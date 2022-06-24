import json
from copy import deepcopy

from aws import aws_assume_role, aws_describe_change_set
from utils import carve_role_arn


def lambda_handler(event, context):
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

    print(response)

    # create payload for next step in state machine
    result = deepcopy(payload)
    if 'StatusReason' in response.keys():
        # CFN Transform will sometimes leave a failed change set for no changes, which isn't a failure
        if response['StatusReason'] == "No updates are to be performed.":
            result["Status"] = "NO_CHANGES"
            result["ExecutionStatus"] = "NO_CHANGES"
            result['StatusReason'] = response['StatusReason']
        elif "didn't contain changes" in response['StatusReason']: 
            result["Status"] = "NO_CHANGES"
            result["ExecutionStatus"] = "NO_CHANGES"
            result['StatusReason'] = response['StatusReason']
        else:
            result["Status"] = response["Status"]
            result["ExecutionStatus"] = response["ExecutionStatus"]
            result['StatusReason'] = response['StatusReason']
    else:
        result["Status"] = response["Status"]
        result["ExecutionStatus"] = response["ExecutionStatus"]
        result['StatusReason'] = "None"

    # return json to step function
    return json.dumps(result, default=str)
