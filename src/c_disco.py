import networkx as nx
from networkx.readwrite import json_graph
import boto3
import json
from botocore.exceptions import ClientError
import pylab as plt
import os
import sys
import time
from c_aws import *
from c_carve import carve_role_arn, save_graph, load_graph


# def build_org_graph(vpcs, pcxs):

#     G = nx.Graph(Name=f"carve-discovered-{int(time.time())}")

#     # process responses from vpc discovery processes
#     for parent_connection in v_parent_connections:
#         R = parent_connection.recv()        
#         G.add_nodes_from(R.nodes.data())


#     # process responses from peering discovery processes
#     P = nx.Graph()
#     for parent_connection in p_parent_connections:
#         R = parent_connection.recv()        
#         P.add_nodes_from(R.nodes.data())

#     accounts = discover_org_accounts()

#     # add edges by looking at all peering connections
#     for pcx in P.nodes.data():
#         G.add_edge(
#             pcx[1]['AccepterVpcId'],
#             pcx[1]['RequesterVpcId'],
#             Account=pcx[1]['Account'],
#             VpcPeeringConnectionId=pcx[1]['VpcPeeringConnectionId'],
#             AccountName=accounts[pcx[1]['Account']],
#             AccepterAccount=pcx[1]['AccepterAccount'],
#             AccepterAccountName=accounts[pcx[1]['AccepterAccount']],
#             AccepterVPCName=G.nodes[pcx[1]['AccepterVpcId']]['Name'],
#             RequesterAccount=pcx[1]['RequesterAccount'],
#             RequesterAccountName=accounts[pcx[1]['RequesterAccount']],
#             RequesterVPCName=G.nodes[pcx[1]['RequesterVpcId']]['Name']
#             )
#     print('discovery complete')
#     return G


def discover_org_accounts():
    ''' discover all accounts in the AWS Org'''
    client = boto3.client('organizations')
    accounts = {}

    # get top level accounts in root
    paginator = client.get_paginator('list_accounts')
    pages = paginator.paginate(PaginationConfig={'PageSize': 20})

    for page in pages:
        # add each account that is active
        for account in page['Accounts']:
            if account['Status'] == 'ACTIVE':
                # create new account object
                accounts[account['Id']] = account['Name']
    return accounts


def discover_subnets(region, account_id, account_name, credentials):
    ''' get VPCs in account/region, returns nx.Graph object of VPC nodes'''


    # create graph structure for VPCs
    G = nx.Graph()

    subnets = aws_describe_subnets(region, credentials, account_id)

    # get all non-default VpcIds owned by this account
    vpcids = []

    vpcs = aws_describe_vpcs(region, credentials)
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

        # vpc_subnets.append({
        #     "AvailabilityZoneId": subnet['AvailabilityZoneId'],
        #     "SubnetId": subnet['SubnetId']
        #     })

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

    for vpc in aws_describe_vpcs(region, credentials):

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
            Subnets=vpc_subnets,
            PrivateEndpoint=None,
            ApiGatewayUrl=None
            )

    return G


def discover_pcxs(region, account_id, account_name, credentials):
    ''' get peering conns in account/region, returns nx.Graph object of peering connection nodes'''

    G = nx.Graph()
    for pcx in aws_describe_peers(region, credentials):
        # get PCX name from tag
        name = "No Name"
        if 'Tags' in pcx:
            for tag in pcx['Tags']:
                if tag['Key'] == 'Name':
                    name = tag['Value']
                    break            

        G.add_node(
            pcx['VpcPeeringConnectionId'],
            Name=name,
            VpcPeeringConnectionId=pcx['VpcPeeringConnectionId'],
            Account=account_id,
            Region=region,
            AccepterVpcId=pcx['AccepterVpcInfo']['VpcId'],
            AccepterAccount=pcx['AccepterVpcInfo']['OwnerId'],
            RequesterVpcId=pcx['RequesterVpcInfo']['VpcId'],
            RequesterAccount=pcx['RequesterVpcInfo']['OwnerId']
            )

    return G


def discover_tgws(region, credentials):
    # describe tgws
    # describe tgw attachments using tgw
    # describe tgw peering using attachment
    tgws = aws_describe_transit_gateways(region, credentials)
    attachments = aws_describe_transit_gateway_attachments(region, credentials)
    route_tables = aws_describe_transit_gateway_route_tables(region, credentials)


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
    region = event['Input']['region']

    credentials = aws_assume_role(carve_role_arn(account_id), f"carve-discovery-{region}")

    # for resource in ['vpcs', 'pcxs']:
    discovered.append(discover_resources('subnets', region, account_id, account_name, credentials))

    return discovered


def sf_StartDiscovery():
    # discover AWS Organizations accounts/regions to pass to next step
    accounts = discover_org_accounts()
    regions = aws_all_regions()
    discovery_targets = []
    for account_id, account_name in accounts.items():
        for region in regions:
            discovery_targets.append({
                "account_id": account_id,
                "account_name": account_name,
                "region": region
            })

    print(f"discovering VPCs/PCXs in {len(accounts)} accounts")

    # need to purge S3 discovery folder before starting new discovery
    aws_purge_s3_path('discovery/accounts/')

    return discovery_targets


def sf_OrganizeDiscovery(event):

    subnets = []
    # pcxs = []

    for payload in event['Input']:
        for s3_path in payload['Payload']:
            if 'subnets' in s3_path:
                subnets.append(s3_path['subnets'])
            # elif 'pcxs' in s3_path:
            #     pcxs.append(s3_path['pcxs'])

    # Load all subnets into discovered graph G
    name = f"carve-discovered-{int(time.time())}"
    G = nx.Graph(Name=name)
    for subnet in subnets:
        path = f"/tmp/{subnet.split('/')[-1]}"
        if not os.path.isfile(path):
            aws_get_carve_s3(subnet, path)

        S = load_graph(path)
        G.add_nodes_from(S.nodes.data())

    # # Load all peering connections into temp P
    # P = nx.Graph()
    # for pcx in pcxs:
    #     path = f"/tmp/{pcx.split('/')[-1]}"
    #     if not os.path.isfile(path):
    #         aws_get_carve_s3(pcx, path)
    #     X = load_graph(path)
    #     P.add_nodes_from(X.nodes.data())

    # # add edges to G by looking at all peering connections
    # accounts = discover_org_accounts()
    # for pcx in P.nodes.data():
    #     G.add_edge(
    #         pcx[1]['AccepterVpcId'],
    #         pcx[1]['RequesterVpcId'],
    #         Account=pcx[1]['Account'],
    #         VpcPeeringConnectionId=pcx[1]['VpcPeeringConnectionId'],
    #         AccountName=accounts[pcx[1]['Account']],
    #         AccepterAccount=pcx[1]['AccepterAccount'],
    #         AccepterAccountName=accounts[pcx[1]['AccepterAccount']],
    #         AccepterVPCName=G.nodes[pcx[1]['AccepterVpcId']]['Name'],
    #         RequesterAccount=pcx[1]['RequesterAccount'],
    #         RequesterAccountName=accounts[pcx[1]['RequesterAccount']],
    #         RequesterVPCName=G.nodes[pcx[1]['RequesterVpcId']]['Name']
    #         )

    save_graph(G, f"/tmp/{name}.json")

    aws_upload_file_s3(f'discovered/{name}.json', f"/tmp/{name}.json")

    return {'discovery': f's3://a-carve-o-dvdaw54vmt-us-east-1/discovered/{name}.json'}


def disco_entrypoint(event, context):
    ''' step function tasks for deployment all flow thru here after the lambda_hanlder '''
    if event['DiscoveryAction'] == 'StartDiscovery':
        response = sf_StartDiscovery()
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


