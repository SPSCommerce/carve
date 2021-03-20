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

    # read graph from s3 key in event
    key = event['Records'][0]['s3']['object']['key']
    print(f'deploying graph: {key}')

    try:
        graph_data = aws_read_s3_direct(key, current_region)
        print(graph_data)
        G = json_graph.node_link_graph(json.loads(graph_data))
    except Exception as e:
        print(f'error loading graph: {e}')
        sys.exit()

    # move deployment object to deploy_started path
    filename = key.split('/')[-1]
    deploy_key = f"deploy_started/{filename}"
    aws_copy_s3_object(key, deploy_key, current_region)
    aws_delete_s3_object(key, current_region)

    # push CFN deployment files to S3
    for file in os.listdir('deployment'):
        aws_upload_file_carve_s3(f'deploy_templates/{file}', f'{os.getcwd()}/deployment/{file}')

    # determine accounts carve will deploy to
    accounts = set()
    for vpc in list(G.nodes):
        accounts.add(G.nodes().data()[vpc]['Account'])

    # use the graph name if it contains one
    if 'Name' in G.graph:
        graph_name = G.graph['Name']
    else:
        graph_name = f'c_deployed_{int(time.time())}'

    # create a ranking of AZ from most to least occuring
    azs_ranked = az_rank(G)

    deployment_targets = []
    for vpc in list(G.nodes):
        vpc_data = G.nodes().data()[vpc]
        target = {}

        # select the subnet in the most occuring AZ
        s = False
        while not s:
            for ranked_az in azs_ranked:
                for subnet in vpc_data['Subnets']:
                    az = subnet['AvailabilityZoneId']
                    if az == ranked_az[0]:
                        target['SubnetId'] = subnet['SubnetId']
                        s = True

        target['Account'] = vpc_data['Account']
        target['GraphName'] = graph_name
        target['Region'] = vpc_data['Region']
        target['VpcId'] = vpc
        target['VpcName'] = vpc_data['Name']

        # target['Credentials'] = credentials[vpc_data['Account']]
        target['Role'] = carve_role_arn(vpc_data['Account'])
        deployment_targets.append(target)

    # cache deployment tags now to local lambda disk to reduce api calls
    tags = aws_get_carve_tags(context.invoked_function_arn)

    # start deployment state machine with graph
    aws_start_stepfunction(os.environ['CarveDeployStepFunction'], deployment_targets)
    # mock_stepfunction(os.environ['CarveDeployStepFunction'], deployment_targets)


def az_rank(G):
    # sort all AZs in graph by most to least used
    azs = {}
    for vpc in list(G.nodes):
        vpc_data = G.nodes().data()[vpc]
        for subnet in vpc_data['Subnets']:
            az = subnet['AvailabilityZoneId']
            if az in azs.keys():
                azs[az] = azs[az] + 1
            else:
                azs[az] = 1
    return sorted(azs.items(), key=lambda x: x[1], reverse=True)


def prepS3template(account, accounts):
    try:
        with open('deployment/carve-regional-s3.cfn.json') as f:
            template = (json.load(f))
    except Exception as e:
        print(f'error opening json_graph {json_graph}: {e}')
        return False

    fileout = f'deployment/carve-{account}-s3.cfn.json'

    for a in accounts:
        # append an S3 deploy policy per account to statement in CFN template
        template['Resources']['CarveS3BucketPolicy']['Properties']['PolicyDocument']['Statement'].append({
            "Sid": f"carve-{a}-deploy",
            "Effect": "Allow",
            "Action": [
                "s3:*"
            ],
            "Resource": {
                "Fn::GetAtt": [
                    "CarveS3Bucket",
                    "Arn"
                ]
            },
            "Principal": {
                "AWS": f"arn:aws:iam::{a}:role/{os.environ['ResourcePrefix']}carve-lambda-{os.environ['OrganizationsId']}"
            }
        })

    try:
        os.remove(fileout)
    except:
        pass

    # output template for deployment
    with open(fileout, 'a') as f:
        json.dump(template, f)



def seed_deployment_files():
    # seed the same lambda package that created this deployment to the carve s3 bucket

    prepS3template(account, accounts)

    aws_copy_s3_object(
        key=os.environ['CodeKey'], 
        target_key="deployment/lambda_packages/${GITSHA}.zip",
        region=, 
        source_bucket=, 
        target_bucket=
        )

    aws_get_carve_s3(
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
        changesetname=event['Input']['ChangeSetName'],
        stackname=event['Input']['StackName'],
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
    # payload = json.loads(event['Input']['Payload'])
    if 'Payload' in event['Input']:
        payload = event['Input']['Payload']
    else:
        payload = event['Input']

    account = payload['Account']
    region = payload['Region']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-changeset-{region}")

    response = aws_describe_change_set(
        change_set_name=payload['ChangeSetName'],
        stackname=payload['StackName'],
        region=region,
        credentials=credentials
        )

    # create payload for next step in state machine
    result = deepcopy(payload)
    result['ChangeSetStatus'] = response
    return result


def sf_CreateChangeSet(event, context):
    # payload = json.loads(event['Input']['Payload'])
    if 'Payload' in event['Input']:
        payload = event['Input']['Payload']
    else:
        payload = event['Input']

    account = payload['Account']
    region = payload['Region']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-changeset-{region}")

    template_url = f"https://s3.amazonaws.com/{os.environ['CarveS3Bucket']}/deploy_templates/carve-vpc.sam.yml"

    parameters = [
        {
            "ParameterKey": "VpcId",
            "ParameterValue": payload['VpcId'],
            "UsePreviousValue": False
        },
        {
            "ParameterKey": "VpcEndpointSubnetIds",
            "ParameterValue": payload['SubnetId'],
            "UsePreviousValue": False
        },
        {
            "ParameterKey": "CarveSNSTopicArn",
            "ParameterValue": os.environ['CarveSNSTopicArn'],
            "UsePreviousValue": False
        },
        {
            "ParameterKey": "OrganizationsId",
            "ParameterValue": os.environ['OrganizationsId'],
            "UsePreviousValue": False
        },
        {
            "ParameterKey": "CarveVersion",
            "ParameterValue": os.environ['CarveVersion'],
            "UsePreviousValue": False
        },
        {
            "ParameterKey": "ResourcePrefix",
            "ParameterValue": os.environ['ResourcePrefix'],
            "UsePreviousValue": False
        }
    ]

    changeset_name = f"{payload['StackName']}-{int(time.time())}"

    response = aws_create_changeset(
        stackname=payload['StackName'],
        changeset_name=changeset_name,
        region=region,
        template_url=template_url,
        parameters=parameters,
        credentials=credentials,
        tags=aws_get_carve_tags(context.invoked_function_arn))

    print(response)

    # create payload for next step in state machine
    result = deepcopy(payload)
    result['ChangeSetName'] = changeset_name
    del result['StackStatus']
    return result


def sf_DescribeStack(event):
    # payload = json.loads(event['Input']['Payload'])
    payload = event['Input']['Payload']

    stackname = f"carve-endpoint-{payload['VpcId']}"
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
    payload = event['Input']['Payload']

    graph_name = None
    for task in payload:
        if 'GraphName' in task:
            graph_name = task['GraphName']
            break

    if graph_name is None:
        print('something went wrong')
        sys.exit()


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
            cleanup['GraphName'] = graph_name
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
    graph_name = payload['GraphName']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-cleanup-{region}")

    # find all carve named stacks
    startswith = f"{os.environ['ResourcePrefix']}carve-endpoint-vpc-"
    stacks = aws_find_stacks(startswith, region, credentials)

    if len(stacks) == 0:
        return []
    else:
        # load deployment network graph from S3 json file
        key=f"deploy_active/{graph_name}.json"    
        graph_data = aws_read_s3_direct(key, region)
        G = json_graph.node_link_graph(json.loads(graph_data))
        # generate a list of all carve stacks not in the graph
        delete_stacks = []
        for stack in stacks:
            vpc = stack['StackName'].split(startswith)[1]
            vpc_id = f"vpc-{vpc}"
            # if carve stack is for a vpc not in the graph, delete it
            if vpc_id not in list(G.nodes):
                # create payloads for delete iterator in state machine
                payload = deepcopy(event['Input'])
                payload['StackName'] = stack['StackName']
                payload['Region'] = region
                payload['Account'] = account
                delete_stacks.append(payload)

        return delete_stacks


def sf_CreateStack(event, context):
    stackname = event['Input']['StackName']
    region = event['Input']['Region']
    account = event['Input']['Account']
    tags = event['Input']['Tags']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-deploy-{event['Input']['VpcId']}")

    response = aws_describe_stack(
        stackname=stackname,
        region= region,
        credentials=credentials
        )

    if response is not None:
        stack = {'StackId': response['StackId']}
    else:
        # create bootstrap stack so a changeset can be created for SAM deploy
        template_url = f"https://s3.amazonaws.com/{os.environ['CarveS3Bucket']}/deploy_templates/carve-bootstrap.cfn.yml"
        stack = aws_create_stack(
            stackname=stackname,
            region=region,
            template_url=template_url,
            parameters=event['Input']['Parameters'],
            credentials=credentials,
            tags=tags
            )

    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['StackName'] = stackname

    return payload




def sf_CreateCarveStack(event, context):
    ''' deploy a carve endpoint/api '''

    # check if stack already exists
    stackname = f"{os.environ['ResourcePrefix']}carve-endpoint-{event['Input']['VpcId']}"
    print(f"Deploy {stackname} to {event['Input']['Account']} in {event['Input']['Region']}")

    account = event['Input']['Account']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-deploy-{event['Input']['VpcId']}")

    tags = aws_get_carve_tags(context.invoked_function_arn)

    response = aws_describe_stack(
        stackname=stackname,
        region=event['Input']['Region'],
        credentials=credentials
        )

    if response is not None:
        stack = {'StackId': response['StackId']}
    else:
        # create bootstrap stack so a changeset can be created for SAM deploy
        template_url = f"https://s3.amazonaws.com/{os.environ['CarveS3Bucket']}/deploy_templates/carve-vpc-endpoint-bootstrap.cfn.yml"
        parameters = [
            {
                "ParameterKey": "OrganizationsId",
                "ParameterValue": os.environ['OrganizationsId']
            }
        ]
        print(template_url)
        stack = aws_create_stack(
            stackname=stackname,
            region=event['Input']['Region'],
            template_url=template_url,
            parameters=parameters,
            credentials=credentials,
            tags=tags
            )

    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['StackName'] = stackname

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
        response = sf_CreateChangeSet(event, context)

    elif event['DeployAction'] == 'ExecuteChangeSet':
        response = sf_ExecuteChangeSet(event)

    elif event['DeployAction'] == 'DeleteStack':
        response = sf_DeleteStack(event)

    elif event['DeployAction'] == 'CleanupDeployments':
        response = sf_CleanupDeployments(event, context)

    elif event['DeployAction'] == 'OrganizeDeletions':
        response = sf_OrganizeDeletions(event, context)

    elif event['DeployAction'] == 'DiscoverCarveStacks':
        # response = sf_DiscoverCarveStacks(event, context)
        response = None

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
    # pass
    aws_delete_bucket_notification()
    aws_purge_s3_bucket()
    return True

