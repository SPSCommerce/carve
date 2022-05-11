import os
from pprint import pp

import lambdavars

from aws import *
from carve import load_graph, carve_role_arn, get_carve_asgs
import concurrent.futures


def threaded_asg_lookup(name, account, region, subnets):
    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{name}")
    response = aws_describe_asg(name, region, credentials)
    arn = response['AutoScalingGroups'][0]['AutoScalingGroupARN']
    return {'arn': arn, 'subnets': subnets}


def lambda_handler(event, context):
    print(event)
    if 'scale' not in event['Input']:
        error = {'error': 'scale not specified in event'}
        print(error)
        return error
    asgs = get_carve_asgs()
    # print(f"Scaling ASGs: {asgs}")
    return {'asgs': asgs, 'scale': event['Input']['scale']}


if __name__ == "__main__":
    event = {"Input": {"scale": "up"}}
    # event = {}
    result = lambda_handler(event, None)
    print(result)