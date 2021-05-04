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
    # call subnet lambdas to collect their results from their beacons

    # get all registered beacons from SSM
    print('getting latest test results')

    # get a list of subnets, accounts, regions, and beacons
    subnets = get_subnet_beacons()

    # use threading for speed, get all beacon reports
    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        p = os.environ['Prefix']

        for subnet in subnets:
            print(f"getting results from {subnet['beacon']}")
            payload = {
                    'action': 'results',
                    'beacon': subnet['beacon']
                    }
            futures.append(executor.submit(
                aws_invoke_lambda,
                arn=f"arn:aws:lambda:{subnet['region']}:{subnet['account']}:function:{p}carve-{subnet['subnet']}",
                payload=payload,
                region=subnet['region'],
                credentials=None))

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    print(results)
    # process_test_results(results)



def process_test_results(results):
    # determine verification beacons here
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    subnet_beacons = json.loads(aws_read_s3_direct('managed_deployment/subnet-beacons.json', current_region))

    verify_beacons = []
    for edge in G.edges:
        if vpc not in edge:
            G.remove_edge(edge[0], edge[1])




# def get_asgs(G=None):
#     if G is None:
#         G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

#     # determine all deployed ASGs
#     asgs = {}
#     for subnet in list(G.nodes):
#         asg = f"{os.environ['Prefix']}carve-beacon-asg-{G.nodes().data()[subnet]['VpcId']}"
#         if asg not in asgs:
#             asgs[asg] = {
#                 'account': G.nodes().data()[subnet]['Account'],
#                 'region': G.nodes().data()[subnet]['Region'],
#                 }

#     for asg, values in asgs.items():


#     return asgs


def scale_beacons(scale):
    ''' 
        discover all beacon IP address 
        add the beacons to the carve-config cloudformation snippet
        push the snipped to regional s3 buckets to be used as a cloudformation include
    '''

    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    # determine VPCs and regions
    vpcs = {}
    for subnet in list(G.nodes):
        a = G.nodes().data()[subnet]['Account']
        r = G.nodes().data()[subnet]['Region']
        vpcs[G.nodes().data()[subnet]['VpcId']] = (a, r)

    asgs = []
    for vpc, ar in vpcs.items():
        vpc_subnets = [x for x,y in G.nodes(data=True) if y['VpcId'] == vpc]
        asgs.append({
            'asg': f"{os.environ['Prefix']}carve-beacon-asg-{vpc}",
            'account': ar[0],
            'region': ar[1],
            'subnets': vpc_subnets
            })

    # using threading, set all ASGs to correct scale for all beacons
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for asg in asgs:

            if scale == 'none':
                desired = 0
            elif scale == 'subnet':
                desired = len(asg['subnets'])
            elif scale == 'vpc':
                desired = 1

            futures.append(executor.submit(
                update_asg_size,
                account=asg['account'],
                asg=asg['asg'],
                minsize=0, 
                maxsize=len(asg['subnets']),
                desired=desired,
                region=asg['region']
                ))
            

        for future in concurrent.futures.as_completed(futures):
            result = future.result()


def update_asg_size(account, asg, minsize, maxsize,  desired, region):
    credentials=aws_assume_role(carve_role_arn(account), f"lookup-{asg}")
    asg_info = aws_describe_asg(asg, region, credentials)

    # only update ASG if min/max/desired is different
    update = False
    if int(asg_info['MinSize']) != int(minsize):
        update = True
    elif int(asg_info['MaxSize']) != int(maxsize):
        update = True
    elif int(asg_info['DesiredCapacity']) != int(desired):
        update = True
    
    if update:
        aws_update_asg_size(asg, minsize, maxsize, desired, region, credentials)

    else:
        # if no udpates, return success for the task tokens
        subnets = asg_info['VPCZoneIdentifier'].split(',')
        for subnet in subnets:
            ssm_param = f"/{os.environ['Prefix']}carve-resources/tokens/{subnet}"
            token = aws_ssm_get_parameter(ssm_param)
            aws_ssm_delete_parameter(ssm_param)
            if token is not None:
                aws_send_task_success(token, {"status": "200"})
            else:
                print(f'taskToken was None for {subnet}')


def get_subnet_beacons():
    # create a list of all subnets and their beacon, account, and region

    # load latest graph
    G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    subnet_beacons = json.loads(aws_read_s3_direct('managed_deployment/subnet-beacons.json', current_region))

    subnets = []
    for vpc in list(G.nodes):
        for subnet in G.nodes().data()[vpc]['Subnets']:
            # only get results if there is an active beacon in the subnet
            if subnet['SubnetId'] in subnet_beacons:
                subnets.append({
                    'subnet': subnet['SubnetId'],
                    'beacon': subnet_beacons[subnet['SubnetId']],
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
    asgs = {}
    for subnet in list(G.nodes):
        asg = f"{os.environ['Prefix']}carve-beacon-asg-{G.nodes().data()[subnet]['VpcId']}"
        if asg not in asgs:
            asgs[asg] = {
                'account': G.nodes().data()[subnet]['Account'],
                'region': G.nodes().data()[subnet]['Region']
                }

    # threaded look up the IP address of all beacons in all ASGs
    subnet_beacons = {}
    all_beacons = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for asg, v in asgs:
            futures.append(executor.submit(
                get_beacons_thread, asg=asg, account=v['account'], region=v['region']))

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            subnet_beacons.update(result)
            for subnet, beacon in result.items():
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
        p = os.environ['Prefix']

        for subnet in subnets:

            futures.append(executor.submit(
                aws_invoke_lambda,
                arn=f"arn:aws:lambda:{subnet['region']}:{subnet['account']}:function:{p}carve-{subnet['subnet']}",
                payload={
                    'action': 'update',
                    'beacon': subnet_beacons[subnet['subnet']],
                    'beacons': ','.join(all_beacons)
                    },
                region=subnet['region'],
                credentials=None))

        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    print(results)

    # # copy config file to all required regions for CloudFormation includes
    # prefix = os.environ['Prefix']
    # org = os.environ['OrgId']
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
    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{asg}")
    instance_ids = []
    asg_info = aws_describe_asg(asg, region, credentials)
    for instance in asg_info['Instances']:
        if instance['LifecycleState'] == "InService":
            instance_ids.append(instance['InstanceId'])

    instances = aws_describe_instances(instance_ids, region, credentials)

    beacons = {}
    for instance in instances:
        beacons[instance['SubnetId']] = instance['PrivateIpAddress']

    return beacons


def ssm_event(event, context):
    ssm_param = event['detail']['name']
    ssm_value = aws_ssm_get_parameter(ssm_param)

    if ssm_param.split('/')[-1] == 'scale':
        G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

        payload = []
        for subnet in list(G.nodes):
            payload.append({
                'parameter': f"/{os.environ['Prefix']}carve-resources/tokens/{subnet}",
                # 'asg': subnet['asg'],
                'task': 'scale',
                'scale': ssm_value
                })

        name = f"scale-{ssm_value}-{int(time.time())}"
        aws_start_stepfunction(os.environ['TokenStateMachine'], payload, name)
        scale_beacons(ssm_value)


def cleanup_ssm():
    # make function to clean up SSM tokens
    # move function to cleanup workflow
    pass

def asg_event(event):

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
        print(ec2)

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
            name = f"{os.environ['Prefix']}carve-beacon-{vpc}-{az}"
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
                        aws_send_task_success(token, {"status": "200"})
                    else:
                        print('taskToken was None')
                    break
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
            aws_send_task_success(token, {"status": "200"})
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
    role_name = f"{os.environ['Prefix']}carve-core"
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




