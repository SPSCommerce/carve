import lambdavars

import json
import os
import time

from aws import *
from carve import get_deploy_key, load_graph, unique_node_values
from sf_privatelink import (add_peer_routes, private_link_deployment,
                            privatelink_template)


def update_peer_names(deploy_regions):
    routing = False
    stackname = f"{os.environ['Prefix']}carve-managed-privatelink"
    for region in deploy_regions:
        stack = aws_describe_stack(stackname, region)
        if stack is not None:
            for output in stack['Outputs']:
                if output['OutputKey'] == 'VpcPeeringConnectionId':
                    routing = True
                    aws_update_tags(
                        resource=output['OutputValue'],
                        tags = [
                            {
                                "Key": "Name",
                                "Value": f"{os.environ['Prefix']}carve-privatelink-{region}"
                            }])
    return routing


def private_link_template(azmap, deploy_accounts, deploy_regions, routing=False):
    ''' create private link templates for each region/az '''

    templates = {}
    second_octet = 0
    template = privatelink_template(second_octet, deploy_accounts, azmap)

    if routing:
        routing_template = add_peer_routes(template, deploy_regions)
        template = routing_template

    key = f"managed_deployment/private-link-{current_region}.cfn.json"
    data = json.dumps(template, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, key)

    templates[current_region] = key

    return templates


def lambda_handler(event, context):
    ''' build CFN templates for a carve private link deployment '''

    if 'graph' in event:
        G = load_graph(event['graph'], local=False)
    else:
        G = load_graph(get_deploy_key(), local=False)
    
    # get all regions and AZids in use in the carve deployment
    deploy_regions = sorted(unique_node_values(G, 'Region'))
    deploy_azids = sorted(unique_node_values(G, 'AvailabilityZoneId'))
    deploy_accounts = sorted(unique_node_values(G, 'Account'))

    peer_regions =[]
    for region in deploy_regions:
        if region != current_region:
            peer_regions.append(region)


    deploy_regions = ['us-east-1', 'us-east-2']


    # update any carve peering connection names in the current region
    routing = update_peer_names(peer_regions)

    # get the AZ id to AZ name mapping for this account
    azs = aws_describe_availability_zones(current_region)['AvailabilityZones']

    # map the AZ names that are in the deployment in this region to the AZ id
    azmap = {}
    for az in azs:
        if az['ZoneId'] in deploy_azids:
            azmap[az['ZoneName']] = az['ZoneId']

    # build the private link CFN template for the current region/subnets
    templates = private_link_template(azmap, deploy_accounts, deploy_regions, routing=routing)

    # deploy the private link CFN template using the deploy stacks step function
    deployment = private_link_deployment(templates, aws_current_account(), deploy_regions, routing)
    
    return json.dumps(deployment, default=str)



if __name__ == '__main__':
    event = {'graph': 'discovered/carve-discovered-1652883036.json'}
    lambda_handler(event, None)
   
