from aws import aws_invoke_lambda, current_region
import os

def lambda_handler(event, context):
    '''
    respond to cloudwatch events and execute carve verifications
    '''


    if 'detail-type' in event:

        if event['source'] == 'aws.events':
            cw_rule = event['resources'][0].split('rule/')[-1]
            if cw_rule == f"{os.environ['Prefix']}carve-results":
                result = carve_results(event, context)
                print(result)


def carve_results(event, context):
    '''
    respond to cloudwatch events and execute carve verifications
    '''
    current_account = context.invoked_function_arn.split(':')[4]
    lambda_arn = f"arn:aws:lambda:{current_region}:{current_account}:function:{os.environ['Prefix']}-carve-verify_routing"
    payload = {}
    result = aws_invoke_lambda(lambda_arn, payload)

    # return the result
    return result