import os

from numpy import insert

import lambdavars

from aws import *

import json
from carve import load_graph, carve_role_arn, beacon_results
import concurrent.futures
import time


def lambda_handler(event, context):
    print(f"event: {event}")

    account = event['asg']['account']
    name = event['asg']['name']
    region = event['asg']['region']

    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{name}")
    response = aws_describe_asg(name, region, credentials)

    instances = response['AutoScalingGroups'][0]['Instances']
    scale_status = "SCALE_IN_PROGRESS"

    if event['scale'] == 'down':
        if len(instances) == 0:
            scale_status = "SCALE_SUCCEEDED"
    else:
        in_service = 0
        for instance in instances:
            if instance['LifecycleState'] == 'InService':
                in_service += 1       
        if in_service == len(instances):
            scale_status = "SCALE_SUCCEEDED"
    # SHOULD ALSO CATCH FAILURE HERE TO RETURN: SCALE_FAILED

    event['ScaleStatus'] = scale_status

    return event


if __name__ == "__main__":
    event = {
        'asg': {
            'name': 'test-carve-beacon-asg-vpc-0cac04ffc6e165683',
            'account': '094619684579',
            'region': 'us-east-1',
            'subnets': 1
        },
        'scale': 'down'
    }
    result = lambda_handler(event, None)
    print(result)