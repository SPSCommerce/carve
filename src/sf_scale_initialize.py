import os
from aws import *
from carve import load_graph, carve_role_arn
import concurrent.futures

def get_carve_asgs(G=None):
    ''' gets the ARNs for all carve deployed ASGs in G '''
    if G is None:
        G = load_graph(aws_newest_s3('deployed_graph/'), local=False)

    # compile a list of all deployed ASG names, accounts, and regions
    asgs = []
    for subnet in list(G.nodes):
        name = f"{os.environ['Prefix']}carve-beacon-asg-{G.nodes().data()[subnet]['VpcId']}"
        asgs[name] = {
            'account': G.nodes().data()[subnet]['Account'],
            'region': G.nodes().data()[subnet]['Region'],
            }

    # lookup the ASG ARNs from the list of ASG names
    asg_arns = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for name, value in asgs.items():
            futures.append(executor.submit(
                threaded_asg_lookup, name=name, account=value['account'], region=value['region']))

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            try:
                asg_arns.append(result['AutoScalingGroups'][0]['AutoScalingGroupARN'])
            except:
                pass

    print(f"ASG arns: {asg_arns}")
    return asg_arns


def threaded_asg_lookup(name, account, region):
    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{name}")
    aws_describe_asg(name, region, credentials)


def lambda_handler(event, context):
    print(f"event: {event}")
    return get_carve_asgs()
