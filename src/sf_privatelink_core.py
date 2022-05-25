import lambdavars

import json
import os

from aws import *
from carve import load_graph, unique_node_values
from sf_privatelink import (add_peer_routes, private_link_deployment,
                            privatelink_template)


def update_peer_names(deploy_regions):
    routing = False
    stackname = f"{os.environ['Prefix']}carve-managed-privatelink"
    for region in deploy_regions:
        # stack = aws_describe_stack(stackname, region)
        outputs = aws_get_stack_outputs_dict(stackname, region)
        if 'VpcPeeringConnectionId' in outputs:
            routing = True
            aws_update_tags(
                resource=outputs['VpcPeeringConnectionId'],
                tags = [
                    {
                        "Key": "Name",
                        "Value": f"{os.environ['Prefix']}carve-privatelink-{region}"
                    }])
            print(f"updated the name on VPC peering connection id {outputs['VpcPeeringConnectionId']} in {region}")
    return routing


def lambda_handler(event, context):
    ''' build CFN templates for a carve private link deployment '''
    print(event)

    if 'graph' in event['Input']:
        G = load_graph(event['Input']['graph'], local=False)
        print(f"successfully loaded graph: {event['Input']['graph']}")
    elif 'graph' in event:
        G = load_graph(event['graph'], local=False)
        print(f"successfully loaded graph: {event['graph']}")
    else:
        raise Exception("no graph provided in input. input format: {'input': {'graph': 'carve-privatelink-graph.json'}}")
    
    # get all regions and AZids in use in the carve deployment
    deploy_regions = sorted(unique_node_values(G, 'Region'))
    print(f"additional regions in use: {len(deploy_regions)-1}")
    deploy_azids = sorted(unique_node_values(G, 'AvailabilityZoneId'))
    print(f"availability zone ids in use: {deploy_azids}")
    deploy_accounts = sorted(unique_node_values(G, 'Account'))
    print(f"accounts in use: {deploy_accounts}")

    peer_regions =[]
    for region in deploy_regions:
        if region != current_region:
            peer_regions.append(region)


    if 'mode' in event:
        if event['mode'] == 'test':
            deploy_regions = ['us-east-1', 'us-east-2']
            print(f"testing with only {len(deploy_regions)} regions: {deploy_regions}")


    # update any carve peering connection names in the current region
    routing = update_peer_names(peer_regions)
    print(f"routing found: {routing}")

    # get the AZ id to AZ name mapping for this account
    azs = aws_describe_availability_zones(current_region)['AvailabilityZones']

    # map the AZ names that are in the deployment in this region to the AZ id
    azmap = {}
    for az in azs:
        if az['ZoneId'] in deploy_azids:
            azmap[az['ZoneName']] = az['ZoneId']

    # build the private link CFN template for the current region/subnets
    second_octet = 0
    template = privatelink_template(current_region, second_octet, deploy_accounts, azmap)

    if routing:
        routing_template = add_peer_routes(template, deploy_regions)
        template = routing_template

    key = f"managed_deployment/private-link-{current_region}.cfn.json"
    data = json.dumps(template, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, key)
    print(f"successfully uploaded privatelink template to s3: {key}")

    deployments = {current_region: key}

    # deploy the private link CFN template using the deploy stacks step function
    deploy_stacks = private_link_deployment(deployments, aws_current_account(), deploy_regions, routing)
    
    return json.dumps(deploy_stacks, default=str)



if __name__ == '__main__':
    # event = {"Input": {"graph": "discovered/carve-discovered-1652883036.json"}, "mode": "test"}
    event = {"Input": {"graph": "deploy_active/carve-test-pl-subnets.json"}}
    deploy = json.loads(lambda_handler(event, None))

    if len(deploy) > 0:
        import time
        name = f"deploying-privatelink-{int(time.time())}"
        aws_start_stepfunction(os.environ['DeployStacksStateMachine'], {'Input': deploy}, name)

