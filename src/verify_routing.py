# import pylab as plt
from telnetlib import GA
import lambdavars
import os

import concurrent.futures
from networkx.readwrite import json_graph

from aws import *
from utils import (load_graph, save_graph, carve_role_arn,
                   get_deploy_key, matching_node_values)


def add_routes(G):
    '''
    run a verification of current routes, invoking every subnet lamabda function in a thread
    then process the results and add verified routes to the graph
    '''
    # pull beacon inventory from s3
    inventory = json.loads(aws_read_s3_direct('managed_deployment/beacon-inventory.json'))
    
    # get all addresses from beacons
    beacons = [beacon['address'] for beacon in inventory.values()]

    print("verifying routes with beacons: ", beacons)

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
                else:
                    print(f"skipping {target} - not a managed beacon")

            # collect thread results
            for future in concurrent.futures.as_completed(futures):
                for subnet, results in future.result().items():
                    verified_routes[subnet] = results

            print(f"verified routes: {verified_routes}")

    # add verified routes to graph
    R = add_graph_links(G, verified_routes, inventory)
    return R


def add_graph_links(G, verified_routes, inventory):
    '''
    create new graph with links by adding routes (links) to the currently deployed graph
    '''
    # make new dict from inventory with address as key and subnet/name for easy lookup
    print("adding routes to graph...")
    beacons_dict = {}
    for beacon, data in inventory.items():
        beacons_dict[data['address']] = beacon

    print("beacons:", beacons_dict)

    # add route links to managed beacons in graph
    for subnet, data in inventory.items():
        print(subnet, data)
        if data['type'] == 'managed':
            for result in verified_routes[subnet]:
                if result['result'] == 'up':
                    beacon = result['beacon']
                    edge = beacons_dict[beacon]
                    if subnet != edge:
                        G.add_edge(subnet, edge)
                        print(f"route added: {subnet} to {edge}")
                    else:
                        print(f"route not added: {subnet} to {edge} - same subnet")
                else:
                    print(f"route down: {subnet} to {data}")
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


def vpc_routing_report(key):
    '''
    Generate a more human digestible report of the current routing graph
    '''
    G = load_graph(key, local=False)
    routing_report = {}
    for edge in G.edges:
        source_vpc = G.nodes[edge[0]]['VpcId']
        dest_vpc = G.nodes[edge[1]]['VpcId']
        source_vpc_data = G.nodes[G.nodes[edge[0]]['VpcId']]
        dest_vpc_data = G.nodes[G.nodes[edge[1]]['VpcId']]

        if source_vpc != dest_vpc:
            # add source vpc if not already in report
            if source_vpc not in routing_report:
                routing_report[source_vpc] = {
                    "Config": {
                        "Name": source_vpc_data['Name'],
                        "Account": source_vpc_data['Account'],
                        "AccountName": source_vpc_data['AccountName'],
                        "Region": source_vpc_data['Region'],
                    },
                    "Routes": {}}

            # add dest vpc if not already in report
            if dest_vpc not in routing_report:
                routing_report[dest_vpc] = {
                    "Config": {
                        "Name": dest_vpc_data['Name'],
                        "Account": dest_vpc_data['Account'],
                        "AccountName": dest_vpc_data['AccountName'],
                        "Region": dest_vpc_data['Region'],
                    },
                    "Routes": {}}

            # add dest vpc to source vpc if not already there
            if dest_vpc not in routing_report[source_vpc]['Routes']:
                routing_report[source_vpc]["Routes"][dest_vpc] = {
                    "Name": dest_vpc_data['Name'],
                    "Account": dest_vpc_data['Account'],
                    "AccountName": dest_vpc_data['AccountName'],
                    "Region": dest_vpc_data['Region'],
                }

            # add source vpc to dest vpc if not already there
            if source_vpc not in routing_report[dest_vpc]['Routes']:
                routing_report[dest_vpc]["Routes"][source_vpc] = {
                    "Name": source_vpc_data['Name'],
                    "Account": source_vpc_data['Account'],
                    "AccountName": source_vpc_data['AccountName'],
                    "Region": source_vpc_data['Region'],
                }

    # write report as json direclty to s3
    report_key = f"discovered/routing-report-{int(time.time())}.json"
    data = json.dumps(routing_report, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, report_key)
    return f"s3://{os.environ['CarveS3Bucket']}/{report_key}"


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
        print(f"graph provided, using provided graph: {G.graph['Name']}")
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
        return {'discovered': f"s3://{os.environ['CarveS3Bucket']}/{output_key}"}
    else:
        # if no s3 path provided, return the graph data with routes
        R.graph['Name'] = f"carve-routes-verified-{int(time.time())}"
        return json_graph.node_link_data(R)


if __name__ == '__main__':
    # routed_graph = verify_routing()
    # print(routed_graph['links'])
    
    import sys
    report = vpc_routing_report(f"discovered/last-routing-discovery.json")
    print(report)
