import json
from copy import deepcopy

from aws import (aws_assume_role, aws_create_stack, aws_describe_stack,
                 aws_get_carve_tags)
from carve import carve_role_arn


def lambda_handler(event, context):
    '''
    Create a new CFN stack if one does not exist

    Expects the following event:
        event['Input'] = {
            "StackName": stackname,
            "Parameters": [cfn parameters],
            "Account": account,
            "Region": region,
            "Template": s3://bucket/template
        }
    '''
    stackname = event['Input']['StackName']
    region = event['Input']['Region']
    account = event['Input']['Account']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-create-{stackname}")

    response = aws_describe_stack(
        stackname=stackname,
        region=region,
        credentials=credentials
        )

    if response is None:
        # create an empty bootstrap stack for changesets
        with open('managed_deployment/bootstrap-stack.cfn.json') as f:
            template = (json.load(f))

        aws_create_stack(
            stackname=stackname,
            region=region,
            template=str(template),
            parameters=[],
            credentials=credentials,
            tags=aws_get_carve_tags(context.invoked_function_arn)
            )

    # create payload for next step in state machine
    payload = deepcopy(event['Input'])
    payload['StackName'] = stackname

    # return json to step function
    return json.dumps(payload, default=str)


