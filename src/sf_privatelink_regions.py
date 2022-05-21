import lambdavars
import json
import os
from copy import deepcopy
from carve import load_graph, get_deploy_key,  unique_node_values
from sf_privatelink import private_link_deployment, privatelink_template
from aws import *
import time

    

def lambda_handler(event, context):
    ''' build CFN templates for a carve private link deployment '''

    if 'graph' in event:
        G = load_graph(event['graph'], local=False)
        print(f"successfully loaded graph {event['graph']} named: {G.graph['name']}")
    else:
        raise Exception('no graph provided in input')
    
    # get all regions and AZids in use in the carve deployment
    deploy_regions = sorted(unique_node_values(G, 'Region'))
    print(f"additional regions in use: {len(deploy_regions)-1}")
    deploy_azids = sorted(unique_node_values(G, 'AvailabilityZoneId'))
    print(f"availability zone ids in use: {deploy_azids}")
    deploy_accounts = sorted(unique_node_values(G, 'Account'))
    print(f"accounts in use: {deploy_accounts}")

    # remove the current region since that was already deployed
    deploy_regions.remove(current_region)

    deploy_regions = ['us-east-2']
    print('testing with only us-east-2 region!')

    # get all azid's in use by region
    private_link_subnets = {}
    i = 0
    for region in deploy_regions:
        private_link_subnets[region] = {}
        # get the AZ id to AZ name mapping for this account
        azs = aws_describe_availability_zones(region)['AvailabilityZones']
        # map the AZ names that are in the deployment in this region to the AZ id
        for az in azs:
            if az['ZoneId'] in deploy_azids:
                private_link_subnets[region][az['ZoneName']] = az['ZoneId']
                i += 1

    print(f"total azids in use across {len()} regions: {i}")

    # build the privatelink CFN templates for each region with the correct azids and upload to s3
    deployments = {}
    second_octet = 1
    for region, azmap in sorted(private_link_subnets.items()):
        template = privatelink_template(region, second_octet, deploy_accounts, azmap)
        key = f"managed_deployment/private-link-{region}.cfn.json"
        data = json.dumps(template, ensure_ascii=True, indent=2, sort_keys=True)
        aws_put_direct(data, key)
        deployments[region] = key
        second_octet += 1
        print(f"successfully uploaded privatelink template to s3: {key}")

    # deploy the private link CFN templates using the deploy stacks step function
    deploy_stacks = private_link_deployment(deployments, aws_current_account(), deploy_regions)

    return json.dumps(deploy_stacks, default=str)



if __name__ == '__main__':
    event = {'graph': 'discovered/carve-discovered-1652883036.json'}
    lambda_handler(event, None)
    pass