# import pylab as plt
import lambdavars
import os
import time

import concurrent.futures

from aws import *
from carve import (load_graph, save_graph, carve_role_arn,
                   get_deploy_key)


def verify_current_routes(G):
    '''
    run a verification of current routes, invoking every subnet lamabda function in a thread
    then process the results and add verified routes to the graph
    '''
    # pull beacon inventory from s3
    inventory = json.loads(aws_read_s3_direct('managed_deployment/beacon-inventory.json'))
    
    # get all addresses from beacons
    beacons = [beacon['address'] for beacon in inventory.values()]

    cred_cache = {}
    verified_routes = {}
    futures = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=300) as executor:
            for target, data in inventory.items():
                # only create threads for carve managed subnet lambdas
                if data['type'] == 'managed':

                    # reuse account creds in threads
                    if data['account'] not in cred_cache:
                        credentials = aws_assume_role(carve_role_arn(data['account']), f"verification")
                        cred_cache[data['account']] = credentials
                    else:
                        credentials = cred_cache[data['account']]

                    # add a thread for each subnet lambda
                    futures.add(executor.submit(
                        verify_subnet_routes,
                        subnet_id=target,
                        credentials=credentials,
                        region=data['region'],
                        beacons=beacons
                        ))

            # collect thread results
            for future in concurrent.futures.as_completed(futures):
                for subnet, results in future.result().items():
                    verified_routes[subnet] = results

    # add verified routes to graph
    R = create_graph_links(G, verified_routes, inventory)
    return R


def create_graph_links(G, verified_routes, inventory):
    '''
    create new graph with links by adding routes to the currently deployed graph
    '''
    # make new dict from inventory with address as key and subnet/name for easy lookup
    beacons_dict = {}
    for beacon, data in inventory.items():
        beacons_dict[data['address']] = beacon

    # add route links to managed subnets in graph
    for subnet in list(G.nodes):
        if G.nodes[subnet]['Type'] == 'managed':
            for result in verified_routes[subnet]:
                if result['result'] == 'up':
                    beacon = result['beacon']
                    edge = beacons_dict[beacon]
                    if subnet != edge:
                        G.add_edge(subnet, edge)
    return G


def verify_subnet_routes(subnet_id, credentials, region, beacons):
    '''
    pass a payload of beacon targets to verify and return the results
    '''
    lambda_arn = f"arn:aws:lambda:{region}:{credentials['Account']}:function:{os.environ['Prefix']}carve-{subnet_id}"
    payload = {'action': 'verify', 'beacons': beacons}
    result = aws_invoke_lambda(lambda_arn, payload, region, credentials)
    verified = {subnet_id: result}
    return verified


def lambda_handler(event, context):
    # load current graph from s3
    deploy_key = get_deploy_key()
    if not deploy_key:
        raise Exception('No deployment key found')
    G = load_graph(deploy_key, local=False)

    # create a new graph with verified routes from graph G
    R = verify_current_routes(G)

    # set a name for the new graph and save to s3
    name = f"routes_verified-{int(time.time())}"
    G.graph['Name'] = name
    save_graph(G, f"/tmp/{name}.json")
    aws_upload_file_s3(f'discovered/{name}.json', f"/tmp/{name}.json")

    return {'discovery': f"s3://{os.environ['CarveS3Bucket']}/discovered/{name}.json"}




if __name__ == '__main__':
    # lambda_handler(None, None)

    # deploy_key = get_deploy_key()
    # if not deploy_key:
    #     raise Exception('No deployment key found')

    deploy_key = "ignore/carve-test-pl-subnets.json"

    # get inventory of all beacons (endpoint private IP addresses)
    G = load_graph(deploy_key, local=True)
    R = verify_current_routes(G)
    file_path = f"ignore/{R.graph['Name']}-routing.json"
    save_graph(R, file_path)
