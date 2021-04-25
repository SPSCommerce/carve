import networkx as nx
import concurrent.futures
from networkx.readwrite import json_graph
import json
import os
import sys
from copy import deepcopy
from c_carve import load_graph, save_graph, carve_role_arn
from c_disco import discover_org_accounts
from c_aws import *
from multiprocessing import Process, Pipe
import time


def start_carve_deployment(event, context, key=False):
    # read graph from s3 key in event
    if not key:
        key = event['Records'][0]['s3']['object']['key']

    G = load_graph(key, local=False)

    # move deployment object to deploy_started path
    filename = key.split('/')[-1]
    deploy_key = f"deploy_active/{filename}"
    aws_purge_s3_path("deploy_active/")
    aws_copy_s3_object(key, deploy_key)
    # aws_delete_s3_object(key, current_region)

    print(f'deploying graph: {key}')

    # create deploy buckets in all required regions for deployment files
    regions = deploy_regions(G)
    deploy_buckets = []

    key = "managed_deployment/carve-deploy-bucket.cfn.yml"
    with open(key) as f:
        template = f.read()

    aws_put_direct(template, key)

    for r in regions:
        stackname = f"{os.environ['ResourcePrefix']}carve-managed-bucket-{r}"
        parameters = [
            {
                "ParameterKey": "OrganizationsId",
                "ParameterValue": os.environ['OrganizationsId']
            },
            {
                "ParameterKey": "ResourcePrefix",
                "ParameterValue": os.environ['ResourcePrefix']
            }
        ]
        deploy_buckets.append({
            "StackName": stackname,
            "Parameters": parameters,
            "Account": context.invoked_function_arn.split(":")[4],
            "Region": r,
            "Template": 'managed_deployment/carve-deploy-bucket.cfn.yml'
        })

    if len(list(G.nodes)) > 0:
        name = f"deploy-{filename}-{int(time.time())}"
        aws_start_stepfunction(os.environ['DeployEndpointsStateMachine'], deploy_buckets, name)
    else:
        # if nothing is being deployed, Run cleanup
        name = f"NO-ENDPOINTS-{filename}-{int(time.time())}"
        aws_start_stepfunction(os.environ['CleanupStateMachine'], [], name)


def get_deploy_key(last=False):
    # get either the current or last deployment graph key from s3
    if not last:
        path = 'deploy_active/'
    else:
        path = 'deployed_graph/'
    return aws_newest_s3(path)


def deploy_regions(G):
    # get all other regions where buckets are needed
    regions = set()
    for node in list(G.nodes):
        r = G.nodes().data()[node]['Region']
        if r not in regions:
            regions.add(r)
    return regions    


def deploy_accounts(G):
    # get all other regions where buckets are needed
    accounts = set()
    for node in list(G.nodes):
        r = G.nodes().data()[node]['Account']
        if r not in accounts:
            accounts.add(r)
    return accounts


def sf_DeployPrep(event, context):
    # input will be the completion of all the deploy buckets
    # need to use above logic to load G and determine 

    G = load_graph(get_deploy_key(), local=False)

    propagate_carve_ami(G)
    regions = deploy_regions(G)

    # # update_bucket_policies(G)

    # push CFN snippets to each region
    for r in regions:
        bucket=f"{os.environ['ResourcePrefix']}carve-managed-bucket-{os.environ['OrganizationsId']}-{r}"
        aws_s3_upload('managed_deployment/carve-updater.yml', bucket=bucket)
        aws_s3_upload('managed_deployment/carve-config.json', bucket=bucket)

    return []


def propagate_carve_ami(G):
    ''' if the carve ami in the current region is newer, update the regional copies '''
    regions = deploy_regions(G)

    # all copies get the same time stamped name, use that to compare
    source_image = aws_ssm_get_parameter(f"/{os.environ['ResourcePrefix']}carve-resources/carve-beacon-ami")
    source_name = aws_describe_image(source_image)['Name']
    # kms_key = aws_ssm_get_parameter(f"/{os.environ['ResourcePrefix']}carve-resources/carve-kms-key")
    print(f'AMI source_name: {source_name}')

    parameter = f"/{os.environ['ResourcePrefix']}carve-resources/carve-beacon-ami"

    # threaded copy of all AMIs
    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for region in regions:
            dupe = False
            try:
                ami = aws_ssm_get_parameter(parameter, region=region)
                image = aws_describe_image(ami, region=region)
                print(f'ami in {region}: {image}')
                name = image['Name']
                if name != source_name:
                    print(f'ami names {name} and {source_name} do not match (copying image to {region})')
                    dupe = True

            except Exception as e:
                print(f'error checking regional AMI (copying image to {region}): {e}')
                dupe = True

            if dupe:
                futures.append(executor.submit(
                    aws_copy_image,
                    name=source_name,
                    source_image=source_image,
                    # source_kms=kms_key,
                    region=region))

        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            if 'ImageId' in r:
                aws_ssm_put_parameter(parameter, r['ImageId'], r['region'])

    # update AMI sharing for deployment accounts
    accounts = deploy_accounts(G)
    for region in regions:
        ami = aws_ssm_get_parameter(parameter, region=region)
        while True:
            if ami_ready(ami, region):
                print(f'sharing {ami} in {region} to: {accounts}')
                aws_share_image(ami, accounts, region)
                break
            else:
                # waiting here is not the best... ami sharing should be migrated into deploy steps
                print(f'ami is not ready to share... waiting 30s to check again')
                time.sleep(30)


def ami_ready(ami, region):
    # wait until AMI is available before proceeding
    status = aws_describe_image(ami, region=region)['State']
    if status == 'available':
        return True
    else:
        return False


def deployment_list(G, context):
    ''' return a list of stacks to deploy 
        1 lambda and 1 EC2 instance per VPC
    '''

    # # create a ranking of AZ from most to least occuring
    # azs_ranked = az_rank(G)

    # create a list of deployment dicts
    deploy_beacons = []
    concurrent = len(list(G.nodes))

    with open("managed_deployment/carve-vpc-stack.cfn.json") as f:
        template = json.load(f)

    # determine all VPCs and their account and region
    vpcs = {}
    for subnet in list(G.nodes):
        a = G.nodes().data()[subnet]['Account']
        r = G.nodes().data()[subnet]['Region']
        vpcs[G.nodes().data()[subnet]['VpcId']] = (a, r)

    # generate 1 CFN stack per VPC
    for vpc, ar in vpcs.items():

        account = ar[0]
        region = ar[1]

        # copy the CFN template to make a new stack from
        vpc_template = deepcopy(template)

        # all subnets in the VPC
        vpc_subnets = [x for x,y in G.nodes(data=True) if y['VpcId'] == vpc]

        # update the VPC CFN template with 1 lambda function per subnet
        # create a list of subnets for CFN parameters
        for subnet in vpc_subnets:
            Function = deepcopy(vpc_template['Resources']['Function'])
            Function['Properties']['FunctionName'] = f"{os.environ['ResourcePrefix']}carve-{subnet}"
            Function['Properties']['Environment']['Variables']['VpcSubnetIds'] = subnet
            Function['Properties']['VpcConfig']['SubnetIds'] = [subnet]

            name = f"Function{subnet.split('-')[-1]}"
            vpc_template['Resources'][name] = deepcopy(Function)

        # remove orig templated function
        del vpc_template['Resources']['Function']

        # push template to s3
        key = f"managed_deployment/{vpc}.cfn.json"
        data = json.dumps(vpc_template, ensure_ascii=True, indent=2, sort_keys=True)
        aws_put_direct(data, key)
    
        image_id = aws_ssm_get_parameter(f"/{os.environ['ResourcePrefix']}carve-resources/carve-beacon-ami", region=region)
        scale = aws_ssm_get_parameter(f"/{os.environ['ResourcePrefix']}carve-resources/scale")

        if scale == 'none':
            desired = 0
        elif scale == 'subnet':
            desired = len(vpc_subnets)
        elif scale == 'vpc':
            desired = 1

        stack = {}
        stack['StackName'] = f"{os.environ['ResourcePrefix']}carve-managed-{vpc}"
        stack['Account'] = account
        stack['Region'] = region
        stack['Template'] = key
        stack['Parameters'] = [
          {
            "ParameterKey": "VpcId",
            "ParameterValue": vpc
          },
          {
            "ParameterKey": "VpcSubnetIds",
            "ParameterValue": ','.join(vpc_subnets)
          },      
          {
            "ParameterKey": "ResourcePrefix",
            "ParameterValue": os.environ['ResourcePrefix']
          },
          {
            "ParameterKey": "ImageId",
            "ParameterValue": image_id
          },
          {
            "ParameterKey": "CarveSNSTopicArn",
            "ParameterValue": os.environ['CarveSNSTopicArn']
          },
          {
            "ParameterKey": "MaxSize",
            "ParameterValue": str(len(vpc_subnets))
          },
          {
            "ParameterKey": "DesiredSize",
            "ParameterValue": str(desired)
          }
        ]

        deploy_beacons.append(stack)


    return deploy_beacons



# def az_rank(G):
#     # sort all AZs in graph by most to least used per region
#     # returns regions with sorted list of AZs = {<region>: [<az>, <az>, <az>]}

#     ### really need other criteria options here... first would be subnets with IGW, then maybe tags?
#     regions = {}
#     for vpc in list(G.nodes):
#         region = G.nodes().data()[vpc]['Region']
#         for subnet in G.nodes().data()[vpc]['Subnets']:
#             az = subnet['AvailabilityZoneId']
#             if region not in regions:
#                 regions[region] = {az: 1}
#             else:
#                 if az in regions[region].keys():
#                     regions[region][az] = regions[region][az] + 1
#                 else:
#                     regions[region][az] = 1

#     sorted_regions = {}
#     for region, azs in regions.items():
#         sorted_regions[region] = sorted(regions[region].items(), key=lambda x: x[1], reverse=True)

#     return sorted_regions



def update_bucket_policies(G):

    # determine which accounts have resources in each region in the graph
    regions = {}
    for vpc in list(G.nodes):
        print(vpc)
        region = G.nodes().data()[vpc]['Region']
        account = G.nodes().data()[vpc]['Account']
        if region in regions:
            if account not in regions[region]:
                regions[region].append(account)
        else:
            regions[region] = [account]

    # update the policy of each regional bucket
    for region, accounts in regions.items():
        bucket = f"{os.environ['ResourcePrefix']}carve-managed-bucket-{os.environ['OrganizationsId']}-{region}"
        policy = aws_get_bucket_policy(bucket)
        # get all account arns that need to deploy thru this region
        arns = []
        for a in accounts:
            arns.append(f"arn:aws:iam::{a}:root")

        statement = []

        # copy existing statements, omitting existing carve-deploy Sid
        for s in template['Resources']['CarveS3BucketPolicy']['Properties']['PolicyDocument']['Statement']:
            if s['Sid'] != 'DeploymentAccess':
                statement.append(deepcopy(s))

        statement.append(
            {
                "Sid": f"DeploymentAccess",
                "Effect": "Allow",
                "Action": ["s3:Get"],
                "Resource":  f"arn:aws:s3:::{os.environ['ResourcePrefix']}carve-managed-bucket-{os.environ['OrganizationsId']}-{region}",
                "Principal": {"AWS": arns}
            }
        )
        # policy = "PolicyDocument": {"Statement": deepcopy(statement)}

    # return json.dumps(policy)
    return


def codepipline_job(event, context):
    param = event['CodePipeline.job']['data']['actionConfiguration']['configuration']['UserParameters']

    if param == 'UpdateEndpoints':
        if os.environ['PropogateUpdates'] == 'True':
            deploy_key = get_deploy_key(last=True)
            if deploy_key is not None:
                # copy deploy key to start deployment
                key_name = deploy_key.split('/')[-1]
                aws_copy_s3_object(deploy_key, f'deploy_input/{key_name}')
                # start_carve_deployment(event, context, key=deploy_key)
            else:
                print('No previous deploy key to run updates with')
        else:
            print('Updating endpoints is disabled')

    elif param == 'BucketNotification':
        aws_create_s3_path('deploy_input/')
        aws_put_bucket_notification('deploy_input/', context.invoked_function_arn)

    # let the pipeline continue
    aws_codepipeline_success(event['CodePipeline.job']['id'])


def sf_CreateSubscriptions(context):
    # create SNS subscriptions to all accounts with deployments
    G = load_graph(get_deploy_key(), local=False)
    accounts = deploy_accounts(G)
    prefix = os.environ['ResourcePrefix']

    # create a CFN template with SNS subscriptions and lambda invoke permissions
    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "SNS Topic Subscriptions for Carve",
        "Resources": {}
    }
    for account in accounts:
        template['Resources'][f'Sub{account}'] = {
            "Type": "AWS::SNS::Subscription",
            "Properties": {
                "Endpoint": context.invoked_function_arn,
                "Protocol": "Lambda",
                "TopicArn": f"arn:aws:sns:{current_region}:{account}:{prefix}carve-account-events"
            }
        }
        template['Resources'][f'Invoke{account}'] = {
            "Type": "AWS::Lambda::Permission",
            "Properties": {
                "Action": "lambda:InvokeFunction",
                "Principal": "sns.amazonaws.com",
                "SourceArn": f"arn:aws:sns:{current_region}:{account}:{prefix}carve-account-events",
                "FunctionName": context.invoked_function_arn
            }
        }

    # deploy the template
    stackname = f"{os.environ['ResourcePrefix']}carve-managed-sns-subscriptions"
    key = f"managed_deployment/{stackname}.json"
    aws_put_direct(json.dumps(template, ensure_ascii=True, indent=2, sort_keys=True), key)

    deploy_sns = [{
            "StackName": stackname,
            "Parameters": [],
            "Account": context.invoked_function_arn.split(":")[4],
            "Region": current_region,
            "Template": key
        }]

    return deploy_sns

    # name = f"deploy-sns-{int(time.time())}"
    # aws_start_stepfunction(os.environ['DeployEndpointsStateMachine'], deploy_sns, name)

 
def sf_GetDeploymentList(context):
    G = load_graph(get_deploy_key(), local=False)
    return deployment_list(G, context)


def sf_DeploymentComplete(context):
    # move deployment object
    deploy_key = get_deploy_key()
    key_name = deploy_key.split('/')[-1]
    aws_copy_s3_object(deploy_key, f'deployed_graph/{key_name}')
    aws_delete_s3_object(deploy_key, current_region)


def deploy_steps_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    response = {}

    if event['DeployAction'] == 'EndpointDeployPrep':
        response = sf_DeployPrep(event, context)

    if event['DeployAction'] == 'GetDeploymentList':
        response = sf_GetDeploymentList(context)

    if event['DeployAction'] == 'CreateSubscriptions':
        response = sf_CreateSubscriptions(context)

    if event['DeployAction'] == 'DeploymentComplete':
        response = sf_DeploymentComplete(context)
        
    # return json to step function
    return json.dumps(response, default=str)

