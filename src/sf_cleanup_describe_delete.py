import json
from carve import carve_role_arn
from aws import aws_assume_role, aws_describe_stack


def lambda_handler(event, context):
    '''
    Describe a CFN stack in an account/region and return the status
    '''
    # payload comes in differently from the step function if it's a choise state
    print(event)
    try:
        payload = event['Payload']['Input']
    except:
        payload = event['Payload']

    account = payload['Account']
    credentials = aws_assume_role(carve_role_arn(account), f"carve-deploy-{payload['Region']}")
    response = aws_describe_stack(
        stackname=payload['StackId'], # deleted stacks require the stack id to be described
        region=payload['Region'],
        credentials=credentials
        )

    payload['StackStatus'] = response['StackStatus']

    return payload



