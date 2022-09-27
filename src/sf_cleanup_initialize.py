import json
import os

from aws import aws_current_account, aws_discover_org_accounts, current_region, aws_all_regions
from utils import get_deploy_key, load_graph, unique_node_values, select_subnets, matching_node_values


def lambda_handler(event, context):
    '''
    Prepare to clean up carve managed stacks from all accounts that are not in the graph
    - get a list of all accounts
    - create a list of stacks to protect that are used by the deployed graph
    - return the list to the step function
    '''

    deploy_key = get_deploy_key()
    G = load_graph(deploy_key, local=False)

    # remove external beacons from the graph
    external = [node for node in G.nodes() if G.nodes().data()[node]['Type'] == 'external']
    G.remove_nodes_from(external)

    print(f'cleaning up after graph deploy: {deploy_key}')

    accounts = aws_discover_org_accounts()

    # create a list for carve stacks to not delete
    safe_stacks = deployed_vpc_stacks(G)

    # add the s3 bucket stacks for active regions to safe stacks
    deploy_region_list = set(sorted(unique_node_values(G, 'Region')))
    deploy_region_list.add(current_region)
    for region in deploy_region_list:
        s3_stack = f"{os.environ['Prefix']}carve-managed-bucket-{region}"
        safe_stacks.append({
            'StackName': s3_stack,
            'Account': context.invoked_function_arn.split(":")[4],
            'Region': region
            })

    # add all private link stacks to safe stacks
    # for region in sorted(unique_node_values(G, 'Region')):
    for region in aws_all_regions():
        safe_stacks.append({
            'StackName': f"{os.environ['Prefix']}carve-managed-privatelink-{region}",
            'Account': aws_current_account(),
            'Region': region
            })

    print(f'all safe stacks: {safe_stacks}')

    # create discovery list of all accounts for step function
    discover_stacks = []
    for account_id, account_name in accounts.items():
        cleanup = {}
        cleanup['Account'] = account_id
        cleanup['SafeStacks'] = []
        for stack in safe_stacks:
            if stack['Account'] == account_id:
                # cleanup['SafeStacks'] = safe_stacks
                cleanup['SafeStacks'].append(stack['StackName'])
        discover_stacks.append(cleanup)

    # returns to a step function iterator
    # return json.dumps(discover_stacks, default=str)
    return discover_stacks

def deployed_vpc_stacks(G):
    # create a list of all VPCs in the graph
    vpcs = matching_node_values(G, 'Type', 'vpc', return_value=None)

    # if running with vpc level verification, remove any VPCs that are not monitored
    if G.graph["VerificationScope"] == "vpc":
        subnets = select_subnets(G)
        for vpc in vpcs:
            if vpc not in subnets:
                print(f"removing vpc from safe stacks: {vpc}")
                vpcs.remove(vpc)

    # add all VPC stacks in the graph to safe stacks
    stacks = []
    for vpc in vpcs:
        print(f"adding vpc to safe stacks: {vpc}")
        stacks.append({
            'StackName': f"{os.environ['Prefix']}carve-managed-endpoints-{vpc}",
            'Account': G.nodes().data()[vpc]['Account'],
            'Region': G.nodes().data()[vpc]['Region']
            })

    return stacks
