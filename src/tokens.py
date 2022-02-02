import json
import os
from aws import aws_ssm_put_parameter, aws_ssm_get_parameter
from carve import update_carve_beacons

def sf_SaveToken(event, context):
    # payload must include the following plus Parameters
    token = event['TaskToken']
    parameter = event['Input']['parameter']
    aws_ssm_put_parameter(parameter=parameter, value=token, param_type='SecureString')


def sf_ProcessReturns(event, context):
    # next_action = event['Input']['NextAction']
    print(f'processing returns: {event}')
    action = event['Input'][0]['action']

    if action == 'scale':
        if event['Input'][0]['result'] == "success":
            scale = aws_ssm_get_parameter(f"/{os.environ['Prefix']}carve-resources/scale")
            if scale.lower() != 'none':
                update_carve_beacons()

    return True


def token_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    if event['Tokens'] == 'SaveTokens':
        response = sf_SaveToken(event, context)

    if event['Tokens'] == 'ProcessReturns':
        response = sf_ProcessReturns(event, context)

    # return json to step function
    return json.dumps(response, default=str)




