import json
import os
from carve import carve_role_arn
from aws import aws_delete_stack, aws_purge_s3_bucket, aws_assume_role


def lambda_handler(event, context):
    '''
    Send delete stack command to account/region for the CFN stack in the event
    - will also empty the S3 bucket if the stack is a bucket stack
    '''
    payload = event['Payload']['Input']
    account = payload['Account']
    region = payload['Region']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-cleanup-{region}")

    # if this is a regional S3 bucket stack, empty the bucket before deleting the stack
    s3_stack = f"{os.environ['Prefix']}carve-managed-bucket-{region}"
    if payload['StackName'] == s3_stack:

        if os.environ['UniqueId'] == "":
            unique = os.environ['OrgId']
        else:
            unique = os.environ['UniqueId']

        bucket = f"{os.environ['Prefix']}carve-managed-bucket-{unique}-{region}"
        aws_purge_s3_bucket(bucket)

    aws_delete_stack(
        stackname=payload['StackName'],
        region=payload['Region'],
        credentials=credentials)

    print(f"WILL DELETE STACK: {payload['StackName']} from {account} in {region}")

    # return json to step function
    return json.dumps(payload, default=str)



