import json
import os
from c_deploy_endpoints import deploy_steps_entrypoint, start_carve_deployment, codepipline_job
from c_deploy_stack import deploy_stack_entrypoint
from c_cleanup import cleanup_steps_entrypoint
from c_disco import disco_entrypoint
from c_aws import aws_put_bucket_notification, aws_codepipeline_success
from c_carve import asg_event, carve_results
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

    if 'detail-type' in event:

        if event['source'] == 'aws.events':
            cw_arn = event['resources'][0]
            print(f'TRIGGERED by CW: {cw_arn}')
            carve_results(event, context)

    elif 'Records' in event:

        if 'Sns' in event['Records'][0]:
            print(f"TRIGGERED by SNS: {event['Records'][0]['EventSubscriptionArn']}")
            message = json.loads(event['Records'][0]['Sns']['Message'])
            # print(message)
            if 'source' in message:
                if message['source'] == 'aws.autoscaling':
                    asg_event(message)

        elif 's3' in event['Records'][0]:
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
    #     # this is from CFN custom resource
    #     return custom_resource_entrypoint(event, context)

    elif 'Payload' in event:
        if 'CleanupAction' in event['Payload']:
            print('TRIGGERED by Cleanup Step Function')
            return cleanup_steps_entrypoint(event, context)

    elif 'CodePipeline.job' in event:
        print('TRIGGERED by CodePipeline')
        codepipline_job(event, context)

    else:
        print(f'unrecognized event: {event}')



def send_api_response(response):
    
    return {"statusCode": 200, "body": json.dumps(response, default=str)}


