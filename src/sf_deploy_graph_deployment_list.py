import lambdavars
import json
import os
from copy import deepcopy
from utils import load_graph, get_deploy_key
from aws import *


def deployment_list(G, upload_template=True):
    ''' 
    return a list of stacks to deploy, formatted for the deploy stacks step function
    '''

    # create a list for deployments
    deploy_beacons = []

    # remove external beacons from the graph
    external = [node for node in G.nodes() if G.nodes().data()[node]['Type'] == 'external']
    G.remove_nodes_from(external)

    # determine all VPCs in the graph and their account and region
    vpcs = {}
    regions = set()
    for subnet in list(G.nodes):
        a = G.nodes().data()[subnet]['Account']
        r = G.nodes().data()[subnet]['Region']
        vpcs[G.nodes().data()[subnet]['VpcId']] = (a, r)
        regions.add(r)

    # create a region map of private link endpoints
    region_map = {}
    for region in regions:
        # get carve private link stack outputs
        stackname = f"{os.environ['Prefix']}carve-managed-privatelink-{region}"
        outputs = aws_get_stack_outputs_dict(stackname, current_region)
        try:
            region_map[region] = f"com.amazonaws.vpce.{current_region}.{outputs['EndpointService']}"
        except:
            raise f"No private link service found in region {region}"


    # generate 1 CFN stack per VPC
    for vpc, ar in vpcs.items():

        account = ar[0]
        region = ar[1]

        vpc_subnets = [x for x,y in G.nodes(data=True) if y['VpcId'] == vpc]

        # generate the CFN template for this VPC
        vpc_template, stack = generate_template(vpc, vpc_subnets, account, region_map[region], region)

        # push template to s3
        if upload_template:
            key = f"managed_deployment/{vpc}.cfn.json"
            data = json.dumps(vpc_template, ensure_ascii=True, indent=2, sort_keys=True)
            aws_put_direct(data, key)
        
        # add stack to list of stacks to deploy
        deploy_beacons.append(stack)

    return deploy_beacons


def generate_template(vpc, vpc_subnets, account, vpce_service, region):

    # open vpc stack base template
    with open("managed_deployment/carve-vpc-stack.cfn.json") as f:
        vpc_template = json.load(f)

    # open lambda code to insert into template
    with open("managed_deployment/subnet_lambda.py") as f:
        lambda_code = f.read()

    # update the VPC CFN template to contain 1 lambda function per subnet
    for subnet in vpc_subnets:
        Function = deepcopy(vpc_template['Resources']['SubnetFunction'])
        Function['Properties']['FunctionName'] = f"{os.environ['Prefix']}carve-{subnet}"
        Function['Properties']['Environment']['Variables']['VpcSubnetIds'] = subnet
        Function['Properties']['VpcConfig']['SubnetIds'] = [subnet]
        Function['Properties']['Code']['ZipFile'] = lambda_code
        name = f"Function{subnet.split('-')[-1]}"
        vpc_template['Resources'][name] = deepcopy(Function)

    # remove original SubnetFunction object from template
    del vpc_template['Resources']['SubnetFunction']

    # generate CFN stack deployment parameters
    stack = {}
    stack['StackName'] = f"{os.environ['Prefix']}carve-managed-beacons-{vpc}"
    stack['Account'] = account
    stack['Region'] = region
    stack['Template'] = f"managed_deployment/{vpc}.cfn.json"
    stack['Parameters'] = [
        {
            "ParameterKey": "VpcId",
            "ParameterValue": vpc
        },
        {
            "ParameterKey": "VpcSubnetIds",
            "ParameterValue": ','.join(vpc_subnets)
        },      
        {
            "ParameterKey": "Prefix",
            "ParameterValue": os.environ['Prefix']
        },
        {
            "ParameterKey": "CarveSNSTopicArn",
            "ParameterValue": os.environ['CarveSNSTopicArn']
        },
        {
            "ParameterKey": "ServiceName",
            "ParameterValue": vpce_service
        }
    ]

    return vpc_template, stack


def lambda_handler(event, context):

    '''
    returns a list of cfn stack deployments using deployment_list() to render the templates
    and generate the stack parameters
    '''
    G = load_graph(get_deploy_key(), local=False)
    stack_deployments = deployment_list(G)

    # return stack_deployments
    return json.dumps(stack_deployments, default=str)
