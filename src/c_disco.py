import networkx as nx
from networkx.readwrite import json_graph
import boto3
import json
from botocore.exceptions import ClientError
import pylab as plt
from multiprocessing import Process, Pipe
import os
import sys
import time
from c_aws import aws_parallel_role_creation, aws_upload_file_carve_s3
from botocore.config import Config



def _discover_org_graph(accounts, regions, context):

    # when refacotring for lambda
    # could self invoke to split vpc/peering discovery
    # would make each lambda have to handle 1/2 as many parallel processes

    # create a list to all processes and connections
    v_processes = []
    v_parent_connections = []
    p_processes = []
    p_parent_connections = []

    role = f"arn:aws:sts::*:role/{os.environ['ResourcePrefix']}carve-lambda-{os.environ['OrganizationsId']}"

    # create all IAM assumed role sessions now, and store their credentials
    credentials = aws_parallel_role_creation(accounts.keys(), role)

    # create one VPC and one Peering discovery process per AWS account and region
    processes = (len(accounts) * len(regions))
    print(f'starting {processes} discovery processes for {len(accounts)} accounts in {len(regions)} regions')

    for account_id, account_name in accounts.items():
        for region in regions:

            # process for discovering VPCs in account/region
            v_parent_conn, v_child_conn = Pipe()
            v_parent_connections.append(v_parent_conn)
            v_process = Process(
                target=_discovery_process,
                args=(account_id, account_name, region, credentials[account_id], 'vpcs', v_child_conn)
                )
            v_processes.append(v_process)
            v_process.start()

            # process for discovering PCXs in account/region
            p_parent_conn, p_child_conn = Pipe()
            p_parent_connections.append(p_parent_conn)
            p_process = Process(
                target=_discovery_process,
                args=(account_id, account_name, region, credentials[account_id], 'peering', p_child_conn)
                )
            p_processes.append(p_process)
            p_process.start()

    # wait for all processes to finish
    for process in v_processes:
        process.join()

    # wait for all processes to finish
    for process in p_processes:
        process.join()

    G = nx.Graph(Name=f"carve-discovered-{int(time.time())}")

    # process responses from vpc discovery processes
    for parent_connection in v_parent_connections:
        R = parent_connection.recv()        
        G.add_nodes_from(R.nodes.data())


    # process responses from peering discovery processes
    P = nx.Graph()
    for parent_connection in p_parent_connections:
        R = parent_connection.recv()        
        P.add_nodes_from(R.nodes.data())

    # add edges by looking at all peering connections
    for pcx in P.nodes.data():
        G.add_edge(
            pcx[1]['AccepterVpcId'],
            pcx[1]['RequesterVpcId'],
            Account=pcx[1]['Account'],
            VpcPeeringConnectionId=pcx[1]['VpcPeeringConnectionId'],
            AccountName=accounts[pcx[1]['Account']],
            AccepterAccount=pcx[1]['AccepterAccount'],
            AccepterAccountName=accounts[pcx[1]['AccepterAccount']],
            AccepterVPCName=G.nodes[pcx[1]['AccepterVpcId']]['Name'],
            RequesterAccount=pcx[1]['RequesterAccount'],
            RequesterAccountName=accounts[pcx[1]['RequesterAccount']],
            RequesterVPCName=G.nodes[pcx[1]['RequesterVpcId']]['Name']
            )
    print('discovery complete')
    return G


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


def _discovery_process(account_id, account_name, region, credentials, resources, child_conn):
    '''discover VPC/peering resources in a specific account/region, return nx.Graph'''

    # discover resources, with G as a graph data structure
    if resources == 'vpcs':
        G = _discover_vpcs(region, account_id, account_name, credentials)
    if resources == 'peering':
        G = _discover_peering(region, account_id, credentials)
  
    # return graph object and close
    child_conn.send(G)
    child_conn.close()



def _discover_vpcs(region, account_id, account_name, credentials, default_vpcs=False):
    ''' get VPCs in account/region, returns nx.Graph object of VPC nodes'''
    client = boto3.client(
        'ec2',
        config=Config(retries=dict(max_attempts=10)),
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    # create graph structure for VPCs
    G = nx.Graph()

    # get all VPCs in this region
    paginator = client.get_paginator('describe_vpcs')
    for pages in paginator.paginate():
        for vpc in pages['Vpcs']:

            if vpc['OwnerId'] != account_id:
                # don't add shared VPCs
                continue

            if vpc['IsDefault']:
                if not default_vpcs:
                    # don't add default VPCs unless requested
                    continue

            # get VPC name from tag if available
            name = "No Name"
            if 'Tags' in vpc:
                for tag in vpc['Tags']:
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                        break

            # create graph node
            G.add_node(
                vpc['VpcId'],
                Name=name,
                Account=account_id,
                AccountName=account_name,
                Region=region,
                CidrBlock=vpc['CidrBlock'],
                PrivateEndpoint=None,
                ApiGatewayUrl=None
                )
    return G


def _discover_peering(region, account_id, credentials):
    ''' get peering conns in account/region, returns nx.Graph object of peering connection nodes'''
    client = boto3.client(
        'ec2',
        config=Config(retries=dict(max_attempts=10)),
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    G = nx.Graph()

    paginator = client.get_paginator('describe_vpc_peering_connections')
    for pages in paginator.paginate():
        for conn in pages['VpcPeeringConnections']:
            # get PCX name from tag
            name = "No Name"
            if 'Tags' in conn:
                for tag in conn['Tags']:
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                        break            
            G.add_node(
                conn['VpcPeeringConnectionId'],
                Name=name,
                VpcPeeringConnectionId=conn['VpcPeeringConnectionId'],
                Account=account_id,
                Region=region,
                AccepterVpcId=conn['AccepterVpcInfo']['VpcId'],
                AccepterAccount=conn['AccepterVpcInfo']['OwnerId'],
                RequesterVpcId=conn['RequesterVpcInfo']['VpcId'],
                RequesterAccount=conn['RequesterVpcInfo']['OwnerId']
                )

    return G


def discovery(event, context):
    ''' kick off org/vpc/pcx discovery logic '''
    print('generating dynamic org vpc graph')

    # discover AWS Organizations Accounts
    accounts = discover_org_accounts()

    client = boto3.client('ec2', region_name=os.environ['AWS_REGION'])
    regions = [region['RegionName'] for region in client.describe_regions()['Regions']]

    # run primary VPC/PCX discovery function
    G = _discover_org_graph(accounts, regions, context)

    G.graph['Name'] = f'c_discovered_{int(time.time())}'

    print("discovery complete uploading to s3")
    # save json data
    with open(f"/tmp/{G.graph['Name']}.json", 'a') as f:
        json.dump(json_graph.node_link_data(G), f)

    aws_upload_file_carve_s3('discovery/', f"/tmp/{G.graph['Name']}.json")

    return 


