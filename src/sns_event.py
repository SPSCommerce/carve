import json
import os
from aws import *
from utils import carve_role_arn


def asg_event(event):
    '''
    this currently just renames EC2 instances on boot to include the subnet id
    '''
    for record in event['Records']:
        message = json.loads(record['Sns']['Message'])

        print(f"TRIGGERED by ASG: {message['detail']['AutoScalingGroupName']}")

        # get insances from event data
        instance_id = ""
        for resource in message['resources']:
            if resource.startswith("arn:aws:ec2"):
                instance_id = resource.split('/')[1]

        # vpc = message['detail']['AutoScalingGroupName'].split(f"{os.environ['Prefix']}carve-beacon-asg-")[-1]
        credentials = aws_assume_role(carve_role_arn(message['account']), f"event-{message['detail']['AutoScalingGroupName']}")

        # get instance metadata from account and update SSM
        ec2 = aws_describe_instances([instance_id], message['region'], credentials)[0]

        if message['detail-type'] == 'EC2 Instance Launch Successful':

            # print(f"adding beacon to ssm: {instance_id} - {ec2['PrivateIpAddress']} - {ec2['SubnetId']}")
            # beacon = {ec2['PrivateIpAddress']: ec2['SubnetId']}

            # append azid code to end of instance name
            subnet = aws_describe_subnets(message['region'], message['account'], credentials, ec2['SubnetId'])[0]
            az = subnet['AvailabilityZoneId'].split('-')[-1]
            name = f"{os.environ['Prefix']}carve-beacon-{ec2['SubnetId']}-{az}"
            tags = [{'Key': 'Name', 'Value': name}]
            aws_create_ec2_tag(ec2['InstanceId'], tags, message['region'], credentials)

            # function = f"arn:aws:lambda:{message['region']}:{message['account']}:function:{os.environ['Prefix']}carve-{ec2['SubnetId']}"
            # beacon = ec2['PrivateIpAddress']

        # elif 'EC2 Instance Terminate Successful' == message['detail-type']:
        #     subnet = message['detail']['Details']['Subnet ID']
        #     print(f"beacon terminated {message}")



def lambda_handler(event, context):
    print(f"event: {event}")
    
    if 'Records' in event:
        if 'Sns' in event['Records'][0]:
            print(f"TRIGGERED by SNS: {event['Records'][0]['EventSubscriptionArn']}")
            message = json.loads(event['Records'][0]['Sns']['Message'])
            if 'source' in message:
                if message['source'] == 'aws.autoscaling':
                    from utils import asg_event
                    asg_event(event)


if __name__ == "__main__":
    event = {}
    result = lambda_handler(event, None)
    print(result)

