import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    '''
    entrypoint for invoke events:
        - step function executing route test
        - diff 2 json graphs (s3 or payload)
        - discovery process
        - beacon deployment
        - cloudformation custom resources

    # lambda needs to log its info at startup

    '''
    if 'CodePipeline.job' not in event:
        print(event)

    if 'update-beacons' in event:
        from c_carve import update_carve_beacons
        update_carve_beacons()

    if 'detail-type' in event:

        if event['source'] == 'aws.events':
            from c_carve import carve_results

            cw_arn = event['resources'][0]
            print(f'TRIGGERED by CW: {cw_arn}')
            carve_results(event, context)

        if event['source'] == 'aws.ssm':
            from c_carve import ssm_event

            ssm_arn = event['resources'][0]
            print(f'TRIGGERED by SSM: {cw_arn}')
            ssm_event(event, context)

    elif 'Records' in event:

        if 'Sns' in event['Records'][0]:
            print(f"TRIGGERED by SNS: {event['Records'][0]['EventSubscriptionArn']}")
            message = json.loads(event['Records'][0]['Sns']['Message'])
            # print(message)
            if 'source' in message:
                if message['source'] == 'aws.autoscaling':
                    from c_carve import asg_event
                    asg_event(message)

        elif 's3' in event['Records'][0]:
            if event['Records'][0]['s3']['bucket']['name'] == os.environ['CarveS3Bucket']:
                from c_deploy_beacons import start_carve_deployment
                start_carve_deployment(event, context)

    elif 'DeployStart' in event:
        from c_deploy_beacons import start_carve_deployment
        print('Starting deployment process')
        return start_carve_deployment(event, context)

    elif 'DeployAction' in event:
        from c_deploy_beacons import deploy_steps_entrypoint
        print('TRIGGERED by Beacons Deployment Step Function')
        return deploy_steps_entrypoint(event, context)

    elif 'DeployStack' in event:
        from c_deploy_stack import deploy_stack_entrypoint
        print('TRIGGERED by Deploy Stack Step Function')
        return deploy_stack_entrypoint(event, context)

    elif 'DiscoveryAction' in event:
        from c_disco import disco_entrypoint
        print('TRIGGERED by Discovery Step Function')
        return disco_entrypoint(event, context)

    elif 'Tokens' in event:
        from c_tokens import token_entrypoint
        print('TRIGGERED by Token Step Function')
        return token_entrypoint(event, context)


    # elif 'ResourceProperties' in event:
    #     # this is from CFN custom resource
    #     return custom_resource_entrypoint(event, context)

    elif 'Payload' in event:
        if 'CleanupAction' in event['Payload']:
            from c_cleanup import cleanup_steps_entrypoint
            print('TRIGGERED by Cleanup Step Function')
            return cleanup_steps_entrypoint(event, context)

    elif 'CodePipeline.job' in event:
        from c_deploy_beacons import codepipline_job
        print('TRIGGERED by CodePipeline')
        codepipline_job(event, context)

    else:
        print(f'unrecognized event: {event}')



def send_api_response(response):
    
    return {"statusCode": 200, "body": json.dumps(response, default=str)}


