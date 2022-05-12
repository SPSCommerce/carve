import networkx as nx
from networkx.readwrite import json_graph
import pylab as plt
import json
import sys
import os
from aws import *
import concurrent.futures
import time


def carve_results():
    # call subnet lambdas to collect their results from their beacons

    # get all registered beacons from SSM
    print('getting latest test results')

    # get a list of subnets, accounts, regions, and beacons
    subnets = get_subnet_beacons()

    # use threading for speed, get all beacon reports
    results = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        p = os.environ['Prefix']

        for beacon, data in subnets.items():
            print(f"getting results from {beacon}")
            payload = {
                    'action': 'results',
                    'beacon': beacon
                    }
            futures.append(executor.submit(
                aws_invoke_lambda,
                arn=f"arn:aws:lambda:{data['region']}:{data['account']}:function:{p}carve-{data['subnet']}",
                payload=payload,
                region=data['region'],
                credentials=None))

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            print(result)
            try:
                results[result['subnet']] = {
                    'beacon': result['beacon'],
                    'status': result['status'],
                    'fping': result['fping'],
                    'health': result['health'],
                    'ts': result['ts']
                    }
            except Exception as e:
                print(f"error processing beacon result: {e}")

    # push subnet beacons data to S3
    log = json.dumps(results, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(log, f"logs/verification-{int(time.time())}")

    return results



# def process_test_results(results):
#     # determine verification beacons here
#     G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

#     subnet_beacons = get_subnet_beacons()

#     verify_beacons = []
#     for edge in G.edges:
#         if vpc not in edge:
#             G.remove_edge(edge[0], edge[1])


def get_carve_asgs(G=None):
    ''' gets the ARNs for all carve deployed ASGs in G '''
    if G is None:
        G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    # build a dict of all carve ASGs with their subnets (carve uses one ASG per VPC)
    asgs = {}
    for subnet in list(G.nodes):
        asgname = f"{os.environ['Prefix']}carve-beacon-asg-{G.nodes().data()[subnet]['VpcId']}"
        if G.nodes().data()[subnet]['VpcId'] not in asgs:
            asgs[asgname] = {
               'account': G.nodes().data()[subnet]['Account'],
               'region': G.nodes().data()[subnet]['Region'],
               'subnets': [subnet]
            }          
        else:
            asgname = f"{os.environ['Prefix']}carve-beacon-asg-{G.nodes().data()[subnet]['VpcId']}"
            asgs[asgname]['subnets'].append(subnet)

    # convert to list of dicts
    asgs_list = []
    for k, v in asgs.items():
        asg = {'name': k, 'account': v['account'], 'region': v['region'], 'subnets': len(v['subnets'])}
        asgs_list.append(asg)

    return asgs_list


def get_subnet_beacons():
    # return dict containing all subnets with their beacon ip, account, and region

    # load latest graph
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    subnet_beacons = json.loads(aws_read_s3_direct('managed_deployment/subnet-beacons.json', current_region))

    subnets = {}
    # for vpc in list(G.nodes):
    for subnet, data in G.nodes().data():
        # only get results if there is an active beacon in the subnet
        if subnet in subnet_beacons:
            subnets[subnet_beacons[subnet]] = {
                'subnet': subnet,
                'account': data['Account'],
                'region': data['Region']
                }
        else:
            # this conditon needs to be handled if there is no beacon
            pass

    return subnets


def update_beacon_inventory():
    ''' 
        1. discovers all beacon IP address 
        2. updates the beacon inventory file on s3
        3. returns a list of all beacon IPs: ['0.0.0.0', '0.0.0.1'...]
    '''

    print('updating carve beacons list')
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    asgs = get_carve_asgs() # list of dicts

    subnet_beacons = {}
    all_beacons = []

    # threaded look up the IP address of all beacons in all ASGs
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for asg in asgs:
            futures.append(executor.submit(
                get_beacons_thread,
                asg=asg['name'],
                account=asg['account'],
                region=asg['region']
                ))

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            subnet_beacons.update(result)
    
    # push subnet beacons data to S3
    data = json.dumps(subnet_beacons, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, 'managed_deployment/subnet-beacons.json')

    all_beacons = []
    for subnet, beacon in subnet_beacons.items():
        all_beacons.append(beacon)

    return all_beacons


def get_beacons_thread(asg, account, region):
    # threaded lookup of all beacon IP addresses in an ASG
    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{asg}")
    instance_ids = []
    asg_info = aws_describe_asg(asg, region, credentials)

    for asg in asg_info['AutoScalingGroups']:
        for instance in asg['Instances']:
            if instance['LifecycleState'] == "InService":
                instance_ids.append(instance['InstanceId'])

    instances = aws_describe_instances(instance_ids, region, credentials)

    beacons = {}
    for instance in instances:
        beacons[instance['SubnetId']] = instance['PrivateIpAddress']

    return beacons


def update_beacon_list(all_beacons):
    ##
    ##
    ## THIS FEELS LIKE IT could BE STEP FUNCTION MAP TASK INSTEAD OF THREADED LAMBDA
    ##  REFACTOR
    ##

    # get a dict of beacons with subnets, accounts, and regions
    subnet_beacons = get_subnet_beacons()

    # use threading to update all beacons with new beacon lists
    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        p = os.environ['Prefix']

        for beacon, data in subnet_beacons.items():
            futures.append(executor.submit(
                aws_invoke_lambda,
                arn=f"arn:aws:lambda:{data['region']}:{data['account']}:function:{p}carve-{data['subnet']}",
                payload={
                    'action': 'update',
                    'beacon': beacon,
                    'beacons': ','.join(all_beacons)
                    },
                region=data['region'],
                credentials=None))

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())



def update_carve_beacons():
    # This will re-run the last execution of the scaling step function
    # Doing this will update the beacons with the latest beacon list
    executions = aws_states_list_executions(arn=os.environ['ScaleStateMachine'], results=100)
    last_exec = aws_states_describe_execution(executions[0])
    scale = json.loads(last_exec['input'])['scale']
    name = f"scale-{scale}-{int(time.time())}"
    aws_start_stepfunction(os.environ['ScaleStateMachine'], last_exec['input'], name)



def asg_event(event):
    return

    # should only be one item, but treat as a list
    for record in event['Records']:
        message = json.loads(record['Sns']['Message'])

        print(f"TRIGGERED by ASG: {message['detail']['AutoScalingGroupName']}")

        # get insances from event data
        instance_id = ""
        for resource in message['resources']:
            if resource.startswith("arn:aws:ec2"):
                instance_id = resource.split('/')[1]

        vpc = message['detail']['AutoScalingGroupName'].split(f"{os.environ['Prefix']}carve-beacon-asg-")[-1]
        credentials = aws_assume_role(carve_role_arn(message['account']), f"event-{message['detail']['AutoScalingGroupName']}")

        # get instance metadata from account and update SSM
        ec2 = aws_describe_instances([instance_id], message['region'], credentials)[0]
        # print(ec2)

        # parameter = f"/{os.environ['Prefix']}carve-resources/vpc-beacons/{vpc}/{ec2['InstanceId']}"

        if 'EC2 Instance Launch Successful' == message['detail-type']:

            # # add to SSM
            # print(f"adding beacon to ssm: {instance_id} - {ec2['PrivateIpAddress']} - {ec2['SubnetId']}")
            # beacon = {ec2['PrivateIpAddress']: ec2['SubnetId']}
            # aws_ssm_put_parameter(parameter, json.dumps(beacon))


            ### need to update this code to grab subnet ssm param instead of ASG

            # append azid code to end of instance name
            subnet = aws_describe_subnets(message['region'], credentials, message['account'], ec2['SubnetId'])[0]
            az = subnet['AvailabilityZoneId'].split('-')[-1]
            name = f"{os.environ['Prefix']}carve-beacon-{ec2['SubnetId']}-{az}"
            tags = [{'Key': 'Name', 'Value': name}]
            aws_create_ec2_tag(ec2['InstanceId'], tags, message['region'], credentials)

            function = f"arn:aws:lambda:{message['region']}:{message['account']}:function:{os.environ['Prefix']}carve-{ec2['SubnetId']}"
            beacon = ec2['PrivateIpAddress']

            ## will need to udate SSM logic for tokens to be 1 token per subnet that will come back up?
            ## or do we check the whole ASG for health?

            i = 0
            while True:
                result = beacon_results(function, beacon)
                print(result)
                if result['health'] == 'up':
                    # ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{asg}",
                    ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{ec2['SubnetId']}"
                    token = aws_ssm_get_parameter(ssm_param)
                    aws_ssm_delete_parameter(ssm_param)
                    if token is not None:
                        aws_send_task_success(token, {"action": "scale", "result": "success"})
                    else:
                        print(f"taskToken was None for {ec2['SubnetId']}")
                    break
                else:
                    if i > 30:
                        break
                        print(f'timed out waiting for beacon {beacon}')
                    else:
                        print(f'waiting for beacon {beacon} - {i}')
                        i = i + 1
                        time.sleep(1)

        elif 'EC2 Instance Terminate Successful' == message['detail-type']:
            # ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{asg}",
            subnet = message['detail']['Details']['Subnet ID']
            ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{subnet}"
            token = aws_ssm_get_parameter(ssm_param)
            aws_ssm_delete_parameter(ssm_param)
            if token is not None:
                aws_send_task_success(token, {"action": "scale", "result": "success"})
            else:
                print(f'taskToken was None for {subnet}')
            print(f"beacon terminated {message}")


def beacon_results(function, beacon):
    region = function.split(':')[3]
    subnet = function.split(':')[-1]
    print(f"getting beacon results from {subnet}")
    payload = {
            'action': 'results',
            'beacon': beacon
            }
    result = aws_invoke_lambda(
        arn=function,
        payload=payload,
        region=region,
        credentials=None
        )
    return result


def carve_role_arn(account):
    # return the carve IAM role ARN for any account number
    # role_name = f"{os.environ['Prefix']}carve-org-role"
    role = f"arn:aws:iam::{account}:role/{os.environ['OrgRoleName']}"
    # role = f"arn:aws:iam::{account}:role/{role_name}"
    return role


def network_diff(A, B):
    # compare peering both directions
    diff_peering(A, B)
    diff_vpcs(A, B)


def diff_peering(A, B, repeat=True):
    for edge in A.edges() - B.edges():
        print(f"DIFFERENCE DETECTED! \'{B.graph['Name']}\' contains a CONNECTION that \'{A.graph['Name']}\' does not:")
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



    

# def main(c_context):


#     # either load graph data for G from json, or generate dynamically
#     if 'json_graph' in c_context:
#         G = load_graph(c_context['json_graph'])
#     else:
#         G = False

#     if not G:
#         G = discovery(c_context)

#     if 'export_visual' in c_context:
#         if c_context['export_visual'] == 'true':
#             export_visual(G, c_context)

#     if 'diff_graph' in c_context:
#         D = load_graph(c_context['diff_graph'])
#         if D:
#             network_diff(G, D)
#         else:
#             print(f'cannot compare: diff_graph did not load')

#     draw_vpc(G, c_context['VpcId'])




