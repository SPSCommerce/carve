import cfnresponse
import json
import boto3

def lambda_handler(event, context):
    print('REQUEST RECEIVED:\n' + json.dumps(event))
    responseData = {}
    if event['RequestType'] == 'Create':
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        return
    if event['RequestType'] == 'Delete':
        try:
            client = boto3.resource('lambda')
            for prop in event['ResourceProperties']:
                if prop.startswith('Function'):
                    func_arn = event['ResourceProperties'][prop]
                    print(f"Deleting {func_arn}")
                    client.delete_function(FunctionName=event['ResourceProperties'][prop])
        except Exception as e:
            responseData = {'error': str(e)}
            cfnresponse.send(event, context, cfnresponse.FAILED, responseData)
            return
        cfnresponse.send(event, context, cfnresponse.SUCCESS, responseData)