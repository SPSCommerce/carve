import networkx as nx
from networkx.readwrite import json_graph
import json
import os
import sys
from copy import deepcopy
from c_carve import load_graph, save_graph
from c_disco import discover_org_accounts
from c_aws import *
from multiprocessing import Process, Pipe
from boto3.session import Session
from crhelper import CfnResource
import time

def deploy_carve_endpoints(event, context):
    # event must include:
    #   event['graph_path'] = graph path in the carve-org-* controlled S3 bucket
    #   event['role'] = role pattern to use across all accounts
    # begin the workflow to deploy endpoints to all VPCs in the graph_path
    # use G to create a payload to start to the carve deployment step function
    # the step function starts with a list of lambda invoke payloads
    # - each lamba payload in the list must contain:
    #   - account
    #   - region
    #   - vpc id
    #   - vpc name
    #   - temporary IAM credentials

    # read graph from s3 event
    key = event['Records'][0]['s3']['object']['key']
    region = os.environ['AWS_REGION']
    try:
        graph_data = aws_read_s3_direct(key, region)
        G = json_graph.node_link_graph(json.load(graph_data))
    except Exception as e:
        print(f'error loading graph: {e}')
        sys.exit()


    # move object immediately
    filename = key.split('/')[-1]
    deploy_key = f"deploying/{filename}"
    response = aws_copy_s3_object(key, deploy_key, region)
    print(f"copy response: {response}")
    response = aws_delete_s3_object(key, region)
    print(f"delete response: {response}")

    # create all IAM assumed role sessions for deployment now, and store their credentials
    accounts = set()
    for vpc in list(G.nodes):
        accounts.add(G.nodes().data()[vpc]['Account'])

    role_name = f"{os.environ['ResourcePrefix']}carve-lambda-{os.environ['OrganizationsId']}"

    credentials = aws_parallel_role_creation(accounts, f"arn:aws:iam::*:role/{role_name}")

    if 'Name' in G.graph:
        graph_name = G.graph['Name']
    else:
        graph_name = f'c_deployed_{int(time.time())}'

    deployment_targets = []
    for vpc in list(G.nodes):
        vpc_data = G.nodes().data()[vpc]
        target = {}
        target['Account'] = vpc_data['Account']
        target['GraphName'] = graph_name
        target['Region'] = vpc_data['Region']
        target['VpcId'] = vpc
        target['VpcName'] = vpc_data['Name']
        target['Credentials'] = credentials[vpc_data['Account']]
        target['Role'] = role
        deployment_targets.append(target)

    # cache deployment tags now to local lambda disk to reduce api calls
    tags = aws_get_carve_tags(context.invoked_function_arn)

    # start deployment state machine with graph
    aws_start_stepfunction(os.environ['CarveDeployStepFunction'], deployment_targets)
    # mock_stepfunction(os.environ['CarveDeployStepFunction'], deployment_targets)


# def mock_stepfunction(arn, deployment_targets):
#     # mock state machine activity, except sequentially
#     print(f'mock invoke of {arn}')
#     from c_entrypoint import lambda_hander
#     for target in deployment_targets:
#         event = {
#             "Input": target
#             "DeployAction": "CreateStack"
#             }

#         lambda_hander({}, event)


def seed_deployment_files():
    # seed the same lambda package that created this deployment to the carve s3 bucket
    aws_download_file_carve_s3(
        key=os.environ['CodeKey'],
        file_path='package.zip',
        bucket=os.environ['CodeBucket']
        )
    # push package to carve deployment folder

    # unzip package

def delete_carve_endpoints():
    deploy_carve_endpoints(event, context)

def sf_ExecuteChangeSet(event):

    response = aws_execute_change_set(
        change_set_name=event['Input']['ChangeSetName'],
        region=event['Input']['Region'],
        credentials=event['Input']['Credentials'])

    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    del payload['ChangeSetStatus']

    return payload


def sf_DescribeChangeSetExecution(event):
    response = aws_describe_change_set(
        change_set_name=event['Input']['ChangeSetName'],
        stackname=event['Input']['StackName'],
        region=event['Input']['Region'],
        credentials=event['Input']['Credentials']
        )
    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['ExecuteChangeSetStatus'] = response['Status']

    return payload



def sf_DescribeChangeSet(event):
    stackname = f"carve-endpoint-{event['VpcId']}"
    response = aws_describe_change_set(
        stackname=event['Input']['StackName'],
        region=event['Input']['Region'],
        credentials=event['Input']['Credentials']
        )
    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['ChangeSetStatus'] = response['Status']

    return payload


def sf_CreateChangeSet(event):
    template_url = f"https://s3.amazonaws.com/{os.environ['CarveS3Bucket']}/deployment/carve-vpc.sam.yml"
    parameters = {"OrganizationsId": os.environ['OrganizationsId']}
    changeset_name = aws_create_changeset(
        stackname=event['Input']['StackName'],
        region=event['Input']['Region'],
        template_url=template_url,
        parameters=parameters,
        credentials=event['Input']['Credentials'],
        tags=tags)

    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['ChangeSetName'] = changeset_name
    del payload['StackStatus']

    return payload


def sf_DescribeStack(event):
    stackname = f"carve-endpoint-{event['VpcId']}"
    response = aws_describe_stack(
        stackname=event['Input']['StackName'],
        region=event['Input']['Region'],
        credentials=event['Input']['Credentials']
        )

    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['StackStatus'] = response['StackStatus']

    return payload


def sf_DeleteStack(event):
    aws_delete_stack(
        stackname=event['Input']['StackName'],
        region=event['Region'],
        credentials=event['Credentials'])

    payload = deepcopy(event['Input'])
    return payload


def sf_CleanupDeployments(event, context):
    '''discover all deployments of carve named stacks and determine if they should exist'''
    # event will be a json array of all final DescribeChangeSetExecution tasks

    # need to load deployed graph from S3
    graph_name = None
    for task in event:
        if ['GraphName'] in task:
            graph_name = task['GraphName']
            role = task['Role']
            break

    if graph_name is None:
        print('something went wrong')
        sys.exit()

    # need new creds for all accounts in the org
    accounts = discover_org_accounts()
    credentials = aws_parallel_role_creation(accounts.keys(), role)

    discover_stacks = []
    for account_id, account_name in accounts.items():
        cleanup = {}
        cleanup['Account'] = account_id
        cleanup['StartsWith'] = 'carve-endpoint-vpc-'
        cleanup['GraphName'] = graph_name
        cleanup['Credentials'] = credentials[account_id]
        discover_stacks.append(cleanup)

    # feeds into an step function iterator
    return discover_stacks


def sf_DiscoverStacks(event):
    account = event['Input']['Account']
    credentials = event['Input']['Credentials']
    startswith = event['Input']['StartsWith']
    graph_name = event['Input']['GraphName']

    # create a list to all processes and connections
    processes = []
    parent_connections = []

    s = Session()
    regions = s.get_available_regions('cloudformation')

    for region in regions:
        # process for discovering stacks in account/region
        parent_conn, child_conn = Pipe()
        parent_connections.append(parent_conn)
        process = Process(
            target=_discover_stacks_process,
            args=(startswith, region, credentials, child_conn)
            )
        processes.append(process)
    
    for process in processes:
        process.start()

    # load deployment network graph from S3 json file
    key=f"deployment/deployed_graphs/{graph_name}.json"    
    graph_data = aws_read_s3_direct(key, region)
    G = json_graph.node_link_graph(json.load(graph_data))

    for process in processes:
        process.join()

    delete_stacks = []
    for parent_connection in parent_connections:
        # each connection contains a list of carve stacks and a region
        for stack in parent_connection.recv():
            vpc = stack['StackName'].split(startswith)[1]
            vpc_id = f"vpc-{vpc}"
            # if carve stack is for a vpc not in the graph, delete it
            if vpc_id not in list(G.nodes):
                # create payloads for delete iterator in state machine
                payload = deepcopy(event['Input'])
                payload['StackName'] = stack['StackName']
                payload['Region'] = stack['Region']
                delete_stacks.append(payload)

    return delete_stacks


def _discover_stacks_process(startswith, region, credentials, child_conn):
    stacks = aws_find_stacks(startswith, region, credentials)
    for stack in stacks:
        stack['Region'] = region
    child_conn.send(stacks)
    child_conn.close()


def sf_CreateCarveStack(event, context):
    ''' deploy a carve endpoint/api '''

    tags = aws_get_carve_tags(context.invoked_function_arn)
    print(tags)

    # check if stack already exists
    stackname = f"carve-endpoint-{event['Input']['VpcId']}"
    response = aws_describe_stack(
        stackname=stackname,
        region=event['Input']['Region'],
        credentials=event['Input']['Credentials']
        )

    if response is not None:
        stack = {'StackId': response['StackId']}
    else:
        # create bootstrap stack so a changeset can be created for SAM deploy
        template_url = f"https://s3.amazonaws.com/{os.environ['CarveS3Bucket']}/deployment/carve-vpc-endpoint-bootstrap.cfn.yml"
        parameters = [
            {
                "ParameterKey": "OrganizationsId",
                "ParameterValue": os.environ['OrganizationsId']
            },
            {
                "ParameterKey": "VpcName",
                "ParameterValue": event['Input']['VpcName']
            }
        ]
        stack = aws_create_stack(
            stackname=stackname,
            region=event['Input']['Region'],
            template_url=template_url,
            parameters=parameters,
            credentials=event['Input']['Credentials'],
            tags=tags
            )

    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['StackName'] = stackname
    payload['Tags'] = tags

    return payload


def deploy_steps_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    if event['DeployAction'] == 'DescribeStack':
        response = sf_DescribeStack(event)

    elif event['DeployAction'] == 'DescribeChangeSet':
        response = sf_DescribeChangeSet(event)

    elif event['DeployAction'] == 'DescribeChangeSetExecution':
        response = sf_DescribeChangeSet(event)

    elif event['DeployAction'] == 'CreateCarveStack':
        response = sf_CreateCarveStack(event, context)

    elif event['DeployAction'] == 'CreateChangeSet':
        response = sf_CreateChangeSet(event)

    elif event['DeployAction'] == 'ExecuteChangeSet':
        response = sf_ExecuteChangeSet(event)

    elif event['DeployAction'] == 'DeleteStack':
        response = sf_DeleteStack(event)

    elif event['DeployAction'] == 'CleanupDeployments':
        response = sf_CleanupDeployments(event, context)

    # return json to step function
    return json.dumps(response, default=str)


### CFN custom resource setup the Carve bucket for deply
helper = CfnResource()

def custom_resource_entrypoint(event, context):
    # need to deal with DeleteStackCleanup vs SetupCarveBucket
    helper(event, context)

@helper.create
def deploy_CfnCreate(event, context):
    if 'DeployEventPath' in event['ResourceProperties']:
        path = event['ResourceProperties']['DeployEventPath']
        notification_id = event['ResourceProperties']['NotificationId']
        aws_create_s3_path(path)
        aws_put_bucket_notification(path, notification_id, context.invoked_function_arn)
        helper.Data['Path'] = path
        helper.Data['Notification'] = notification_id

    else:
        pass

@helper.update
def deploy_CfnUpdate(event, context):
    deploy_CfnDelete(event, context)
    deploy_CfnCreate(event, context)


@helper.delete
def deploy_CfnDeletePoll(event, context):
    if len(aws_states_list_executions(os.environ['CarveDeployStepFunction'])) > 0:
        return None
    else:
        return True


@helper.poll_delete
def deploy_CfnDelete(event, context):
    # elif 'OrganizationsId' in event['ResourceProperties']:
    #     delete_carve_endpoints(event, context)
    pass
    # aws_delete_bucket_notification()
    # aws_empty_bucket()

