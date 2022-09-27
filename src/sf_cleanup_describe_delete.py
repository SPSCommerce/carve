from utils import carve_role_arn
from aws import aws_assume_role, aws_describe_stack


def lambda_handler(event, context):
    '''
    Describe a CFN stack in an account/region and return the status
    '''
    # payload comes in differently from the step function if it's a choice state
    print(event)
    try:
        payload = event['Input']['Payload']
    except:
        payload = event['Input']

    account = payload['Account']
    credentials = aws_assume_role(carve_role_arn(account), f"carve-deploy-{payload['Region']}")
    response = aws_describe_stack(
        stackname=payload['StackId'], # deleted stacks require the stack id in order to be described
        region=payload['Region'],
        credentials=credentials
        )

    payload['StackStatus'] = response['StackStatus']

    return payload



