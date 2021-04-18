import networkx as nx
from networkx.readwrite import json_graph
import pylab as plt
import json
import sys
import os
from c_aws import *
import urllib3
import concurrent.futures



def carve_results(event, context):
    # call subnet lambdas to collect their results from their endpoints

    # get all registered beacons from SSM
    print('getting latest test results')

    # get a list of subnets, accounts, regions, and beacons
    subnets = get_subnet_beacons()

    # use threading for speed, get all beacon reports
    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        p = os.environ['ResourcePrefix']

        for subnet in subnets:

            futures.append(executor.submit(
                aws_invoke_lambda,
                arn=f"arn:aws:lambda:{subnet['region']}:{subnet['account']}:function:{p}carve-{subnet['subnet']}",
                payload={
                    'action': 'results'
                    'beacon': subnet['beacon']
                    },
                region=subnet['region'],
                credentials=None))

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    print(results)
    # process_test_results(results)


### when should I update beacon lists?
### stack updates using the step functions could be expensive if frequent
### should have a method to handle asg messages after deployment
### should have a flag to ignore asg messages if rolling ASGs
### Don't need any security for inbound TCP since it's 1:1 SG from lambda to beacon
###    - push updates to EC2 thru tcp socket instead
###    - https://realpython.com/python-sockets/
###    - port: 8080


def get_subnet_beacons():
    # create a list of all monitored subnets running testing
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    subnet_beacons = aws_read_s3_direct('managed_deployment/subnet-beacons.json', current_region)

    subnets = []
    for vpc in list(G.nodes):
        for subnet in G.nodes().data()[vpc]['Subnets']:
            # only get results if there is an active beacon in the subnet
            if subnet['SubnetId'] in subnet_beacons:
                subnets.append({
                    'subnet': subnet['SubnetId'],
                    'beacon': subnet_beacons[subnet['SubnetId']]
                    'account': G.nodes().data()[vpc]['Account'],
                    'region': G.nodes().data()[vpc]['Region']
                    })
            else:
                # this conditon needs to be handled if there is no beacon
                pass
    return subnets


def update_carve_beacons():
    ''' 
        discover all beacon IP address 
        add the beacons to the carve-config cloudformation snippet
        push the snipped to regional s3 buckets to be used as a cloudformation include
    '''

    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    # determine all deployed ASGs
    asgs = []
    regions = set()
    for vpc in list(G.nodes):
        a = G.nodes().data()[vpc]['Account']
        r = G.nodes().data()[vpc]['Region']
        regions.add(r)
        asgs.append({
            'asg': f"{os.environ['ResourcePrefix']}carve-beacon-asg-{vpc}",
            'account': a,
            'region': r
            })

    # using threading, look up the IP address of all beacons in all ASGs
    subnet_beacons = {}
    all_beacons = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for asg in asgs:
            futures.append(executor.submit(
                get_beacons_thread,
                asg=asg['asg'],
                account=asg['account'],
                region=asg['region']))

        for future in concurrent.futures.as_completed(futures):
            subnet_beacons.update(future)
            for subnet, beacon in future.items():
                all_beacons.append(beacon)

    # push subnet beacons data to S3
    data = json.dumps(subnet_beacons, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, 'managed_deployment/subnet-beacons.json')

    # # create an updated config file with all the beacons
    # config_path = "managed_deployment/carve-config.json"

    # with open(config_path) as f:
    #     config = json.load(f)

    # config['/root/carve.cfg']['content'] = '\n'.join(beacons)

    # # push carve config file to S3
    # data = json.dumps(config, ensure_ascii=True, indent=2, sort_keys=True)
    # aws_put_direct(data, config_path)

    # get a list of subnets, accounts, regions, and beacons
    subnets = get_subnet_beacons()

    # use threading to update all beacons with new beacon lists
    results = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        p = os.environ['ResourcePrefix']

        for subnet in subnets:

            futures.append(executor.submit(
                aws_invoke_lambda,
                arn=f"arn:aws:lambda:{subnet['region']}:{subnet['account']}:function:{p}carve-{subnet['subnet']}",
                payload={
                    'action': 'update'
                    'beacon': subnet_beacons[subnet['subnet']],
                    'beacons': ','.join(beacons)
                    },
                region=subnet['region'],
                credentials=None))

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    print(results)

    # # copy config file to all required regions for CloudFormation includes
    # prefix = os.environ['ResourcePrefix']
    # org = os.environ['OrganizationsId']
    # for r in regions:
    #     aws_copy_s3_object(
    #         key=config_path,
    #         target_key=config_path,
    #         source_bucket=os.environ['CarveS3Bucket'],
    #         target_bucket=f"{prefix}carve-managed-bucket-{org}-{r}")

    # # update all VPC stacks
    # deploy_key = get_deploy_key(last=True)

    # if deploy_key is not None:
    #     start_carve_deployment(event, context, key=deploy_key)
    # else:
    #     print('No previous deploy key to run updates with')


def get_beacons_thread(asg, account, region):
    # threaded lookup of all beacon IP addresses in an ASG
    credentials = aws_assume_role(carve_role_arn(a), f"lookup-{asg}")
    instance_ids = aws_asg_instances(asg, r, credentials)
    instances = aws_describe_instances(instance_ids, r, credentials)

    beacons = {}
    for instance in instances:
        beacons[instance['SubnetId']] = instance['PrivateIpAddress']

    return beacons

def update_beacons_thread(arn, beacon, beacons):
    # threaded lookup of all beacon IP addresses in an ASG
    credentials = aws_assume_role(carve_role_arn(a), f"lookup-{asg}")
    instance_ids = aws_asg_instances(asg, r, credentials)
    instances = aws_describe_instances(instance_ids, r, credentials)

    beacons = {}
    for instance in instances:
        beacons[instance['SubnetId']] = instance['PrivateIpAddress']

    return beacons


def process_test_results(results):
    pass


def asg_event(message):

    print(f"TRIGGERED by ASG: {message['detail']['AutoScalingGroupName']}")

    # get insances from event data
    instance_id = ""
    for resource in message['resources']:
        if resource.startswith("arn:aws:ec2"):
            instance_id = resource.split('/')[1]

    vpc = message['detail']['AutoScalingGroupName'].split(f"{os.environ['ResourcePrefix']}carve-beacon-asg-")[-1]
    credentials = aws_assume_role(carve_role_arn(message['account']), f"event-{message['detail']['AutoScalingGroupName']}")

    # get instance metadata from account and update SSM
    ec2 = aws_describe_instances([instance_id], message['region'], credentials)[0]

    parameter = f"/{os.environ['ResourcePrefix']}carve-resources/vpc-beacons/{vpc}/{ec2['InstanceId']}"

    if 'EC2 Instance Launch Successful' == message['detail-type']:

        # add to SSM
        print(f"adding beacon to ssm: {instance_id} - {ec2['PrivateIpAddress']} - {ec2['SubnetId']}")
        beacon = {ec2['PrivateIpAddress']: ec2['SubnetId']}
        aws_ssm_put_parameter(parameter, json.dumps(beacon))

        # add azid code to end of instance name
        subnet = aws_describe_subnets(message['region'], credentials, message['account'], ec2['SubnetId'])[0]
        az = subnet['AvailabilityZoneId'].split('-')[-1]
        name = f"{os.environ['ResourcePrefix']}carve-beacon-{vpc}-{az}"
        aws_rename_instance(ec2['InstanceId'], name, message['region'], credentials)

    elif 'EC2 Instance Terminate Successful' == message['detail-type']:

        # remove from SSM
        print(f"removing beacon from ssm: {parameter}")
        aws_ssm_delete_parameter(parameter)


def carve_role_arn(account):
    # return the carve IAM role ARN for any account number
    role_name = f"{os.environ['ResourcePrefix']}carve-lambda-{os.environ['OrganizationsId']}"
    role = f"arn:aws:iam::{account}:role/{role_name}"
    return role


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




