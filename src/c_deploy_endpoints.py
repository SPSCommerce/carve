import networkx as nx
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

    regions = deploy_regions(G)

    # create deploy buckets in all required regions for deployment files
    deploy_buckets = []

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
    for vpc in list(G.nodes):
        r = G.nodes().data()[vpc]['Region']
        # if r != current_region:
        if r not in regions:
            regions.add(r)
    return regions    


def sf_DeployPrep(event, context):
    # input will be the completion of all the deploy buckets
    # need to use above logic to load G and determine 

    G = load_graph(get_deploy_key(), local=False)

    # # update_bucket_policies(G)

    # # push lambda deploy pkg and reqs layer pkg to regional S3 buckets
    # # get all other regions where buckets are needed
    # regions = set()
    # for vpc in list(G.nodes):
    #     r = G.nodes().data()[vpc]['Region']
    #     if r not in regions:
    #         regions.add(r)

    # codekey = f"lambda_packages/{os.environ['GITSHA']}/package.zip"
    # reqskey = f"lambda_packages/{os.environ['GITSHA']}/reqs_package.zip"

    # for r in regions:
    #     aws_copy_s3_object(
    #         key=codekey,
    #         target_key=codekey,
    #         source_bucket=os.environ['CodeBucket'],
    #         target_bucket=f"{os.environ['ResourcePrefix']}carve-managed-bucket-{os.environ['OrganizationsId']}-{r}"
    #         )
    #     aws_copy_s3_object(
    #         key=reqskey,
    #         target_key=reqskey,
    #         source_bucket=os.environ['CodeBucket'],
    #         target_bucket=f"{os.environ['ResourcePrefix']}carve-managed-bucket-{os.environ['OrganizationsId']}-{r}"
    #         )

    deployment_targets = deploy_layers(G, context)

    return deployment_targets


def deploy_layers(G, context):
    regions = deploy_regions(G)

    # create lambda layers in all required regions for deployment
    deploy_layers = []

    # for r in regions:
    #     stackname = f"{os.environ['ResourcePrefix']}carve-managed-layers-{r}"
    #     parameters = [
    #         {
    #             "ParameterKey": "OrganizationsId",
    #             "ParameterValue": os.environ['OrganizationsId']
    #         },
    #         {
    #             "ParameterKey": "S3Bucket",
    #             "ParameterValue": os.environ['CarveS3Bucket']
    #         },
    #         {
    #             "ParameterKey": "GITSHA",
    #             "ParameterValue": os.environ['GITSHA']
    #         },
    #         {
    #             "ParameterKey": "ResourcePrefix",
    #             "ParameterValue": os.environ['ResourcePrefix']
    #         }
    #     ]
    #     deploy_layers.append({
    #         "StackName": stackname,
    #         "Parameters": parameters,
    #         "Account": context.invoked_function_arn.split(":")[4],
    #         "Region": r,
    #         "Template": 'managed_deployment/carve-layer.cfn.yml'
    #     })

    return deploy_layers
    # if len(deploy_layers) > 0:
    #     name = f"deploy-layers-{int(time.time())}"
    #     aws_start_stepfunction(os.environ['DeployEndpointsStateMachine'], deploy_layers, name)


def deployment_list(G, context):
    ''' return a list of stacks to deploy 
        1 lambda and 1 EC2 instance per VPC
    '''
    # create a ranking of AZ from most to least occuring
    azs_ranked = az_rank(G)

    # create a list of deployment dicts
    deployment_targets = []
    concurrent = len(list(G.nodes))
    for vpc in list(G.nodes):
        vpc_data = G.nodes().data()[vpc]

        # of available subnets, select the the highest ranked AZ for the region
        # this logic minimizes cross AZ traffic across the Org
        s = False
        subnet_id = ""
        while not s:
            for ranked_az in azs_ranked[vpc_data['Region']]:
                for subnet in vpc_data['Subnets']:
                    az = subnet['AvailabilityZoneId']
                    if az == ranked_az[0]:
                        subnet_id = subnet['SubnetId']
                        s = True

        # add lambda stack first
        target = {}
        target['StackName'] = f"{os.environ['ResourcePrefix']}carve-managed-lambda-{vpc}"
        target['Account'] = vpc_data['Account']
        target['Region'] = vpc_data['Region']
        target['Template'] = "managed_deployment/carve-vpc-lambda.sam.yml"
        target['Parameters'] = [
          {
            "ParameterKey": "VpcId",
            "ParameterValue": vpc
          },
          {
            "ParameterKey": "VpcSubnetIds",
            "ParameterValue": subnet_id
          },
          {
            "ParameterKey": "ResourcePrefix",
            "ParameterValue": os.environ['ResourcePrefix']
          }
        ]

        deployment_targets.append(target)

        # add ec2 stack next
        target = {}
        target['StackName'] = f"{os.environ['ResourcePrefix']}carve-managed-ec2-{vpc}"
        target['Account'] = vpc_data['Account']
        target['Region'] = vpc_data['Region']
        target['Template'] = "managed_deployment/carve-vpc-ec2.cfn.yml"
        target['Parameters'] = [
          {
            "ParameterKey": "VpcId",
            "ParameterValue": vpc
          },
          {
            "ParameterKey": "VpcSubnetIds",
            "ParameterValue": subnet_id
          },      
          {
            "ParameterKey": "ResourcePrefix",
            "ParameterValue": os.environ['ResourcePrefix']
          },
          {
            "ParameterKey": "CarveSNSTopicArn",
            "ParameterValue": os.environ['CarveSNSTopicArn']
          }
        ]
        deployment_targets.append(target)


    return deployment_targets



def az_rank(G):
    # sort all AZs in graph by most to least used per region
    # returns regions with sorted list of AZs = {<region>: [<az>, <az>, <az>]}

    ### really need other criteria options here... first would be subnets with IGW, then maybe tags?
    regions = {}
    for vpc in list(G.nodes):
        region = G.nodes().data()[vpc]['Region']
        for subnet in G.nodes().data()[vpc]['Subnets']:
            az = subnet['AvailabilityZoneId']
            if region not in regions:
                regions[region] = {az: 1}
            else:
                if az in regions[region].keys():
                    regions[region][az] = regions[region][az] + 1
                else:
                    regions[region][az] = 1

    sorted_regions = {}
    for region, azs in regions.items():
        sorted_regions[region] = sorted(regions[region].items(), key=lambda x: x[1], reverse=True)

    return sorted_regions



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
                start_carve_deployment(event, context, key=deploy_key)
            else:
                print('No previous deploy key to run updates with')
        else:
            print('Updating endpoints is disabled')

    elif param == 'BucketNotification':
        aws_create_s3_path('deploy_input/')
        aws_put_bucket_notification('deploy_input/', context.invoked_function_arn)

    # let the pipeline continue
    aws_codepipeline_success(event['CodePipeline.job']['id'])



def sf_GetDeploymentList(context):
    G = load_graph(get_deploy_key(), local=False)
    return deployment_list(G, context)


def sf_DeploymentComplete():
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

    if event['DeployAction'] == 'DeploymentComplete':
        response = sf_DeploymentComplete()
        
    # return json to step function
    return json.dumps(response, default=str)

