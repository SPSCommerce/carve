# import networkx as nx
# from networkx.readwrite import json_graph
# import pylab as plt
import json
# import sys
import os
from c_aws import *
# import urllib3
# import concurrent.futures




def sf_SaveToken(event, context):
    # payload must include the following plus Parameters
    token = event['TaskToken']
    parameter = event['Input']['Parameter']
    aws_ssm_put_parameter(parameter=parameter, value=token, param_type='SecureString')
    return True


def sf_ProcessReturns(event, context):
    # next_action = event['Input']['NextAction']
    print('sf_ProcessReturns')
    # aws_invoke_lambda(arn, payload, region, credentials)
    return True


def token_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    print(event)

    if event['Payload']['Tokens'] == 'SaveTokens':
        response = sf_SaveToken(payload)

    if event['Payload']['Tokens'] == 'SaveTokens':
        response = sf_SaveToken(payload)

    # return json to step function
    return json.dumps(response, default=str)




