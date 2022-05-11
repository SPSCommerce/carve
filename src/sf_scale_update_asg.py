import os

import lambdavars

from aws import *

import json
from carve import carve_role_arn
import concurrent.futures
import time



def update_asg_size(asg, desired, account, region):
    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{asg}")
    aws_update_asg_size(asg, desired, region, credentials)


def lambda_handler(event, context):
    print(f"event: {event}")

    if event['scale'] == 'down':
        desired = 0
    else:
        desired = event['asg']['subnets']

    update_asg_size(
        asg = event['asg']['name'],
        desired = desired,
        account = event['asg']['account'],
        region = event['asg']['region']
        )

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