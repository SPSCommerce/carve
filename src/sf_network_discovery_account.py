import lambdavars
import networkx as nx
from aws import *
from utils import (carve_role_arn, save_graph)
from networkx.readwrite import json_graph


def discover_nodes(region, account_id, account_name, credentials):
    ''' get subnets in account/region, returns nx.Graph object of subnets nodes'''

    # create graph structure for subnets
    G = nx.Graph()

    # determine default security group for each VPC in this region
    default_groups = aws_discover_default_security_groups(credentials, region)

    # first add discovered VPC nodes
    print("discovering vpcs in {}".format(region))
    vpcs = aws_describe_vpcs(region, credentials, account_id)
    for vpc in vpcs:

        if vpc['OwnerId'] != account_id:
            # don't add VPCs that are shared to this account
            continue

        if vpc['IsDefault']:
            # don't add default VPCs
            continue

        # get tags from vpc
        try:
            tags = aws_tag_dict(vpc['Tags'])
        except:
            tags = {}

        # update vpc name to match tag if available
        try:
            vpc_name = tags['Name']
        except:
            vpc_name = vpc['VpcId']

        # add vpc nodes to graph
        G.add_node(
            vpc['VpcId'],
            Name=vpc_name,
            Account=account_id,
            AccountName=account_name,
            Region=region,
            CidrBlock=vpc['CidrBlock'],
            Type='vpc',
            DefaultSecurityGroup=default_groups[vpc['VpcId']],
            Tags=tags
            )

    # next add subnet nodes
    print("discovering subnets in {}".format(region))
    for subnet in aws_describe_subnets(region, account_id, credentials):

        # only add subnets for discovered vpcs
        if subnet['VpcId'] not in G.nodes():
            continue

        # get tags from subnet
        try:
            tags = aws_tag_dict(subnet['Tags'])
        except:
            tags = {}

        # update subnet name to match tag if available
        try:
            subnet_name = tags['Name']
        except:
            subnet_name = subnet['SubnetId']

        # create graph nodes for subnets
        G.add_node(
            subnet['SubnetId'],
            Name=subnet_name,
            Account=account_id,
            AccountName=account_name,
            Region=region,
            AvailabilityZone=subnet['AvailabilityZone'],
            AvailabilityZoneId=subnet['AvailabilityZoneId'],
            CidrBlock=subnet['CidrBlock'],
            VpcId=subnet['VpcId'],
            Type='subnet',
            Tags=tags
            )

    # return graph of all subnets in this region
    return G


def lambda_handler(event, context):
    '''
    this lambda discovers all subnets in the regions and accounts defined in the event
    the reults are uploaded to the carve managed S3 bucket in the discovery directory

    event = {'regions': ['us-east-1', ...], 'account': {'account_id': '123456789012', 'account_name': 'awsaccountname'}}
    
    '''
    print(event) # for debugging

    # get account_id and account_name and regions from event
    account_id = event['account']['account_id']
    account_name = event['account']['account_name']
    regions = event['regions']

    # use one set of credentials for all regions
    credentials = aws_assume_role(carve_role_arn(account_id), f"carve-discovery")

    # graph for all subnets in all regions in this account
    A = nx.Graph()
    A.graph['Name'] = f'subnets_{account_id}_{account_name}'

    # discover subnets in each region
    for region in regions:
        # test if we can connect to the region
        if not aws_active_region(region, credentials, account_id):
            continue

        # create networkx instance of all subnets and vpcs in this region
        R = discover_nodes(region, account_id, account_name, credentials)
        
        # add discovered subnets to A
        A.add_nodes_from(R.nodes.data())


    if len(A.nodes) > 0:
        save_graph(A, f"/tmp/{A.graph['Name']}.json")
        aws_upload_file_s3(f"discovery/{A.graph['Name']}.json", f"/tmp/{A.graph['Name']}.json")

    json_data = json.dumps(json_graph.node_link_data(A))

    print(f"discovered {len(A.nodes)} subnets in {account_id} {account_name}: {json_data}")


if __name__ == "__main__":
    event = {}
    result = lambda_handler(event, None)
    print(json.dumps(result))
    
