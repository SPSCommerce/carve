import networkx as nx
from networkx.readwrite import json_graph
import pylab as plt
import json
import sys
import os
from aws import *




# def process_test_results(results):
#     # determine verification beacons here
#     G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

#     subnet_beacons = get_subnet_beacons()

#     verify_beacons = []
#     for edge in G.edges:
#         if vpc not in edge:
#             G.remove_edge(edge[0], edge[1])



def export_visual(Graph, c_context):

    G = Graph

    # remove isolated nodes from graph
    if 'peers_only' in c_context:
        if c_context['peers_only'] == 'true':
            G.remove_nodes_from(list(nx.isolates(G)))

    print('drawing graph diagram')
    # print(f"/src/c_graphic_{G.graph['Name']}.png")

    options = {
        'node_color': 'blue',
        'node_size': 100,
        'font_size': 14,
        'width': 3,
        'with_labels': True,
    }

    plt.figure(G.graph['Name'],figsize=(24,24)) 

    nx.draw_circular(G, **options)

    # G = nx.cycle_graph(80)
    # pos = nx.circular_layout(G)

    # # default
    # plt.figure(1)
    # nx.draw(G,pos)

    # # smaller nodes and fonts
    # plt.figure(2)
    # nx.draw(G,pos,node_size=60,font_size=8) 

    # # larger figure size
    # plt.figure(3,figsize=(12,12)) 
    # nx.draw(G,pos)

    plt.savefig(f"/src/c_graphic_{G.graph['Name']}.png")



def draw_vpc(Graph, vpc):

    G = Graph

    print('drawing graph diagram')
    print(f"/src/c_graphic_{vpc}.png")

    # remove all edges without vpc
    for edge in G.edges:
        if vpc not in edge:
            G.remove_edge(edge[0], edge[1])

    # remove all nodes left without edges
    G.remove_nodes_from(list(nx.isolates(G)))


    options = {
        'node_color': 'blue',
        'node_size': 100,
        'font_size': 14,
        'width': 3,
        'with_labels': True,
    }

    plt.figure(vpc,figsize=(24,24)) 

    # nx.draw_circular(G, **options)
    # nx.draw_networkx(G, **options) # good for single
    # nx.draw_spectral(G, **options)
    # nx.draw_spring(G, **options) # similar to netoworkx also good
    nx.draw_shell(G, **options)

    plt.savefig(f"/src/c_graphic_{vpc}.png")

def carve_role_arn(account):
    # return the carve IAM role ARN for any account number
    # role_name = f"{os.environ['Prefix']}carve-org-role"
    role = f"arn:aws:iam::{account}:role/{os.environ['OrgRoleName']}"
    # role = f"arn:aws:iam::{account}:role/{role_name}"
    return role

def get_deploy_key(last=False):
    # get either the current or last deployment graph key from s3
    if last:
        path = 'deployed_graph/'
    else:
        path = 'deploy_active/'
    return aws_newest_s3(path)


def unique_node_values(G, key):
    # from graph G, get all unique values of key
    values = set()
    for node in list(G.nodes):
        try:
            values.add(G.nodes().data()[node][key])
        except:
            pass
    return values

def load_graph(graph, local=True):
    try:
        if local:
            with open(graph) as f:
                G = json_graph.node_link_graph(json.load(f))
                G.graph['Name'] = graph.split('/')[-1].split('.')[0]
                return G
        else:
            graph_data = aws_read_s3_direct(graph)
            G = json_graph.node_link_graph(json.loads(graph_data))
            return G
    except Exception as e:
        print(f'error opening json_graph {json_graph}: {e}')
        sys.exit()


def save_graph(G, file_path):
    # save json data
    try:
        os.remove(file_path)
    except:
        pass

    with open(file_path, 'a') as f:
        json.dump(json_graph.node_link_data(G), f)




