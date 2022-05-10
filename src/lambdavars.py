'''
This imports the carve lambda environment variables for local testing if not run in lambda
'''

import os

if 'AWS_REGION' not in os.environ:
    import boto3
    function = 'test-carve-core-entrypoint'
    os.environ['AWS_REGION'] = "us-east-1"

    client = boto3.client('lambda', region_name=os.environ['AWS_REGION'])
    config = client.get_function_configuration(FunctionName=function)
    for k, v in config['Environment']['Variables'].items():
        os.environ[k] = v
