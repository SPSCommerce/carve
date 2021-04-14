import networkx as nx
from networkx.readwrite import json_graph
import pylab as plt
import json
import sys
import os
from c_aws import *
import urllib3
import concurrent.futures

# from c_disco import discovery
# from pprint import pprint



def execute_carve(event, context):
    # get all registered beacons from SSM
    print('running carve test')

    beacon_params = aws_ssm_get_parameters(f"/{os.environ['ResourcePrefix']}carve-resources/vpc-beacons/")

    print(f'beacon_params: {beacon_params}')

    beacons = []
    for k, v in beacon_params.items():
        addr = list(json.loads(v).keys())[0]
        beacons.append(addr)

    print(f'beacons: {beacons}')

    # create a list of all monitored VPCs for testing
    vpcs = []
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)
    print('loaded graph')
    for vpc in list(G.nodes):
        vpcs.append({
            'vpc': vpc,
            'account': G.nodes().data()[vpc]['Account'],
            'region': G.nodes().data()[vpc]['Region']})

    print(f'vpcs: {vpcs}')

    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        p = os.environ['ResourcePrefix']

        for vpc in list(G.nodes):
            a = G.nodes().data()[vpc]['Account']
            r = G.nodes().data()[vpc]['Region']
            futures.append(executor.submit(
                aws_invoke_lambda,
                arn=f"arn:aws:lambda:{r}:{a}:function:{p}carve-{vpc}",
                payload=beacons,
                region=r,
                credentials=None))

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    print(results)
    # process_test_results(results)


def process_test_results(results):
    pass
    # targets = []
    # for edge in list(G.edges(vpc)):
    #     for v in edge:
    #         if v != vpc:
    #             targets.append(str(v))

    # target_beacons = []
    # for target in targets:
    #     if target in beacons:
    #         target_beacons.append(beacons['target'])



def asg_event(message):

        print(f"TRIGGERED by ASG: {message['detail']['AutoScalingGroupName']}")

        # get insances from event data
        instances = []
        for resource in message['resources']:
            if resource.startswith("arn:aws:ec2"):
                instances.append(resource.split('/')[1])

        vpc = message['detail']['AutoScalingGroupName'].split(f"{os.environ['ResourcePrefix']}carve-beacon-asg-")[-1]
        credentials = aws_assume_role(carve_role_arn(message['account']), f"event-{message['detail']['AutoScalingGroupName']}")

        # get instance metadata from account and update SSM
        for ec2 in aws_describe_instances(instances, message['region'], credentials):

            parameter = f"/{os.environ['ResourcePrefix']}carve-resources/vpc-beacons/{vpc}/{ec2['InstanceId']}"

            if 'EC2 Instance Launch Successful' == message['detail-type']:
                print(f"adding beacon to ssm: {ec2['InstanceId']} - {ec2['PrivateIpAddress']} - {ec2['SubnetId']}")
                beacon = {ec2['PrivateIpAddress']: ec2['SubnetId']}
                aws_ssm_put_parameter(parameter, json.dumps(beacon))

            elif 'EC2 Instance Terminate Successful' == message['detail-type']:
                print(f"removing beacon from ssm: {parameter}")
                aws_ssm_delete_parameter(parameter)



def carve_role_arn(account):
    # return the carve IAM role ARN for any account number
    role_name = f"{os.environ['ResourcePrefix']}carve-lambda-{os.environ['OrganizationsId']}"
    role = f"arn:aws:iam::{account}:role/{role_name}"
    return role


# how do you want to orchestrate tests?
# maybe a StepFunction per lambda?
# could start step func by assume role from core
# step function sends back SNS?
# works cross account and region
# look at event bridge https://dashbird.io/blog/cutting-step-functions-costs-on-enterprise-scale-workflows/


# def run_test(G, c_context):
#     targets = []
#     for edge in list(G.edges):
#         # edge example:  ('vpc-id', 'vpc-id')
#         if c_context['VpcId'] in edge:
#             for v in edge:
#                 if v != c_context['VpcId']:
#                     targets.append(str(v))
#     # get values
#     for target in targets:
#         PrivateEndpoint = G.nodes[target]['PrivateEndpoint']
#         ApiGatewayUrl = G.nodes[target]['ApiGatewayUrl']
#         # do some cool shit
    
#     print(targets)


def network_diff(A, B):
    # compare peering both directions
    diff_peering(A, B)
    diff_vpcs(A, B)


def diff_peering(A, B, repeat=True):
    for edge in A.edges() - B.edges():
        print(f"DIFFERENCE DETECTED! \'{B.graph['Name']}\' contains a PEERING CONNECTION that \'{A.graph['Name']}\' does not:")
        print(f"#######################")
        print(A.nodes().data()[edge[0]])
        print(f"-------peered to-------")
        print(A.nodes().data()[edge[1]])
        print(f"#######################")
    if repeat:
        diff_peering(B, A, repeat=False)


def diff_vpcs(A, B, repeat=True):
    for node in A.nodes() - B.nodes():
        print(f"DIFF DETECTED! \'{B.graph['Name']}\' contains a VPC that \'{A.graph['Name']}\' does not:")
        print(f"#######################")
        print(A.nodes().data()[node])
        print(f"#######################")
    if repeat:
        diff_peering(B, A, repeat=False)



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



def load_graph(graph, local=True):
    try:
        if local:
            with open(graph) as f:
                G = json_graph.node_link_graph(json.load(f))
                G.graph['Name'] = graph.split('/')[-1].split('.')[0]
                return G
        else:
            graph_data = aws_read_s3_direct(graph, current_region)
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
    

def main(c_context):


    # either load graph data for G from json, or generate dynamically
    if 'json_graph' in c_context:
        G = load_graph(c_context['json_graph'])
    else:
        G = False

    if not G:
        G = discovery(c_context)

    if 'export_visual' in c_context:
        if c_context['export_visual'] == 'true':
            export_visual(G, c_context)

    if 'diff_graph' in c_context:
        D = load_graph(c_context['diff_graph'])
        if D:
            network_diff(G, D)
        else:
            print(f'cannot compare: diff_graph did not load')

    draw_vpc(G, c_context['VpcId'])




