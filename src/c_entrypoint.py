import json
import os
from c_deploy_endpoints import deploy_steps_entrypoint, start_carve_deployment, get_deploy_key
from c_deploy_stack import deploy_stack_entrypoint
from c_cleanup import cleanup_steps_entrypoint
from c_disco import disco_entrypoint
from c_aws import aws_put_bucket_notification, aws_codepipeline_success
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
    if 'CodePipeline.job' not in event:
        print(event)

    # c_context = setup_context(context)

    # Triggered by cloudwatch cron/scheduled job
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

        elif 'eventSource' in event['Records'][0]:
            if event['Records'][0]['eventSource'] == "aws:s3":
                if event['Records'][0]['s3']['bucket']['name'] == os.environ['CarveS3Bucket']:
                    start_carve_deployment(event, context)

    elif 'queryStringParameters' in event:
        print(f'TRIGGERED by API Gateway: {event["requestContext"]["apiId"]}')
        send_api_response(event)

    elif 'DeployStart' in event:
        print('Starting deployment process')
        return start_carve_deployment(event, context)

    elif 'DeployAction' in event:
        print('TRIGGERED by Endpoint Deployment Step Function')
        return deploy_steps_entrypoint(event, context)

    elif 'DeployStack' in event:
        print('TRIGGERED by Deploy Stack Step Function')
        return deploy_stack_entrypoint(event, context)

    elif 'VerifyAction' in event:
        print('TRIGGERED by Route Verification Step Function')
        # return verify_steps_entrypoint(event)
    
    elif 'DiscoveryAction' in event:
        print('TRIGGERED by Discovery Step Function')
        return disco_entrypoint(event, context)

    # elif 'ResourceProperties' in event:
    #     return custom_resource_entrypoint(event, context)

    elif 'Payload' in event:
        if 'CleanupAction' in event['Payload']:
            print('TRIGGERED by Cleanup Step Function')
            return cleanup_steps_entrypoint(event, context)

    elif 'CodePipeline.job' in event:
        print('TRIGGERED by CodePipeline')
        param = event['CodePipeline.job']['data']['actionConfiguration']['configuration']['UserParameters']

        if param == 'UpdateEndpoints':
            if os.environ['PropogateUpdates'] == 'True':
                start_carve_deployment(event, context, key=get_deploy_key(last=True))
            else:
                print('Updating endpoints is disabled')
 
        elif param == 'BucketNotification':
            aws_put_bucket_notification('deploy_input/', context.invoked_function_arn)
            aws_codepipeline_success(event['CodePipeline.job']['id'])

    else:
        print(f'unrecognized event: {event}')



def send_api_response(response):
    
    return {"statusCode": 200, "body": json.dumps(response, default=str)}


