import json
from copy import deepcopy

from aws import aws_assume_role, aws_describe_change_set
from carve import carve_role_arn


def lambda_handler(event, status):
    '''
    Describes a cloudformation stack changeset in any account/region and return the response

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


    # the payload structure changes if this is called after a task state vs a choice state
    if 'Payload' in event['Input']:
        payload = event['Input']['Payload']
    else:
        payload = event['Input']

    account = payload['Account']
    region = payload['Region']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-changeset-{region}")

    response = aws_describe_change_set(
        changesetname=payload['ChangeSetId'],
        region=region,
        credentials=credentials
        )

    # create payload for next step in state machine
    result = deepcopy(payload)
    if 'StatusReason' in response.keys():
        if response['StatusReason'] == "No updates are to be performed.":
            # CFN Transform will sometimes leave a failed change set for no changes
            result[status] = "NO_CHANGES"
            result['StatusReason'] = response['StatusReason']
        elif "didn't contain changes" in response['StatusReason']: 
            result[status] = "NO_CHANGES"
            result['StatusReason'] = response['StatusReason']
        else:
            result[status] = response[status]
            result['StatusReason'] = response['StatusReason']
    else:
        result[status] = response[status]

    # return json to step function
    return json.dumps(result, default=str)


