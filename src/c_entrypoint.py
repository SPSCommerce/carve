import json
import os
from c_deploy import deploy_steps_entrypoint, deploy_carve_endpoints, custom_resource_entrypoint
from c_disco import discovery
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    '''
    entrypoint for invoke events:
        - step function executing route test
        - diff 2 json graphs (s3 or payload)
        - discovery process
        - endpoint deployment
        - cloudformation custom resources

    # lambda needs to log its info at startup

    '''
    # print(event)

    # c_context = setup_context(context)

    # Triggered by cloudwatch cron/scheduled job = crawler run
    if 'detail-type' in event:
        if event.get('detail-type') == 'Scheduled Event':
            cw_arn = event['resources'][0]
            print(f'TRIGGERED by CW: {cw_arn}')
            return cw_arn
        
    elif 'Records' in event:

        if 'EventSource' in event['Records'][0]:
            if event['Records'][0]['EventSource'] == "aws:sns":
                sns_arn = event['Records'][0]['EventSubscriptionArn']
                print(f'TRIGGERED by SNS: {sns_arn}')
                return sns_arn

        elif 'eventSource' in event['Records']:
            if event['Records'][0]['EventSource'] == "aws:s3":
                if event['Records'][0]['s3']['bucket']['name'] == os.environ['CarveS3Bucket']:
                    deploy_carve_endpoints(event, context)

    elif 'queryStringParameters' in event:
        print(f'TRIGGERED by API Gateway: {event["requestContext"]["apiId"]}')
        send_api_response(event)

    elif 'DeployStart' in event:
        print('Starting deployment process')
        return deploy_carve_endpoints(event, context)

    elif 'DeployAction' in event:
        print('TRIGGERED by Deployment Step Function')
        return deploy_steps_entrypoint(event, context)

    elif 'Discovery' in event:
        print('Starting deployment process')
        return discovery(event, context)

    elif 'VerifyAction' in event:
        print('TRIGGERED by Route Verification Step Function')
        # return verify_steps_entrypoint(event)
    
    elif 'ResourceProperties' in event:
        return custom_resource_entrypoint(event, context)

    else:
        print(f'unrecognized event: {event}')



def send_api_response(response):
    
    return {"statusCode": 200, "body": json.dumps(response, default=str)}


