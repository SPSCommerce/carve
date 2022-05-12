import lambdavars
from aws import *
import json
from carve import carve_role_arn



def lambda_handler(event, context):
    print(f"event: {event}")

    # need to coerce data
    # data lives in "Payload" on first check, then when passed from the choice
    # state the data moves to the top of the json object
    data = {'asg': {}}

    if "Payload" in event:
        print("Payload found")
        data['asg']['account'] = event['Payload']['asg']['account']
        data['asg']['name'] = event['Payload']['asg']['name']
        data['asg']['region'] = event['Payload']['asg']['region']
        data['scale'] = event['Payload']['scale']
    else:
        print("Payload not found")
        data = event
 
    credentials = aws_assume_role(carve_role_arn(data['asg']['account']), f"lookup-{data['asg']['name']}")
    response = aws_describe_asg(data['asg']['name'], data['asg']['region'], credentials)

    instances = response['AutoScalingGroups'][0]['Instances']
    scale_status = "SCALE_IN_PROGRESS"

    if data['scale'] == 'down':
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
    data['ScaleStatus'] = scale_status

    print(f"returning: {json.dumps(data, default=str)}")
    return json.dumps(data, default=str)


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
    print(result)