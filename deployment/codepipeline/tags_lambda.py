import boto3
from pprint import pprint


def lambda_handler(event, context):
    print(f"getting tags for {event['StackId']}")
    cfn = boto3.client('cloudformation', region_name='us-east-1')
    stack = cfn.describe_stacks(StackName=event['StackId'])
    for tag in stack['Stacks'][0]['Tags']:
        print(tag)


if __name__ == "__main__":
    event = {'StackId': "arn:aws:cloudformation:us-east-1:365849160317:stack/carve-pipeline/6ad74930-8440-11ec-bc77-1249929fad47"}
    lambda_handler(event, None)