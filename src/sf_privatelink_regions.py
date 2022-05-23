import lambdavars

import json
from aws import *
from carve import load_graph, unique_node_values
from privatelink import private_link_deployment, privatelink_template


def lambda_handler(event, context):
    ''' build CFN templates for a carve private link deployment '''

    print(event)

    if 'graph' in event['Input']:
        G = load_graph(event['Input']['graph'], local=False)
        print(f"successfully loaded graph: {event['Input']['graph']}")
    else:
        raise Exception('no graph provided in input. input format: {\"input\": {\"graph\": \"carve-privatelink-graph.json\"}}')
    
    print(f"building CFN templates for regional private link deployments")

    # get all regions and AZids in use in the carve deployment
    deploy_regions = sorted(unique_node_values(G, 'Region'))
    print(f"Graph contains {len(deploy_regions)-1} additional regions with VPCs: {deploy_regions}")
    deploy_azids = sorted(unique_node_values(G, 'AvailabilityZoneId'))
    print(f"Graph contains {len(deploy_azids)} availability zone ids in use by VPCs: {deploy_azids}")
    deploy_accounts = sorted(unique_node_values(G, 'Account'))
    print(f"Graph contains {len(deploy_accounts)} accounts wtih VPCs: {deploy_accounts}")

    # remove the current region since that was already deployed
    deploy_regions.remove(current_region)

    if ['mode'] in event:
        if event['mode'] == 'test':
            deploy_regions = ['us-east-2']
            print(f"testing with only {len(deploy_regions)} additonal regions: {deploy_regions}")

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

    print(f"total azids in use across additional {len(deploy_regions)} regions: {i}")

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
    event = {"Input": {"graph": "discovered/carve-discovered-1652883036.json"}, "mode": "test"}
    deploy = json.loads(lambda_handler(event, None))

    if len(deploy) > 0:
        import time
        name = f"deploying-privatelink-{int(time.time())}"
        aws_start_stepfunction(os.environ['DeployStacksStateMachine'], {'Input': deploy}, name)
