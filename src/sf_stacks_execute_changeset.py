import json
from copy import deepcopy

from aws import aws_assume_role, aws_execute_change_set
from carve import carve_role_arn


def lambda_handler(event, context):
    '''
    Executes a cloudformation stack changeset in any account/region and passes the payload thru

    Expects the following event:
        event['Input'] = {
            "StackName": stackname,
            "Parameters": [cfn parameters],
            "Account": account,
            "Region": region,
            "Template": s3://bucket/template,
            "ChangeSetId": changeset_id
        }
    '''  
    if 'Payload' in event['Input']:
        payload = event['Input']['Payload']
    else:
        payload = event['Input']

    account = payload['Account']
    region = payload['Region']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-changeset-{region}")

    aws_execute_change_set(
        changesetname=payload['ChangeSetName'],
        stackname=payload['StackName'],
        region=region,
        credentials=credentials)

    # create payload for next step in state machine
    response = deepcopy(payload)
    if 'Status' in response:
        del response['Status']

    # return json to step function
    return json.dumps(response, default=str)


