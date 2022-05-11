import os
from pprint import pp

import lambdavars

from aws import *
from carve import load_graph, carve_role_arn
import concurrent.futures

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

    # # lookup the ASG ARNs from the list of ASG names
    # asg_list = []
    # with concurrent.futures.ThreadPoolExecutor() as executor:
    #     futures = []
    #     for name, value in asgs.items():
    #         futures.append(executor.submit(
    #             threaded_asg_lookup,
    #             name=name,
    #             account=value['account'],
    #             region=value['region'],
    #             subnets=len(value['subnets'])
    #             ))

    #     for future in concurrent.futures.as_completed(futures):
    #         result = future.result()
    #         try:
    #             asg_list.append(result)
    #         except:
    #             pass

    # return asg_list


def threaded_asg_lookup(name, account, region, subnets):
    credentials = aws_assume_role(carve_role_arn(account), f"lookup-{name}")
    response = aws_describe_asg(name, region, credentials)
    arn = response['AutoScalingGroups'][0]['AutoScalingGroupARN']
    return {'arn': arn, 'subnets': subnets}


def lambda_handler(event, context):
    print(event)
    if 'scale' not in event['Input']:
        error = {'error': 'scale not specified in event'}
        print(error)
        return error
    asgs = get_carve_asgs()
    # print(f"Scaling ASGs: {asgs}")
    return {'asgs': asgs, 'scale': event['Input']['scale']}


if __name__ == "__main__":
    event = {"Input": {'scale': 'up'}}
    # event = {}
    result = lambda_handler(event, None)
    print(result)