import networkx as nx
from networkx.readwrite import json_graph
import json
import os
import sys
from copy import deepcopy
from c_carve import load_graph, save_graph, carve_role_arn
from c_disco import discover_org_accounts
from c_aws import *
from c_deploy_endpoints import deploy_list, get_deploy_key
from multiprocessing import Process, Pipe
from crhelper import CfnResource
import time


# def delete_carve_endpoints():
#     deploy_carve_endpoints(event, context)


def sf_DescribeStack(event):
    if 'Payload' in event['Input']:
        payload = event['Input']['Payload']
    else:
        payload = event['Input']

    account = payload['Account']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-deploy-{payload['Region']}")

    response = aws_describe_stack(
        stackname=payload['StackName'],
        region=payload['Region'],
        credentials=credentials
        )

    # create payload for next step in state machine
    payload = deepcopy(payload)
    payload['StackStatus'] = response['StackStatus']

    return payload


def sf_DeleteStack(event):
    payload = event['Input']['Payload']
    # payload = json.loads(event['Input']['Payload'])

    account = payload['Account']
    region = payload['Region']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-cleanup-{region}")

    aws_delete_stack(
        stackname=payload['StackName'],
        region=payload['Region'],
        credentials=credentials)

    payload = deepcopy(event['Input'])
    return payload


def sf_OrganizeDeletions(event):
    payload = event['Input']['Payload']
    # payload = json.loads(event['Input']['Payload'])
    delete_stacks = []
    for task in payload:
        if 'StackName' in task:
            delete_stacks.append(deepcopy(task))

    return delete_stacks


def sf_CleanupDeployments(event, context):
    '''discover all deployments of carve named stacks and determine if they should exist'''
    # event will be a json array of all final DescribeChangeSetExecution tasks

    # swipe the GraphName from one of the tasks, need to load deployed graph from S3
    # payload = json.loads(event['Input']['Payload'])
    # payload = event['Input']['Payload']

    print(event)

    G = load_graph(get_deploy_key(), local=False)

    print(f'cleaning up after graph deploy')

    # do not delete any carve stacks that should be deployed
    safe_stacks = []
    stacks = deploy_list(G)
    for stack in stacks:
        safe_stacks.append(stack['StackName'])

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


def sf_DeploymentComplete(event):
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


def sf_DiscoverCarveStacks(event):
    payload = event['Input']['Payload']
    # payload = json.loads(event['Input']['Payload'])

    account = payload['Account']
    region = payload['Region']
    safe_stacks = payload['SafeStacks']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-cleanup-{region}")

    # find all carve resource prefix named stacks
    startswith = f"{os.environ['ResourcePrefix']}carve-endpoint-vpc-"
    stacks = aws_find_stacks(startswith, region, credentials)

    if len(stacks) == 0:
        return []
    else:
        delete_stacks = []
        for stack in stacks:
            if stack not in safe_stacks:
                # create payloads for delete iterator in state machine
                payload = deepcopy(event['Input'])
                payload['StackName'] = stack['StackName']
                payload['Region'] = region
                payload['Account'] = account
                delete_stacks.append(payload)

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
    if event['CleanupAction'] == 'DescribeStack':
        response = sf_DescribeStack(event)

    elif event['CleanupAction'] == 'DeleteStack':
        response = sf_DeleteStack(event)

    elif event['CleanupAction'] == 'CleanupDeployments':
        response = sf_CleanupDeployments(event, context)

    elif event['CleanupAction'] == 'OrganizeDeletions':
        response = sf_OrganizeDeletions(event, context)

    elif event['CleanupAction'] == 'DiscoverCarveStacks':
        response = sf_DiscoverCarveStacks(event, context)
        response = None

    # return json to step function
    return json.dumps(response, default=str)



