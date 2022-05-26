from re import A
import lambdavars
import networkx as nx
import concurrent.futures
from networkx.readwrite import json_graph
import json
import os
import sys
from copy import deepcopy
from carve import load_graph, get_deploy_key, unique_node_values
from aws import *
from multiprocessing import Process, Pipe
import time


def start_carve_deployment(event, context, key=False, cleanup=True):
    # read graph from s3 key in event
    if not key:
        key = event['Records'][0]['s3']['object']['key']

    G = load_graph(key, local=False)

    # move deployment artifact to deploy_started/ path
    filename = key.split('/')[-1]
    deploy_key = f"deploy_active/{filename}"
    aws_purge_s3_path("deploy_active/")
    aws_copy_s3_object(key, deploy_key)
    # remove the old deployment artifact from s3
    if cleanup:
        aws_delete_s3_object(key, current_region)

    print(f"deploying uploaded graph: {event['Records'][0]['s3']['bucket']['arn']}/{key}")

    # create deploy buckets in all required regions for deployment files
    regions = unique_node_values(G, 'Region')
    try:
        regions.remove(current_region)
    except:
        pass

    deploy_buckets = []

    key = "managed_deployment/carve-managed-bucket.cfn.yml"
    with open(key) as f:
        template = f.read()

    aws_put_direct(template, key)

    for r in regions:
        stackname = f"{os.environ['Prefix']}carve-managed-bucket-{r}"
        parameters = [
            {
                "ParameterKey": "OrgId",
                "ParameterValue": os.environ['OrgId']
            },
            {
                "ParameterKey": "Prefix",
                "ParameterValue": os.environ['Prefix']
            },
            {
                "ParameterKey": "UniqueId",
                "ParameterValue": os.environ['UniqueId']
            }
        ]
        deploy_buckets.append({
            "StackName": stackname,
            "Parameters": parameters,
            "Account": context.invoked_function_arn.split(":")[4],
            "Region": r,
            "Template": key
        })

    # if len(list(G.nodes)) > 0:
    name = f"deploy-{filename}-{int(time.time())}"
    aws_start_stepfunction(os.environ['DeployBeaconsStateMachine'], deploy_buckets, name)
    # else:
    #     # if nothing is being deployed, Run cleanup
    #     name = f"NO-BEACONS-{filename}-{int(time.time())}"
    #     aws_start_stepfunction(os.environ['CleanupStateMachine'], [], name)
    #     # move the deployment file
    #     sf_DeploymentComplete(None)


# def update_vpce_access(accounts):
#     ''' update the carve private vpce access to allow all VPC accounts '''

#     # get service name from the stack output
#     stackname = f"{os.environ['Prefix']}carve-managed-privatelink"
#     stack_info = aws_describe_stack(
#         stackname=stackname,
#         region=current_region,
#         )

#     for output in stack_info['Outputs']:
#         if output['OutputKey'] == 'EndpointService':
#             endpoint_service = output['OutputValue']
#             break

#     outputs = aws_get_stack_outputs_dict(stackname, current_region)
#     endpoint_service = outputs['EndpointService']

#     # get a list of all current principals (account roots) it's shared to
#     #   principals: ['arn:aws:iam::123456789012:root']
#     principals = aws_describe_vpc_endpoint_permissions(endpoint_service)
#     current_accounts = []
#     for p in principals:
#         current_accounts.append(p.split(':')[4])

#     # build lists of all accounts to add/remove
#     remove = []
#     add = []
#     for a in current_accounts:
#         if a not in accounts:
#             remove.append(f"arn:aws:iam::{a}:root")
#     for a in accounts:
#         if a not in current_accounts:
#             add.append(f"arn:aws:iam::{a}:root")

#     # update carve private vpce access
#     aws_modify_vpc_endpoint_permissions(endpoint_service, add_principals=add, remove_principals=remove)



def sf_DeployPrep():
    ''' if the carve ami in the current region is newer, update the regional copies '''
    G = load_graph(get_deploy_key(), local=False)
    
    # # update the carve vpce access with all accounts in the deployment
    # accounts = unique_node_values(G, 'Account')
    # update_vpce_access(accounts)

    # # this is disabled now that carve does not use EC2 for beacons
    # regions = unique_node_values(G, 'Region')
    
    # distribute_regional_carve_amis(regions)
    return


def distribute_regional_carve_amis(regions):
    parameter = f"/{os.environ['Prefix']}carve-resources/carve-beacon-ami"
    print(f"getting parameter {parameter} in {current_region}")
    source_image = aws_ssm_get_parameter(parameter)
    print(f"source_image: {source_image}")
    source_name = aws_describe_image(source_image)['Name']
    print(f'AMI source_name: {source_name}')

    # threaded copy of all AMIs
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
                    region=region))

        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            if 'ImageId' in r:
                aws_ssm_put_parameter(parameter, r['ImageId'], r['region'])


def sf_DeployPrepCheck():
    # since carve is not using ec2 for beacons, this is not needed, simply return complete
    # so the step function can continue. will be removed with step function refactor
    payload = {'ImageStatus': 'complete'}

    # G = load_graph(get_deploy_key(), local=False)
    # regions = deploy_regions(G)
    # accounts = deploy_accounts(G)

    # parameter = f"/{os.environ['Prefix']}carve-resources/carve-beacon-ami"

    # # check if all AMIs are ready in each region
    # complete = True
    # for region in regions:
    #     ami = aws_ssm_get_parameter(parameter, region=region)
    #     if ami_ready(ami, region):
    #         # update AMI sharing for deployment accounts
    #         print(f'sharing {ami} in {region} to: {accounts}')
    #         aws_share_image(ami, accounts, region)
    #     else:
    #         print(f'ami in {region} is not ready.')
    #         complete = False

    # if complete:
    #     payload = {'ImageStatus': 'complete'}
    # else:
    #     payload = {'ImageStatus': 'pending'}

    return payload


def ami_ready(ami, region):
    # wait until AMI is available before proceeding
    status = aws_describe_image(ami, region=region)['State']
    if status == 'available':
        return True
    else:
        return False


def beacon_ec2_template(vpc, vpc_subnets, account, region):
    # all subnets in the VPC
    with open("managed_deployment/carve-vpc-stack-ec2.cfn.json") as f:
        vpc_template = json.load(f)

    with open("managed_deployment/subnet_ec2_lambda.py") as f:
        lambda_code = f.read()

    # update the VPC CFN template with 1 lambda function per subnet
    # create a list of subnets for CFN parameters
    for subnet in vpc_subnets:
        Function = deepcopy(vpc_template['Resources']['SubnetFunction'])
        Function['Properties']['FunctionName'] = f"{os.environ['Prefix']}carve-{subnet}"
        Function['Properties']['Environment']['Variables']['VpcSubnetIds'] = subnet
        Function['Properties']['VpcConfig']['SubnetIds'] = [subnet]
        Function['Properties']['Code']['ZipFile'] = lambda_code
        name = f"Function{subnet.split('-')[-1]}"
        vpc_template['Resources'][name] = deepcopy(Function)

    # remove orig templated function
    del vpc_template['Resources']['SubnetFunction']

    image_id = aws_ssm_get_parameter(f"/{os.environ['Prefix']}carve-resources/carve-beacon-ami", region=region)

    stack = {}
    stack['StackName'] = f"{os.environ['Prefix']}carve-managed-beacons-{vpc}"
    stack['Account'] = account
    stack['Region'] = region
    stack['Template'] = f"managed_deployment/{vpc}.cfn.json"
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
            "ParameterKey": "Prefix",
            "ParameterValue": os.environ['Prefix']
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
            "ParameterKey": "CarveCoreRegion",
            "ParameterValue": current_region
        },
        {
            "ParameterKey": "MaxSize",
            "ParameterValue": str(len(vpc_subnets))
        },
        {
            "ParameterKey": "DesiredSize",
            "ParameterValue": str(len(vpc_subnets))
        },
        {
            "ParameterKey": "PublicIPs",
            "ParameterValue": "false"
        }
    ]

    return vpc_template, stack

def beacon_pl_template(vpc, vpc_subnets, account, vpce_service, region):
    # all subnets in the VPC
    with open("managed_deployment/carve-vpc-stack-pl.cfn.json") as f:
        vpc_template = json.load(f)

    with open("managed_deployment/subnet_pl_lambda.py") as f:
        lambda_code = f.read()

    # update the VPC CFN template with 1 lambda function per subnet
    # create a list of subnets for CFN parameters
    for subnet in vpc_subnets:
        Function = deepcopy(vpc_template['Resources']['SubnetFunction'])
        Function['Properties']['FunctionName'] = f"{os.environ['Prefix']}carve-{subnet}"
        Function['Properties']['Environment']['Variables']['VpcSubnetIds'] = subnet
        Function['Properties']['VpcConfig']['SubnetIds'] = [subnet]
        Function['Properties']['Code']['ZipFile'] = lambda_code
        name = f"Function{subnet.split('-')[-1]}"
        vpc_template['Resources'][name] = deepcopy(Function)

    # remove orig templated function
    del vpc_template['Resources']['SubnetFunction']

    # # get service name
    # stack_info = aws_describe_stack(
    #     stackname=f"{os.environ['Prefix']}carve-privatelink",
    #     region=current_region,
    #     )

    # for output in stack_info['Outputs']:
    #     if output['OutputKey'] == 'EndpointService':
    #         service_name = f"com.amazonaws.vpce.{current_region}.{output['OutputValue']}"

    stack = {}
    stack['StackName'] = f"{os.environ['Prefix']}carve-managed-beacons-{vpc}"
    stack['Account'] = account
    stack['Region'] = region
    stack['Template'] = f"managed_deployment/{vpc}.cfn.json"
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
            "ParameterKey": "Prefix",
            "ParameterValue": os.environ['Prefix']
        },
        {
            "ParameterKey": "CarveSNSTopicArn",
            "ParameterValue": os.environ['CarveSNSTopicArn']
        },
        {
            "ParameterKey": "ServiceName",
            "ParameterValue": vpce_service
        }
    ]

    return vpc_template, stack


def deployment_list(G, context):
    ''' return a list of stacks to deploy 
        1 lambda and 1 EC2 instance per VPC
    '''

    # # create a ranking of AZ from most to least occuring
    # azs_ranked = az_rank(G)

    # create a list of deployment dicts
    deploy_beacons = []
    concurrent = len(list(G.nodes))

    # determine all VPCs and their account and region
    vpcs = {}
    regions = set()
    for subnet in list(G.nodes):
        a = G.nodes().data()[subnet]['Account']
        r = G.nodes().data()[subnet]['Region']
        vpcs[G.nodes().data()[subnet]['VpcId']] = (a, r)
        regions.add(r)

    region_map = {}
    for region in regions:
        # get carve private link stack outputs
        stackname = f"{os.environ['Prefix']}carve-managed-privatelink-{region}"
        outputs = aws_get_stack_outputs_dict(stackname, current_region)
        try:
            region_map[region] = f"com.amazonaws.vpce.{current_region}.{outputs['EndpointService']}"
        except:
            raise f"No private link service found in region {region}"


    # generate 1 CFN stack per VPC
    for vpc, ar in vpcs.items():

        account = ar[0]
        region = ar[1]

        vpc_subnets = [x for x,y in G.nodes(data=True) if y['VpcId'] == vpc]

        # vpc_template = beacon_ec2_template(vpc, vpc_subnets, account, region)
        vpc_template, stack = beacon_pl_template(vpc, vpc_subnets, account, region_map[region], region)

        # push template to s3
        key = f"managed_deployment/{vpc}.cfn.json"
        data = json.dumps(vpc_template, ensure_ascii=True, indent=2, sort_keys=True)
        aws_put_direct(data, key)
    
        deploy_beacons.append(stack)


    return deploy_beacons


# def parse_cfn_sns(m):
#     # incoming SNS from CloudFormation have the message as a multi-line string
#     # each line is formatted gross. this cleans it up into a proper dict
#     if m.startswith("StackId="):
#         message = {}
#         lines = m.splitlines()
#         for l in lines:
#             k = l.split('=')[0]
#             v = l.split('=')[1].split("'")[1::2]
#             if k == "ResourceProperties":
#                 try:
#                     v = json.loads(v[0])
#                 except:
#                     pass
#             message[k] = v
#         return message


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



# def update_bucket_policies(G):

#     # determine which accounts have resources in each region in the graph
#     regions = {}
#     for vpc in list(G.nodes):
#         print(vpc)
#         region = G.nodes().data()[vpc]['Region']
#         account = G.nodes().data()[vpc]['Account']
#         if region in regions:
#             if account not in regions[region]:
#                 regions[region].append(account)
#         else:
#             regions[region] = [account]

#     # update the policy of each regional bucket
#     if os.environ['UniqueId'] == "":
#         unique = os.environ['OrgId']
#     else:
#         unique = os.environ['UniqueId']

#     for region, accounts in regions.items():
#         bucket = f"{os.environ['Prefix']}carve-managed-bucket-{unique}-{region}"
#         policy = aws_get_bucket_policy(bucket)
#         # get all account arns that need to deploy thru this region
#         arns = []
#         for a in accounts:
#             arns.append(f"arn:aws:iam::{a}:root")

#         statement = []

#         # copy existing statements, omitting existing carve-deploy Sid
#         for s in template['Resources']['CarveS3BucketPolicy']['Properties']['PolicyDocument']['Statement']:
#             if s['Sid'] != 'DeploymentAccess':
#                 statement.append(deepcopy(s))

#         statement.append(
#             {
#                 "Sid": f"DeploymentAccess",
#                 "Effect": "Allow",
#                 "Action": ["s3:Get"],
#                 "Resource":  f"arn:aws:s3:::{os.environ['Prefix']}carve-managed-bucket-{unique}-{region}",
#                 "Principal": {"AWS": arns}
#             }
#         )
#         # policy = "PolicyDocument": {"Statement": deepcopy(statement)}

#     # return json.dumps(policy)
#     return


def codepipline_job(event, context):
    param = event['CodePipeline.job']['data']['actionConfiguration']['configuration']['UserParameters']

    if param == 'UpdateManagedStacks':
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
            print('Updating Managed Stacks is disabled')

    elif param == 'BucketNotification':
        aws_create_s3_path('deploy_input/')
        aws_put_bucket_notification('deploy_input/', context.invoked_function_arn)

    # let the pipeline continue
    aws_codepipeline_success(event['CodePipeline.job']['id'])


# def sf_CreateSubscriptions(context):
#     # create SNS subscriptions to all org accounts with deployments
#     G = load_graph(get_deploy_key(), local=False)
#     accounts = deploy_accounts(G)
#     accounts.remove(context.invoked_function_arn.split(':')[4])

#     prefix = os.environ['Prefix']

#     # create a CFN template with SNS subscriptions and lambda invoke permissions
#     template = {
#         "AWSTemplateFormatVersion": "2010-09-09",
#         "Description": "SNS Topic Subscriptions for Carve",
#         "Resources": {}
#     }
#     for account in accounts:

#         template['Resources'][f'Sub{account}'] = {
#             "Type": "AWS::SNS::Subscription",
#             "Properties": {
#                 "Endpoint": context.invoked_function_arn,
#                 "Protocol": "Lambda",
#                 "TopicArn": f"arn:aws:sns:{current_region}:{account}:{prefix}carve-account-events"
#             }
#         }
#         template['Resources'][f'Invoke{account}'] = {
#             "Type": "AWS::Lambda::Permission",
#             "Properties": {
#                 "Action": "lambda:InvokeFunction",
#                 "Principal": "sns.amazonaws.com",
#                 "SourceArn": f"arn:aws:sns:{current_region}:{account}:{prefix}carve-account-events",
#                 "FunctionName": context.invoked_function_arn
#             }
#         }

#     # deploy the template
#     stackname = f"{os.environ['Prefix']}carve-managed-sns-subscriptions"
#     key = f"managed_deployment/{stackname}.json"
#     aws_put_direct(json.dumps(template, ensure_ascii=True, indent=2, sort_keys=True), key)

#     deploy_sns = [{
#             "StackName": stackname,
#             "Parameters": [],
#             "Account": context.invoked_function_arn.split(":")[4],
#             "Region": current_region,
#             "Template": key
#         }]

#     return deploy_sns



def sf_GetDeploymentList(context):
    '''
    returns a list of cfn stack deployments using deployment_list() to render the templates
    and generate the stack parameters
    '''
    G = load_graph(get_deploy_key(), local=False)
    stack_deployments = deployment_list(G, context)

    return stack_deployments


def sf_DeploymentComplete(context):
    # move deployment object
    deploy_key = get_deploy_key()
    if not deploy_key:
        raise Exception('No deployment key found')

    key_name = deploy_key.split('/')[-1]
    aws_copy_s3_object(deploy_key, f'deployed_graph/{key_name}')
    
    # 
    # aws_delete_s3_object(deploy_key, current_region)

    ## should carve execute the last scale up/down? Code is below

    # executions = aws_states_list_executions(arn=os.environ['ScaleStateMachine'], results=1)

    # last_exec = executions[0]['executionArn']
    
    # response = aws_states_describe_execution(last_exec)

    # input = json.loads(response['input'])
    # print(f"Running scale step function with last input: {input}")

    # name = f"deployment-complete-scale-{input['scale']}-{int(time.time())}"
    # aws_start_stepfunction(os.environ['ScaleStateMachine'], input, name)



def deploy_steps_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    response = {}

    if event['DeployAction'] == 'DeployPrepCheck':
        response = sf_DeployPrepCheck()

    if event['DeployAction'] == 'BeaconDeployPrep':
        response = sf_DeployPrep()

    if event['DeployAction'] == 'GetDeploymentList':
        response = sf_GetDeploymentList(context)

    # if event['DeployAction'] == 'CreateSubscriptions':
    #     response = sf_CreateSubscriptions(context)

    if event['DeployAction'] == 'DeploymentComplete':
        response = sf_DeploymentComplete(context)
        
    # return json to step function
    return json.dumps(response, default=str)

if __name__ == '__main__':
    sf_DeploymentComplete(None)