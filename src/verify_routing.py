# import pylab as plt
import lambdavars
import os

import concurrent.futures
from networkx.readwrite import json_graph

from aws import *
from utils import (load_graph, save_graph, carve_role_arn,
                   get_deploy_key)


def add_routes(G):
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
    print("verifying routes...")
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
    R = add_graph_links(G, verified_routes, inventory)
    return R


def add_graph_links(G, verified_routes, inventory):
    '''
    create new graph with links by adding routes to the currently deployed graph
    '''
    # make new dict from inventory with address as key and subnet/name for easy lookup
    print("adding routes to graph...")
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
    result = aws_invoke_lambda(lambda_arn, payload, credentials)
    verified = {subnet_id: result}
    return verified


def verify_routing(G=None, graph_key=None, output_key=None):
    '''
    main function to run routing verification. graph can be loaded 3 ways:
     - provide a graph_key to load from the carve s3 bucket
     - provide graph as a networkx graph
     - providing neither graph_key or graph_data will load most recently deployed graph from s3
    
    If output_key is provided, the graph will be saved to provided key in the carve s3 bucket
    '''

    # determine which graph to use
    if G != None:
        print('graph provided, using provided graph...')
    elif graph_key != None:
        print('graph_key provided, loading graph...')
        G = load_graph(graph_key, local=False)
    else:
        # if neither provided, load last deploy key from s3
        print('no graph provided, loading last deploy key...')
        deploy_key = get_deploy_key(last=True)
        if not deploy_key:
            raise Exception('No graph provided or found')
        else:
            G = load_graph(deploy_key, local=False)

    # remove any old routes from graph
    G.remove_edges_from(G.edges)

    # create a new graph with verified routes
    R = add_routes(G)

    if output_key != None:
        # set a name for the new graph and save to s3
        name = output_key.split('/')[-1]
        R.graph['Name'] = name
        save_graph(R, f"/tmp/{name}.json")
        aws_upload_file_s3(output_key, f"/tmp/{name}.json")
        return {'discovery': f"s3://{os.environ['CarveS3Bucket']}/{output_key}"}
    else:
        # if no s3 path provided, return the graph data with routes
        R.graph['Name'] = f"carve-routes-verified-{int(time.time())}"
        return json_graph.node_link_data(R)


if __name__ == '__main__':
    local_graph = "ignore/carve-test-pl-subnets.json"
    G = load_graph(local_graph, local=True)
    routed_graph = verify_routing(G=G)

    print(routed_graph)

