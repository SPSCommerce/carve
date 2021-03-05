import json
import os
from c_deploy import deploy_steps_entrypoint, deploy_carve_endpoints, custom_resource_entrypoint
from c_disco import discovery
import logging

import logging
logger = logging.logging.getLogger()
logger.setLevel(logging.INFO)

def setup_context(context):
    '''
        create c_context dictionary to pass around where needed

    '''
    c_context = {}
    # c_context['VpcEndpointId'] = os.environ['VpcEndpointId']
    # c_context['VpcId'] = os.environ['VpcId']

    # local test vars
    # c_context['role'] = "arn:aws:sts::*:role/carve"
    # c_context['region_list'] = "us-east-1,us-west-2,ap-southeast-2,ca-central-1"
    c_context['region_list'] = 'all'
    # c_context['json_graph'] = '/src/c_disco_graph.json'
    # c_context['diff_graph'] = '/src/c_disco_graph_wrong.json'
    c_context['peers_only'] = 'true'
    c_context['VpcId'] = 'vpc-id'
    c_context['export_visual'] = 'false'
    c_context['invoked_function_arn'] = context.invoked_function_arn
    # boto client config number of retries

    return c_context


def lambda_handler(event, context):
    '''
    entrypoint for SNS events:
        - execute route test against a given payload
        - execute route test against s3 json_graph
        - diff 2 json graphs (s3 or payload)
    entrypoint for manual invoke:
        - discovery process

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
        sns_arn = event['Records'][0]['EventSubscriptionArn']
        print(f'TRIGGERED by SNS: {sns_arn}')
        return cw_arn

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



    # # queryStringParameters
    # param1 = event["queryStringParameters"]["param1"]
    # param2 = event["queryStringParameters"]["param2"]
    



def send_api_response(response):
    
    return {"statusCode": 200, "body": json.dumps(response, default=str)}



def deploy_test():
    from c_deploy import deploy_org_endpoints, parse_args
    from c_carve import load_graph
    import sys
    me = sys.argv[0]
    sys.argv = [me, '-r', "arn:aws:iam::*:role/carve", '-g', "/src/data/c_disco_graph-last.json"]
    os.environ['StepFunctionDeploy'] = 'StepFunctionDeployARN'

    deploy_args = parse_args()
    
    G = load_graph(deploy_args.graph)
    # print(G)
    deploy_org_endpoints(G, deploy_args.role)


    # # test = 'sns'
    # # test = 'cw'
    # test = 'api'

    # with open(f'/src/events/{test}_event.json') as f:
    #     event = json.load(f)

    # hander(context={}, event=event)

