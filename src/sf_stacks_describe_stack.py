import json
from copy import deepcopy

from aws import aws_assume_role, aws_describe_stack
from utils import carve_role_arn


def lambda_handler(event, context):
    '''
    Describes a cloudformation stack in any account/region and return the response

    Expects the following event:
        event['Input'] = {
            "StackName": stackname,
            "Parameters": [cfn parameters],
            "Account": account,
            "Region": region,
            "Template": s3://bucket/template
        }

    '''

    # the payload structure changes if this is called after a task state vs a choice state
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
    if 'StackStatusReason' in response:
        payload['StackStatusReason'] = response['StackStatusReason']

    # return json to step function
    return json.dumps(payload, default=str)


