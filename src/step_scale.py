import networkx as nx
from networkx.readwrite import json_graph
import pylab as plt
import json
import sys
import os
from aws import *
import urllib3
import concurrent.futures
import time


# STEPS
# 1. get all VPC ASGs, feed list to iteration
# 2. check current scale of ASG
#   3. if scale is not correct, update ASG
#   4. if scale is correct, return success
# 5. after updating ASG, wait for ASG to scale
# 6. return success


# def get_asgs(G=None):
#     if G is None:
#         G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

#     # determine all deployed ASGs
#     asgs = {}
#     for subnet in list(G.nodes):
#         asg = f"{os.environ['Prefix']}carve-beacon-asg-{G.nodes().data()[subnet]['VpcId']}"
#         if asg not in asgs:
#             asgs[asg] = {
#                 'account': G.nodes().data()[subnet]['Account'],
#                 'region': G.nodes().data()[subnet]['Region'],
#                 }

#     for asg, values in asgs.items():


#     return asgs


def scale_beacons(scale):
    ''' 
        discover all beacon IP address 
        add the beacons to the carve-config cloudformation snippet
        push the snipped to regional s3 buckets to be used as a cloudformation include
    '''

    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    vpcs = {}
    payload = []
    for subnet in list(G.nodes):
        # determine VPCs and regions
        a = G.nodes().data()[subnet]['Account']
        r = G.nodes().data()[subnet]['Region']
        vpcs[G.nodes().data()[subnet]['VpcId']] = (a, r)
        # add an ssm path to store tokens for each subnet
        payload.append({
            'parameter': f"/{os.environ['Prefix']}carve-resources/tokens/{subnet}",
            'task': 'scale',
            'scale': scale
            })

    # start a step function to generate tokens to track scaling each subnet
    name = f"scale-{scale}-{int(time.time())}"
    print('starting token step function')
    aws_start_stepfunction(os.environ['TokenStateMachine'], payload, name)

    # generate a list of autoscaling groups to scale
    asgs = []
    for vpc, ar in vpcs.items():
        vpc_subnets = [x for x,y in G.nodes(data=True) if y['VpcId'] == vpc]
        asgs.append({
            'asg': f"{os.environ['Prefix']}carve-beacon-asg-{vpc}",
            'account': ar[0],
            'region': ar[1],
            'subnets': vpc_subnets
            })

    # wait for tokens to appear before scaling
    i = 0
    while True:
        tokens = aws_ssm_get_parameters(f"/{os.environ['Prefix']}carve-resources/tokens/")
        if len(payload) == len(tokens):
            print('tokens are ready')
            break
        else:
            if i > 30:
                print('timed out waiting for tokens')
            else:
                i = i + 1
                print('waiting 1s for tokens...')
                time.sleep(1)

    print(f'scaling asgs: {asgs}')
    # using threading, set all ASGs to correct scale for all beacons
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for asg in asgs:

            if scale == 'none':
                desired = 0
            elif scale == 'subnet':
                desired = len(asg['subnets'])
            elif scale == 'vpc':
                desired = 1

            futures.append(executor.submit(
                update_asg_size,
                account=asg['account'],
                asg=asg['asg'],
                minsize=0, 
                maxsize=len(asg['subnets']),
                desired=desired,
                region=asg['region']
                ))
            
        for future in concurrent.futures.as_completed(futures):
            result = future.result()


def update_asg_size(account, asg, minsize, maxsize,  desired, region):
    credentials=aws_assume_role(carve_role_arn(account), f"lookup-{asg}")
    asg_info = aws_describe_asg(asg, region, credentials)
    print(f'scaling asg: {asg}')

    # only update ASG if min/max/desired is different
    update = False
    if int(asg_info['MinSize']) != int(minsize):
        print('scale due to MinSize')
        update = True
    elif int(asg_info['MaxSize']) != int(maxsize):
        print('scale due to MaxSize')
        update = True
    elif int(asg_info['DesiredCapacity']) != int(desired):
        print('scale due to DesiredCapacity')
        update = True
    else:
        print('no scaling update to ASG')
    

    if update:
        aws_update_asg_size(asg, minsize, maxsize, desired, region, credentials)
    else:
        # if no udpates, return success for the task tokens
        subnets = asg_info['VPCZoneIdentifier'].split(',')
        print(f'clearing tokens for subnets: {subnets}')
        for subnet in subnets:
            ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{subnet}"
            token = aws_ssm_get_parameter(ssm_param)
            aws_ssm_delete_parameter(ssm_param)
            if token is not None:
                aws_send_task_success(token, {"action": "scale", "result": "none"})
            else:
                print(f'taskToken was None for {subnet}')


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


def update_carve_beacons():
    ''' 
        discover all beacon IP address 
        add the beacons to the carve-config cloudformation snippet
        push the snipped to regional s3 buckets to be used as a cloudformation include
    '''

    print('updating carve beacons')
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    # determine all deployed ASGs
    asgs = {}
    for subnet in list(G.nodes):
        asg = f"{os.environ['Prefix']}carve-beacon-asg-{G.nodes().data()[subnet]['VpcId']}"
        if asg not in asgs:
            asgs[asg] = {
                'account': G.nodes().data()[subnet]['Account'],
                'region': G.nodes().data()[subnet]['Region']
                }

    # threaded look up the IP address of all beacons in all ASGs
    subnet_beacons = {}
    all_beacons = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for asg, value in asgs.items():
            futures.append(executor.submit(
                get_beacons_thread, asg=asg, account=value['account'], region=value['region']))

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            subnet_beacons.update(result)
            for subnet, beacon in result.items():
                all_beacons.append(beacon)

    # push subnet beacons data to S3
    data = json.dumps(subnet_beacons, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, 'managed_deployment/subnet-beacons.json')

    # # create an updated config file with all the beacons
    # config_path = "managed_deployment/carve-config.json"

    # with open(config_path) as f:
    #     config = json.load(f)

    # config['/root/carve.cfg']['content'] = '\n'.join(beacons)

    # # push carve config file to S3
    # data = json.dumps(config, ensure_ascii=True, indent=2, sort_keys=True)
    # aws_put_direct(data, config_path)

    # get a list of subnets, accounts, regions, and beacons
    subnets = get_subnet_beacons()

    # use threading to update all beacons with new beacon lists
    results = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        p = os.environ['Prefix']

        for beacon, data in subnets.items():

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

    print(results)

    # # copy config file to all required regions for CloudFormation includes
    # prefix = os.environ['Prefix']
    # org = os.environ['OrgId']
    # for r in regions:
    #     aws_copy_s3_object(
    #         key=config_path,
    #         target_key=config_path,
    #         source_bucket=os.environ['CarveS3Bucket'],
    #         target_bucket=f"{prefix}carve-managed-bucket-{org}-{r}")

    # # update all VPC stacks
    # deploy_key = get_deploy_key(last=True)

    # if deploy_key is not None:
    #     start_carve_deployment(event, context, key=deploy_key)
    # else:
    #     print('No previous deploy key to run updates with')


def get_beacons_thread(asg, account, region):
    # threaded lookup of all beacon IP addresses in an ASG
    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{asg}")
    instance_ids = []
    asg_info = aws_describe_asg(asg, region, credentials)
    for instance in asg_info['Instances']:
        if instance['LifecycleState'] == "InService":
            instance_ids.append(instance['InstanceId'])

    instances = aws_describe_instances(instance_ids, region, credentials)

    beacons = {}
    for instance in instances:
        beacons[instance['SubnetId']] = instance['PrivateIpAddress']

    return beacons



def asg_event(event):

    # should only be one item, but treat as a list
    for record in event['Records']:
        message = json.loads(record['Sns']['Message'])

        print(f"TRIGGERED by ASG: {message['detail']['AutoScalingGroupName']}")

        # get insances from event data
        instance_id = ""
        for resource in message['resources']:
            if resource.startswith("arn:aws:ec2"):
                instance_id = resource.split('/')[1]

        vpc = message['detail']['AutoScalingGroupName'].split(f"{os.environ['Prefix']}carve-beacon-asg-")[-1]
        credentials = aws_assume_role(carve_role_arn(message['account']), f"event-{message['detail']['AutoScalingGroupName']}")

        # get instance metadata from account and update SSM
        ec2 = aws_describe_instances([instance_id], message['region'], credentials)[0]
        # print(ec2)

        # parameter = f"/{os.environ['Prefix']}carve-resources/vpc-beacons/{vpc}/{ec2['InstanceId']}"

        if 'EC2 Instance Launch Successful' == message['detail-type']:

            # # add to SSM
            # print(f"adding beacon to ssm: {instance_id} - {ec2['PrivateIpAddress']} - {ec2['SubnetId']}")
            # beacon = {ec2['PrivateIpAddress']: ec2['SubnetId']}
            # aws_ssm_put_parameter(parameter, json.dumps(beacon))


            ### need to update this code to grab subnet ssm param instead of ASG

            # append azid code to end of instance name
            subnet = aws_describe_subnets(message['region'], credentials, message['account'], ec2['SubnetId'])[0]
            az = subnet['AvailabilityZoneId'].split('-')[-1]
            name = f"{os.environ['Prefix']}carve-beacon-{ec2['SubnetId']}-{az}"
            tags = [{'Key': 'Name', 'Value': name}]
            aws_create_ec2_tag(ec2['InstanceId'], tags, message['region'], credentials)

            function = f"arn:aws:lambda:{message['region']}:{message['account']}:function:{os.environ['Prefix']}carve-{ec2['SubnetId']}"
            beacon = ec2['PrivateIpAddress']

            ## will need to udate SSM logic for tokens to be 1 token per subnet that will come back up?
            ## or do we check the whole ASG for health?

            i = 0
            while True:
                result = beacon_results(function, beacon)
                print(result)
                if result['health'] == 'up':
                    # ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{asg}",
                    ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{ec2['SubnetId']}"
                    token = aws_ssm_get_parameter(ssm_param)
                    aws_ssm_delete_parameter(ssm_param)
                    if token is not None:
                        aws_send_task_success(token, {"action": "scale", "result": "success"})
                    else:
                        print(f"taskToken was None for {ec2['SubnetId']}")
                    break
                else:
                    if i > 30:
                        break
                        print(f'timed out waiting for beacon {beacon}')
                    else:
                        print(f'waiting for beacon {beacon} - {i}')
                        i = i + 1
                        time.sleep(1)

        elif 'EC2 Instance Terminate Successful' == message['detail-type']:
            # ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{asg}",
            subnet = message['detail']['Details']['Subnet ID']
            ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{subnet}"
            token = aws_ssm_get_parameter(ssm_param)
            aws_ssm_delete_parameter(ssm_param)
            if token is not None:
                aws_send_task_success(token, {"action": "scale", "result": "success"})
            else:
                print(f'taskToken was None for {subnet}')
            print(f"beacon terminated {message}")


