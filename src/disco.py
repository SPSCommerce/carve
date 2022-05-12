# import pylab as plt
import os
import time

import networkx as nx
from botocore.exceptions import ClientError
from networkx.readwrite import json_graph

from aws import *
from carve import (carve_results, carve_role_arn, get_subnet_beacons,
                   load_graph, save_graph, update_carve_beacons)



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
 
