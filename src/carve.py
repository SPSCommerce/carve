from telnetlib import GA
from aws import aws_invoke_lambda, current_region
import os
import networkx as nx
from networkx.readwrite import json_graph
import json
from utils import load_graph, get_deploy_key

def lambda_handler(event, context):
    '''
    respond to cloudwatch events and execute carve verifications
    '''


    if 'detail-type' in event:

        if event['source'] == 'aws.events':
            cw_rule = event['resources'][0].split('rule/')[-1]
            if cw_rule == f"{os.environ['Prefix']}carve-results":
                result = carve_results(event, context)


def carve_results(event, context):
    '''
    respond to cloudwatch events and execute carve verifications
    '''
    current_account = context.invoked_function_arn.split(':')[4]
    lambda_arn = f"arn:aws:lambda:{current_region}:{current_account}:function:{os.environ['Prefix']}carve-verify_routing"
    payload = {}
    result = aws_invoke_lambda(lambda_arn, payload)
    print(result)

    V = json_graph.node_link_graph(json.loads(result))

    deploy_key = get_deploy_key()
    if not deploy_key:
        raise Exception('No graph provided or found')
    else:
        G = load_graph(deploy_key, local=False)

    network_diff(V, G)

    # return the result
    return result


def network_diff(A, B):
    diff_links(A, B)
    diff_nodes(A, B)


def diff_links(A, B, repeat=True):
    for edge in A.edges() - B.edges():
        print(f"DIFFERENCE DETECTED! \'{B.graph['Name']}\' contains a CONNECTION that \'{A.graph['Name']}\' does not:")
        print(f"#######################")
        print(A.nodes().data()[edge[0]])
        print(f"-------routes to-------")
        print(A.nodes().data()[edge[1]])
        print(f"#######################")
    if repeat:
        diff_links(B, A, repeat=False)


def diff_nodes(A, B, repeat=True):
    for node in A.nodes() - B.nodes():
        print(f"DIFF DETECTED! \'{B.graph['Name']}\' contains a VPC that \'{A.graph['Name']}\' does not:")
        print(f"#######################")
        print(A.nodes().data()[node])
        print(f"#######################")
    if repeat:
        diff_nodes(B, A, repeat=False)