import lambdavars
import os
import time
import networkx as nx
from aws import *
from carve import (carve_role_arn, save_graph)


def discover_subnets(region, account_id, account_name, credentials):
    ''' get subnets in account/region, returns nx.Graph object of subnets nodes'''

    # create graph structure for subnets
    G = nx.Graph()

    # list will be filled with all non-default VpcIds owned by this account
    vpcids = []

    vpcs = aws_describe_vpcs(region, credentials, account_id)
    for vpc in vpcs:

        if vpc['OwnerId'] != account_id:
            # don't add VPCs that are shared to this account
            continue

        if vpc['IsDefault']:
            # don't add default VPCs
            continue

        vpcids.append(vpc['VpcId'])


    for subnet in aws_describe_subnets(region, credentials, account_id):

        # ignore default VPCs and shared subnets
        if subnet['VpcId'] not in vpcids:
            continue

        subnet_name = subnet['SubnetId']

        # update subnet name to match tag if available
        if 'Tags' in subnet:
            for tag in subnet['Tags']:
                if tag['Key'] == 'Name':
                    subnet_name = tag['Value']
                    break

        if subnet_name == f"{os.environ['Prefix']}carve-imagebuilder-public-subnet":
            # exclude carve image builder subnet
            continue

        # create graph nodes
        G.add_node(
            subnet['SubnetId'],
            Name=subnet_name,
            Account=account_id,
            AccountName=account_name,
            Region=region,
            CidrBlock=vpc['CidrBlock'],
            VpcId=subnet['VpcId']
            )

    # return graph of all subnets in this region
    return G


def lambda_handler(event, context):
    '''
    this lambda discovers all subnets in the provided account/regions, and uploads the reults to S3

    event = {'regions': ['us-east-1', ...], 'account': {'account_id': '104966627370', 'account_name': 'spsc'}}
    
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

        # create networkx instance of all subnets in this region
        R = discover_subnets(region, account_id, account_name, credentials)
        
        # add discovered subnets to A
        A.add_nodes_from(R.nodes.data())


    if len(A.nodes) > 0:
        save_graph(A, f"/tmp/{A.graph['Name']}.json")
        aws_upload_file_s3(f"discovery/{A.graph['Name']}.json", f"/tmp/{A.graph['Name']}.json")

    print(f"discovered {len(A.nodes)} subnets in {account_id} {account_name}: {A.nodes.data()}")


if __name__ == "__main__":
    event = {
        'regions': ['ap-northeast-1', 'ap-northeast-2', 'ap-northeast-3', 'ap-south-1', 'ap-southeast-1', 'ap-southeast-2', 'ap-southeast-3', 'ca-central-1', 'eu-central-1', 'eu-north-1', 'eu-west-1', 'eu-west-2', 'eu-west-3', 'sa-east-1', 'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2'],
        'account': {'account_id': '104966627370', 'account_name': 'spsc'}
        # 'account': {'account_id': '602068278189', 'account_name': 'spsartifactsnonprod'}
        }
    result = lambda_handler(event, None)
    print(json.dumps(result))
    
