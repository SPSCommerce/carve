import networkx as nx
from networkx.readwrite import json_graph
import json
import os
import sys
from copy import deepcopy
from c_carve import load_graph, save_graph, carve_role_arn
from c_disco import discover_org_accounts
from c_aws import *
from c_deploy_endpoints import deployment_list, get_deploy_key
from multiprocessing import Process, Pipe
from crhelper import CfnResource
import time


# def delete_carve_endpoints():
#     deploy_carve_endpoints(event, context)


def sf_DescribeDeleteStack(event):
    account = payload['Account']
    credentials = aws_assume_role(carve_role_arn(account), f"carve-deploy-{payload['Region']}")
    response = aws_describe_stack(
        stackname=payload['StackName'],
        region=payload['Region'],
        credentials=credentials
        )

    # create payload for next step in state machine
    # payload = deepcopy(payload)
    payload['StackStatus'] = response['StackStatus']

    return payload


def sf_DeleteStack(payload):
    account = payload['Account']
    region = payload['Region']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-cleanup-{region}")

    # if this is a regional S3 stack, empty the contents first
    s3_stack = f"{os.environ['ResourcePrefix']}carve-{os.environ['OrganizationsId']}-s3-{region}"
    if payload['StackName'] == s3_stack:
        bucket = f"{os.environ['ResourcePrefix']}carve-{os.environ['OrganizationsId']}-{region}"
        aws_purge_s3_bucket(bucket)

    aws_delete_stack(
        stackname=payload['StackName'],
        region=payload['Region'],
        credentials=credentials)

    return payload


def sf_OrganizeDeletions(payload):
    delete_stacks = []
    for task in payload:
        for stack in task['Payload']:
            delete_stacks.append(stack)
    return delete_stacks


def sf_CleanupDeployments():
    '''discover all deployments of carve named stacks and determine if they should exist'''
    # event will be a json array of all final DescribeChangeSetExecution tasks

    # swipe the GraphName from one of the tasks, need to load deployed graph from S3
    # payload = json.loads(event['Input']['Payload'])
    # payload = event['Input']['Payload']

    deploy_key = get_deploy_key()
    G = load_graph(deploy_key, local=False)

    print(f'cleaning up after graph deploy')

    # do not delete any carve stacks that should be deployed
    safe_stacks = []
    for stack in deployment_list(G):
        safe_stacks.append({
            'StackName': stack['StackName'],
            'Account': stack['Account']
            })

    # need all accounts & regions
    accounts = discover_org_accounts()
    regions = aws_all_regions()

    # create discovery list of all accounts/regions for step function
    discover_stacks = []
    for region in regions:
        for account_id, account_name in accounts.items():
            cleanup = {}
            cleanup['Account'] = account_id
            cleanup['Region'] = region
            cleanup['SafeStacks'] = []
            for stack in safe_stacks:
                if stack['Account'] == account_id:
                    cleanup['SafeStacks'].append(stack['StackName'])
            discover_stacks.append(cleanup)

    # returns to a step function iterator
    return discover_stacks


def sf_DeploymentComplete(payload):
    # not functional yet
    sys.exit()

    # should notify of happiness
    # should move deploy graph to completed
    # need to add a final step to state machine

    # move deployment object immediately
    filename = key.split('/')[-1]
    deploy_key = f"deploy_started/{filename}"
    aws_copy_s3_object(key, deploy_key, region)
    aws_delete_s3_object(key, region)


def sf_DiscoverCarveStacks(payload):
    account = payload['Account']
    region = payload['Region']
    safe_stacks = payload['SafeStacks']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-cleanup-{region}")

    # find all carve resource prefix named stacks
    startswith = f"{os.environ['ResourcePrefix']}carve-endpoint-vpc-"
    stacks = aws_find_stacks(startswith, region, credentials)

    if len(stacks) == 0:
        print(f"found no stacks for deletion in {account} in {region}.")        
        return []
    else:
        delete_stacks = []
        for stack in stacks:
            if stack['StackName'] not in safe_stacks:
                print(f"found {stack['StackName']} for deletion")
                # create payloads for delete iterator in state machine
                del_stack = {}
                del_stack['StackName'] = stack['StackName']
                del_stack['Region'] = region
                del_stack['Account'] = account
                delete_stacks.append(del_stack)

        return delete_stacks


        # # load deployment network graph from S3 json file
        # # graph_data = aws_read_s3_direct(deploykey, region)
        # # G = json_graph.node_link_graph(json.loads(graph_data))
        # G = load_graph(deploykey, local=False)

        # # generate a list of all carve stacks not in the graph
        # delete_stacks = []
        # for stack in stacks:
        #     vpc = stack['StackName'].split(startswith)[1]
        #     vpc_id = f"vpc-{vpc}"
        #     # if carve stack is for a vpc not in the graph, delete it
        #     if vpc_id not in list(G.nodes):
        #         # create payloads for delete iterator in state machine
        #         payload = deepcopy(event['Input'])
        #         payload['StackName'] = stack['StackName']
        #         payload['Region'] = region
        #         payload['Account'] = account
        #         delete_stacks.append(payload)

        # return delete_stacks


def  cleanup_steps_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    try:
        payload = event['Payload']['Input']
    except:
        payload = event['Payload']

    if event['Payload']['CleanupAction'] == 'DescribeDeleteStack':
        response = sf_DescribeDeleteStack(payload)

    elif event['Payload']['CleanupAction'] == 'DeleteStack':
        response = sf_DeleteStack(payload)

    elif event['Payload']['CleanupAction'] == 'CleanupDeployments':
        response = sf_CleanupDeployments()

    elif event['Payload']['CleanupAction'] == 'OrganizeDeletions':
        response = sf_OrganizeDeletions(payload)

    elif event['Payload']['CleanupAction'] == 'DiscoverCarveStacks':
        response = sf_DiscoverCarveStacks(payload)

    # return json to step function
    return json.dumps(response, default=str)



