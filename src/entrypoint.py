import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    '''
    entrypoint for invoke events
    '''


    if 'detail-type' in event:

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

    else:
        print(f'unrecognized event: {event}')



def send_api_response(response):
    
    return {"statusCode": 200, "body": json.dumps(response, default=str)}


