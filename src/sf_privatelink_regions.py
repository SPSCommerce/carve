import lambdavars
import json
import os
from copy import deepcopy
from carve import load_graph, get_deploy_key,  unique_node_values
from sf_privatelink import private_link_deployment, privatelink_template
from aws import *
import time



def private_link_templates(private_link_subnets, deploy_accounts):
    ''' create private link templates for each region/az '''

    templates = {}
    second_octet = 1
    for region, azmap in sorted(private_link_subnets.items()):
        template = privatelink_template(second_octet, deploy_accounts, azmap)
        key = f"managed_deployment/private-link-{region}.cfn.json"
        data = json.dumps(template, ensure_ascii=True, indent=2, sort_keys=True)
        aws_put_direct(data, key)
        templates[region] = key
        second_octet += 1

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

    # remove the current region since that was already deployed
    deploy_regions.remove(current_region)


    deploy_regions = ['us-east-2']


    # get all azid's in use by region
    private_link_subnets = {}
    for region in deploy_regions:
        private_link_subnets[region] = {}
        # get the AZ id to AZ name mapping for this account
        azs = aws_describe_availability_zones(region)['AvailabilityZones']
        # map the AZ names that are in the deployment in this region to the AZ id
        for az in azs:
            if az['ZoneId'] in deploy_azids:
                private_link_subnets[region][az['ZoneName']] = az['ZoneId']

    # build the private link CFN templates for the regions/subnets
    templates = private_link_templates(private_link_subnets, deploy_accounts)

    # deploy the private link CFN templates using the deploy stacks step function
    deployment = private_link_deployment(templates, aws_current_account(), deploy_regions)

    return json.dumps(deployment, default=str)



if __name__ == '__main__':
    event = {'graph': 'discovered/carve-discovered-1652883036.json'}
    lambda_handler(event, None)
    pass