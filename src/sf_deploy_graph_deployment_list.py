import lambdavars
import json
import os
from copy import deepcopy
from utils import load_graph, get_deploy_key, select_subnets, matching_node_values
from aws import *
from datetime import datetime

def deployment_list(G, upload_template=True):
    ''' 
    return a list of stacks to deploy, formatted for the deploy stacks step function
    '''

    # create a list for deployments
    deploy_beacons = []

    # create date/time stamp for template
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # remove external beacons from the graph
    external = [node for node in G.nodes() if G.nodes().data()[node]['Type'] == 'external']
    G.remove_nodes_from(external)

    # determine all VPCs in the graph and their account and region
    vpcs = {}
    regions = set()
    for vpc in matching_node_values(G, 'Type', 'vpc', return_value=None):
        account = G.nodes().data()[vpc]['Account']
        region = G.nodes().data()[vpc]['Region']
        vpcs[vpc] = (account, region)
        regions.add(region)

    # create a region map of private link endpoint urls
    region_map = {}
    for region in regions:
        # get carve private link stack outputs
        stackname = f"{os.environ['Prefix']}carve-managed-privatelink-{region}"
        outputs = aws_get_stack_outputs_dict(stackname, region)
        try:
            region_map[region] = f"com.amazonaws.vpce.{region}.{outputs['EndpointService']}"
        except:
            raise f"No private link service found in region {region}"

    print(f"region_map: {region_map}")

    # generate a list of preferred subnets for each VPC to be used if VerificationScope is set to VPC
    print("generating preferred subnet lists")
    # subnets = {'VpcId': {"subnet": SubnetId, "name": Name, "azid": AvailabilityZoneId}}
    subnets = select_subnets(G)

    # generate 1 CFN stack per VPC
    skipped = []
    for vpc, location in vpcs.items():

        account = location[0]
        region = location[1]

        # default scope to vpc if verification scope is not defined in graph
        try:
            scope = G.graph["VerificationScope"]
        except:
            scope = "vpc"

        if scope == "subnet":
            vpc_subnets = [x for x,y in G.nodes(data=True) if y['VpcId'] == vpc]
        elif scope == "vpc":
            try:
                vpc_subnets = [subnets[vpc]['subnet']]
            except:
                skipped.append(vpc)
                print(f"WARNING: No preferred subnet found for VPC {vpc}. Excluding VPC.")
                continue

        # generate the CFN template for this VPC
        security_group = G.nodes().data()[vpc]['DefaultSecurityGroup']
        vpc_template, stack = generate_template(vpc, vpc_subnets, security_group, account, region_map[region], region)

        # push template to s3
        if upload_template:
            key = f"managed_deployment/{timestamp}/{vpc}.cfn.json"
            stack['Template'] = key
            data = json.dumps(vpc_template, ensure_ascii=True, indent=2, sort_keys=True)
            aws_put_direct(data, key)
            print(f"uploaded {key} to s3")
        
        # add stack to list of stacks to deploy
        deploy_beacons.append(stack)

    if len(skipped) > 0:
        print(f"WARNING: The following VPCs were excluded from deployment due to missing preferred subnets: {skipped}")

    return deploy_beacons


def generate_template(vpc, vpc_subnets, security_group, account, vpce_service, region):

    # get current folder path
    path = f"{os.path.dirname(os.path.realpath(__file__))}/managed_deployment"

    # open vpc stack base template
    with open(f"{path}/carve-vpc-stack.cfn.json") as f:
        vpc_template = json.load(f)

    # open subnet lambda code to insert into template
    with open(f"{path}/subnet_lambda.py") as f:
        lambda_code = f.read()

    # update the VPC CFN template to contain 1 lambda function per subnet
    i=1
    for subnet in vpc_subnets:
        # create a copy of the lambda function for each subnet
        Function = deepcopy(vpc_template['Resources']['SubnetFunction'])
        Function['Properties']['FunctionName'] = f"{os.environ['Prefix']}carve-{subnet}"
        Function['Properties']['Environment']['Variables']['VpcSubnetIds'] = subnet
        Function['Properties']['VpcConfig']['SubnetIds'] = [subnet]
        Function['Properties']['Code']['ZipFile'] = lambda_code
        # add the function to the template, and to the delete function variables in the template
        vpc_template['Resources'][f"Function{subnet.split('-')[-1]}"] = deepcopy(Function)
        vpc_template['Resources']['LambdaDelete']['Properties']['Environment']['Variables'][f"Function{i}"] = f"{os.environ['Prefix']}carve-{subnet}"
        i+=1

    # set the number of subnet lambdas for the lambda delete function
    vpc_template['Resources']['LambdaDelete']['Properties']['Environment']['Variables']['FunctionCount'] = str(len(vpc_subnets))

    # insert the lambda delete CFN resource code into the template
    with open(f"{path}/lambda_delete.py") as f:
        delete_lambda_code = f.read()
    vpc_template['Resources']['LambdaDelete']['Properties']['Code']['ZipFile'] = delete_lambda_code

    # remove original SubnetFunction object from template
    del vpc_template['Resources']['SubnetFunction']

    # generate CFN stack deployment parameters
    stack = {}
    stack['StackName'] = f"{os.environ['Prefix']}carve-managed-endpoints-{vpc}"
    stack['Account'] = account
    stack['Region'] = region
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
            "ParameterKey": "VpcSecurityGroupId",
            "ParameterValue": security_group
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


if __name__ == '__main__':
    event = {"Input": {"graph": "discovered/carve-test-all.json"}}
    G = load_graph(event=event, local=False)
 
    stack_deployments = deployment_list(G)

    # return stack_deployments
    print(json.dumps(stack_deployments, default=str))