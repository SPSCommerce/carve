'''
This imports the carve lambda environment variables for local testing if not run in lambda
'''

import os

# create lambda context class
class LambdaContext:
    def __init__(self):
        self.invoked_function_arn = os.environ['AWS_LAMBDA_FUNCTION_ARN']


if 'AWS_REGION' not in os.environ:
    import boto3
    function = 'nonprod-carve-core-deploy_trigger'
    os.environ['AWS_REGION'] = "us-east-1"

    client = boto3.client('lambda', region_name=os.environ['AWS_REGION'])
    config = client.get_function_configuration(FunctionName=function)
    for k, v in config['Environment']['Variables'].items():
        os.environ[k] = v

    # create lambda context object
    os.environ['AWS_LAMBDA_FUNCTION_ARN'] = config['FunctionArn']

    global lambda_context
    lambda_context = LambdaContext()

