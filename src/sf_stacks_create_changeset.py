import json
import time
from copy import deepcopy

from aws import (aws_assume_role, aws_create_changeset, aws_get_carve_tags,
                 aws_read_s3_direct, current_region)
from carve import carve_role_arn


def lambda_handler(event, context):
    '''
    Creates a changeset for a cloudformation stack in any account/region

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
    region = payload['Region']
    parameters = payload['Parameters']

    template = aws_read_s3_direct(payload['Template'], current_region)

    credentials = aws_assume_role(carve_role_arn(account), f"carve-changeset-{region}")

    changeset_name = f"{payload['StackName']}-{int(time.time())}"

    response = aws_create_changeset(
        stackname=payload['StackName'],
        changeset_name=changeset_name,
        region=region,
        template=template,
        parameters=parameters,
        credentials=credentials,
        tags=aws_get_carve_tags(context.invoked_function_arn))

    # create payload for next step in state machine
    result = deepcopy(payload)
    result['ChangeSetName'] = changeset_name
    result['ChangeSetId'] = response['Id']
    del result['StackStatus']

    # return json to step function
    return json.dumps(result, default=str)


