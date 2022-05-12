import lambdavars

import os
import time

import networkx as nx
from botocore.exceptions import ClientError
from networkx.readwrite import json_graph

from aws import *
from carve import (carve_results, carve_role_arn, get_subnet_beacons,
                   load_graph, save_graph, update_carve_beacons)


def discover_subnets(region, account_id, account_name, credentials):
    ''' get VPCs in account/region, returns nx.Graph object of VPC nodes'''


    # create graph structure for VPCs
    G = nx.Graph()

    # get all non-default VpcIds owned by this account
    vpcids = []

    vpcs = aws_describe_vpcs(region, credentials, account_id)
    for vpc in vpcs:

        if vpc['OwnerId'] != account_id:
            # don't add shared VPCs
            continue

        if vpc['IsDefault']:
            # don't add default VPCs
            continue

        vpcids.append(vpc['VpcId'])


    for subnet in aws_describe_subnets(region, credentials, account_id):

        # ignore default VPCs and shared subnets
        if subnet['VpcId'] not in vpcids:
            continue

        # get subnet name from tag if available
        name = subnet['SubnetId']
        if 'Tags' in subnet:
            for tag in subnet['Tags']:
                if tag['Key'] == 'Name':
                    name = tag['Value']
                    break

        if name == f"{os.environ['Prefix']}carve-imagebuilder-public-subnet":
            # do not discover carve image builder subnet
            continue

        # create graph nodes
        G.add_node(
            subnet['SubnetId'],
            Name=name,
            Account=account_id,
            AccountName=account_name,
            Region=region,
            CidrBlock=vpc['CidrBlock'],
            VpcId=subnet['VpcId']
            )

    return G



def discover_vpcs(region, account_id, account_name, credentials):
    ''' get VPCs in account/region, returns nx.Graph object of VPC nodes'''


    # create graph structure for VPCs
    G = nx.Graph()

    subnets = aws_describe_subnets(region, credentials, account_id)

    for vpc in aws_describe_vpcs(region, credentials, account_id):

        if vpc['OwnerId'] != account_id:
            # don't add shared VPCs
            continue

        if vpc['IsDefault']:
            # don't add default VPCs
            continue

        # get VPC name from tag if available
        name = "unnamed"
        if 'Tags' in vpc:
            for tag in vpc['Tags']:
                if tag['Key'] == 'Name':
                    name = tag['Value']
                    break

        vpc_subnets = []
        for subnet in subnets:
            if subnet['VpcId'] == vpc['VpcId']:
                vpc_subnets.append({
                    "AvailabilityZoneId": subnet['AvailabilityZoneId'],
                    "SubnetId": subnet['SubnetId']
                })

        # create graph node
        G.add_node(
            vpc['VpcId'],
            Name=name,
            Account=account_id,
            AccountName=account_name,
            Region=region,
            CidrBlock=vpc['CidrBlock'],
            Subnets=vpc_subnets
            )

    return G


def discover_routing():
    # make sure all beacons are accounted for
    # update_carve_beacons()

    #  [{'subnet-0d310df8338186b7f': {
    #      'beacon': '10.0.22.112'
    #      'fping': {
    #          '10.0.22.112': 0.046,
    #          '10.0.43.87': 0.634,
    #          '10.1.9.32': 0.142,
    #          '10.2.10.235': 0.0,
    #          '10.3.5.235': 0.0,
    #          '10.4.3.255': 0.0
    #          },
    #     'health': 'up',
    #     'status': 200,
    #     'ts': '1620791060'
    #     }, ...]
    results = carve_results()

    # {'0.0.0.0': {
    #     'subnet': 'subnet-0d310df8338186b7f',
    #     'account': data['Account'],
    #     'region': data['Region']
    # }}
    subnet_beacons = get_subnet_beacons()

    # G.add_node(
    #     subnet['SubnetId'],
    #     Name=name,
    #     Account=account_id,
    #     AccountName=account_name,
    #     Region=region,
    #     CidrBlock=vpc['CidrBlock'],
    #     VpcId=subnet['VpcId']
    #     )
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    for ip, data in subnet_beacons.items():
        print(f'results: {results}')
        print(f'data: {data}')
        result = results[data['subnet']]
        if result['status'] == 200:
            for target, ms in result['fping'].items():
                if ms > 0:
                    G.add_edge(subnet_beacons[target]['subnet'], data['subnet'])

    name = f"routes_verified-{int(time.time())}"

    G.graph['Name'] = name

    save_graph(G, f"/tmp/{name}.json")

    file = aws_upload_file_s3(f'discovered/{name}.json', f"/tmp/{name}.json")

    return {'discovery': f"s3://{os.environ['CarveS3Bucket']}/discovered/{name}.json"}
 

def discover_resources(resource, region, account_id, account_name, credentials):
    # if resource == 'vpcs':
    #     G = discover_vpcs(region, account_id, account_name, credentials)
    # if resource == 'pcxs':
    #     G = discover_pcxs(region, account_id, account_name, credentials)

    G = discover_subnets(region, account_id, account_name, credentials)
    
    name = f'{resource}_{account_id}_{region}_{int(time.time())}'
    G.graph['Name'] = name

    save_graph(G, f"/tmp/{name}.json")

    aws_upload_file_s3(f'discovery/accounts/{name}.json', f"/tmp/{name}.json")

    return {resource: f'discovery/accounts/{name}.json'}


def sf_DiscoverAccount(event):
    ''' second step function task for discovery, per region/account '''

    # regions = aws_all_regions()
    discovered = []

    # for region in regions:
    account_id = event['Input']['account_id']
    account_name = event['Input']['account_name']
    regions = event['Input']['regions']

    credentials = aws_assume_role(carve_role_arn(account_id), f"carve-discovery")

    # for resource in ['vpcs', 'pcxs']:
    for region in regions:
        discovered.append(discover_resources('subnets', region, account_id, account_name, credentials))

    return {'Discovered': True}


def sf_StartDiscovery(context):
    # discover AWS Organizations accounts/regions to pass to next step
    accounts = aws_discover_org_accounts()
    regions = aws_all_regions()
    discovery_targets = []
    for account_id, account_name in accounts.items():
        discovery_targets.append({
            "account_id": account_id,
            "account_name": account_name,
            "regions": regions
        })
    print(f"discovering VPCs/PCXs in {len(accounts)} accounts")

    # need to purge S3 discovery folder before starting new discovery
    aws_purge_s3_path('discovery/accounts/')

    return discovery_targets


def sf_OrganizeDiscovery(event):

    subnets = aws_s3_list_objects(prefix='discovery/accounts')

    # Load all subnets into discovered graph G
    name = f"carve-discovered-{int(time.time())}"
    G = nx.Graph(Name=name)
    for subnet in subnets:
        path = f"/tmp/{subnet.split('/')[-1]}"
        if not os.path.isfile(path):
            aws_get_carve_s3(subnet, path)

        S = load_graph(path)
        G.add_nodes_from(S.nodes.data())

    save_graph(G, f"/tmp/{name}.json")

    aws_upload_file_s3(f'discovered/{name}.json', f"/tmp/{name}.json")

    return {'discovery': f's3://a-carve-o-dvdaw54vmt-us-east-1/discovered/{name}.json'}


def disco_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    if event['DiscoveryAction'] == 'StartDiscovery':
        response = sf_StartDiscovery(context)
        # need to return an array?

    elif event['DiscoveryAction'] == 'DiscoverAccount':
        response = sf_DiscoverAccount(event)

    elif event['DiscoveryAction'] == 'OrganizeDiscovery':
        response = sf_OrganizeDiscovery(event)
        # keep this here until the s3 bucket custom resource works
        aws_put_bucket_notification("deploy_input/", "CarveDeploy", context.invoked_function_arn)

    # return json to step function
    return response
    # return json.dumps(response, default=str)


def lambda_handler(event, context):
    print(event)
    return


if __name__ == "__main__":
    event = {}
    # event = {}
    result = lambda_handler(event, None)
    print(result)