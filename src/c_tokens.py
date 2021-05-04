import json
import os
from c_aws import aws_ssm_put_parameter


def sf_SaveToken(event, context):
    # payload must include the following plus Parameters
    token = event['TaskToken']
    parameter = event['Input']['parameter']
    aws_ssm_put_parameter(parameter=parameter, value=token, param_type='SecureString')


def sf_ProcessReturns(event, context):
    # next_action = event['Input']['NextAction']
    print(f'put code here to process returns: {event}')
    # aws_invoke_lambda(arn, payload, region, credentials)
    return True


def token_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    if event['Tokens'] == 'SaveTokens':
        response = sf_SaveToken(event, context)

    if event['Tokens'] == 'ProcessReturns':
        response = sf_ProcessReturns(event, context)

    # return json to step function
    return json.dumps(response, default=str)




