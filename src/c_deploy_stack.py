import json
import os
from copy import deepcopy
from c_carve import carve_role_arn
from c_aws import *
import time


def sf_ExecuteChangeSet(event):
    if 'Payload' in event['Input']:
        payload = event['Input']['Payload']
    else:
        payload = event['Input']

    account = payload['Account']
    region = payload['Region']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-changeset-{region}")

    response = aws_execute_change_set(
        change_set_name=payload['ChangeSetName'],
        region=region,
        credentials=credentials)

    # create payload for next step in state machine
    result = deepcopy(payload)
    del result['ChangeSetStatus']

    return result


def sf_DescribeChangeSet(event, status):
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
    result[status] = response
    return result


def sf_CreateChangeSet(event, context):
    # payload = json.loads(event['Input']['Payload'])
    if 'Payload' in event['Input']:
        payload = event['Input']['Payload']
    else:
        payload = event['Input']

    account = payload['Account']
    region = payload['Region']
    parameters = payload['Parameters']

    # create bootstrap stack to orchestrate all deploys/updates thru changesets
    with open(payload['Template']) as f:
        template = (json.load(f))

    credentials = aws_assume_role(carve_role_arn(account), f"carve-changeset-{region}")

    changeset_name = f"{payload['StackName']}-{int(time.time())}"

    response = aws_create_changeset(
        stackname=payload['StackName'],
        changeset_name=changeset_name,
        region=region,
        template_url=template_url,
        parameters=parameters,
        credentials=credentials,
        tags=aws_get_carve_tags(context.invoked_function_arn))

    # create payload for next step in state machine
    result = deepcopy(payload)
    result['ChangeSetName'] = changeset_name
    del result['StackStatus']
    return result


def sf_DescribeStack(event):
    # payload = json.loads(event['Input']['Payload'])
    payload = event['Input']['Payload']
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


def sf_CreateStack(event, context):
    # payload must include the following plus Parameters
    stackname = event['Input']['StackName']
    region = event['Input']['Region']
    account = event['Input']['Account']
    # tags = event['Input']['Tags']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-deploy-{event['Input']['VpcId']}")

    response = aws_describe_stack(
        stackname=stackname,
        region= region,
        credentials=credentials
        )

    if response is not None:
        stack = {'StackId': response['StackId']}
    else:
        # create bootstrap stack to orchestrate all deploys/updates thru changesets
        with open('deployment/carve-bootstrap.cfn.json') as f:
            template = (json.load(f))

        parameters = [
            {
                "ParameterKey": "OrganizationsId",
                "ParameterValue": os.environ['OrganizationsId']
            }
        ]
        stack = aws_create_stack(
            stackname=stackname,
            region=region,
            template=template,
            parameters=parameters,
            credentials=credentials,
            tags=aws_get_carve_tags(context.invoked_function_arn)
            )

    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['StackName'] = stackname

    return payload


def deploy_stack_entrypoint(event, context):
    ''' step function entrypoint for deploying CFN stacks '''
    if event['DeployStack'] == 'DescribeStack':
        response = sf_DescribeStack(event)

    elif event['DeployStack'] == 'DescribeChangeSet':
        response = sf_DescribeChangeSet(event, "DescribeChangeSet")

    elif event['DeployStack'] == 'DescribeChangeSetExecution':
        response = sf_DescribeChangeSet(event, "DescribeChangeSetExecution")

    elif event['DeployStack'] == 'CreateStack':
        response = sf_CreateStack(event, context)

    elif event['DeployStack'] == 'CreateChangeSet':
        response = sf_CreateChangeSet(event, context)

    elif event['DeployStack'] == 'ExecuteChangeSet':
        response = sf_ExecuteChangeSet(event)

    # return json to step function
    return json.dumps(response, default=str)


