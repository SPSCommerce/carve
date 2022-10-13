import cfnresponse
import json
import boto3
import os

# This lambda function is a CloudFormation custom resource that's used to delete 
# the carve VPC lambda functions when the stack is deleted. CloudFormation has a 
# bug where it takes 20-40 minutes to delete the functions due to waiting to 
# hear back on ENI deletion. To work around this, the resources are set to retain 
# in the stack, and instead this lambda function deletes the functions immediately.

# CloudFormation Bug:
# https://github.com/serverless/serverless/issues/5008

def lambda_handler(event, context):
    print('REQUEST RECEIVED:\n' + json.dumps(event))
    responseData = {}
    if event['RequestType'] == 'Create':
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        return
    if event['RequestType'] == 'Delete':
        try:
            # from 1 thru FunctionCount
            print('Deleting Lambda Functions')
            for i in range(1, int(os.environ['FunctionCount'])+1):
                # delete each carve VPC function
                subnet_function = os.environ[f'Function{i}']
                print(f'Deleting lambda function: {subnet_function}')
                client = boto3.client('lambda')
                client.delete_function(FunctionName=subnet_function)
        except Exception as e:
            print(e)
            responseData = {'error': str(e)}
            cfnresponse.send(event, context, cfnresponse.FAILED, responseData)
            return
        cfnresponse.send(event, context, cfnresponse.SUCCESS, responseData)
