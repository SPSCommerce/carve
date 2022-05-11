import json
import os

import lambdavars

from aws import *
from carve import load_graph, carve_role_arn, get_carve_asgs
import concurrent.futures

from pprint import pprint


def get_subnet_beacons():
    # return dict containing all subnets with their beacon ip, account, and region

    # load latest graph
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    subnet_beacons = json.loads(aws_read_s3_direct('managed_deployment/subnet-beacons.json', current_region))

    subnets = {}
    # for vpc in list(G.nodes):
    for subnet, data in G.nodes().data():
        # only get results if there is an active beacon in the subnet
        if subnet in subnet_beacons:
            subnets[subnet_beacons[subnet]] = {
                'subnet': subnet,
                'account': data['Account'],
                'region': data['Region']
                }
        else:
            # this conditon needs to be handled if there is no beacon
            pass

    return subnets


def inventory_carve_beacons():
    ''' 
        discover all beacon IP address 
        add the beacons to the carve-config cloudformation snippet
        push the snipped to regional s3 buckets to be used as a cloudformation include
    '''

    print('updating carve beacons list')
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    asgs = get_carve_asgs() # list of dicts

    subnet_beacons = {}
    all_beacons = []

    # threaded look up the IP address of all beacons in all ASGs
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for asg in asgs:
            futures.append(executor.submit(
                get_beacons_thread,
                asg=asg['name'],
                account=asg['account'],
                region=asg['region']
                ))

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            subnet_beacons.update(result)
    
    # push subnet beacons data to S3
    data = json.dumps(subnet_beacons, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, 'managed_deployment/subnet-beacons.json')

    all_beacons = []
    for subnet, beacon in subnet_beacons.items():
        all_beacons.append(beacon)

    return all_beacons


def update_beacon_list(all_beacons):
    ##
    ##
    ## THIS FEELS LIKE IT SHOULD BE STEP FUNCTION MAP TASK INSTEAD OF THREADED LAMBDA
    ##  REFACTOR
    ##

    # get a dict of beacons with subnets, accounts, and regions
    subnet_beacons = get_subnet_beacons()

    # use threading to update all beacons with new beacon lists
    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        p = os.environ['Prefix']

        for beacon, data in subnet_beacons.items():
            futures.append(executor.submit(
                aws_invoke_lambda,
                arn=f"arn:aws:lambda:{data['region']}:{data['account']}:function:{p}carve-{data['subnet']}",
                payload={
                    'action': 'update',
                    'beacon': beacon,
                    'beacons': ','.join(all_beacons)
                    },
                region=data['region'],
                credentials=None))

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())


def get_beacons_thread(asg, account, region):
    # threaded lookup of all beacon IP addresses in an ASG
    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{asg}")
    instance_ids = []
    asg_info = aws_describe_asg(asg, region, credentials)

    for asg in asg_info['AutoScalingGroups']:
        for instance in asg['Instances']:
            if instance['LifecycleState'] == "InService":
                instance_ids.append(instance['InstanceId'])

    instances = aws_describe_instances(instance_ids, region, credentials)

    beacons = {}
    for instance in instances:
        beacons[instance['SubnetId']] = instance['PrivateIpAddress']

    return beacons


def lambda_handler(event, context):
    print(event)

    print("getting beacon inventory")
    all_beacons = inventory_carve_beacons()

    if len(all_beacons) > 0:
        print(f"updating inventory with {len(all_beacons)} beacons")
        update_beacon_list(all_beacons)
    else:
        print("no beacons to update")


if __name__ == "__main__":
    event = {"Payload": {
        'asg': {
            'name': 'test-carve-beacon-asg-vpc-0cac04ffc6e165683',
            'account': '094619684579',
            'region': 'us-east-1',
            'subnets': 1
        },
        'scale': 'up'
    }}
    result = lambda_handler(event, None)
    # print(result)