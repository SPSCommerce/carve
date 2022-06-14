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


    if 'update-beacons' in event:
        from carve import update_carve_beacons
        response = update_carve_beacons()
        return response

    elif 'detail-type' in event:

        if event['source'] == 'aws.events':
            cw_rule = event['resources'][0].split('rule/')[-1]
            print(f'TRIGGERED by CW rule: {cw_rule}')
            if cw_rule == 'carve-results':
                from carve import carve_results
                carve_results()


    elif 'Records' in event:

        if 'Sns' in event['Records'][0]:
            print(f"TRIGGERED by SNS: {event['Records'][0]['EventSubscriptionArn']}")
            message = json.loads(event['Records'][0]['Sns']['Message'])
            if 'source' in message:
                if message['source'] == 'aws.autoscaling':
                    from carve import asg_event
                    asg_event(event)

        # elif 's3' in event['Records'][0]:
        #     if event['Records'][0]['s3']['bucket']['name'] == os.environ['CarveS3Bucket']:
        #         from deploy_beacons import start_carve_deployment
        #         start_carve_deployment(event, context)

    elif 'DiscoverRouting' in event:
        from disco import discover_routing
        return discover_routing()


    elif 'Payload' in event:
        if 'CleanupAction' in event['Payload']:
            from cleanup import cleanup_steps_entrypoint
            print('TRIGGERED by Cleanup Step Function')
            return cleanup_steps_entrypoint(event, context)

    elif 'CodePipeline.job' in event:
        # from deploy_beacons import codepipline_job
        print('TRIGGERED by CodePipeline')
        # codepipline_job(event, context)

    else:
        print(f'unrecognized event: {event}')



def send_api_response(response):
    
    return {"statusCode": 200, "body": json.dumps(response, default=str)}


