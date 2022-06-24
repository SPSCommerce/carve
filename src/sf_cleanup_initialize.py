import json
import os

from aws import aws_current_account, aws_discover_org_accounts, current_region
from carve import get_deploy_key, load_graph, unique_node_values


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
    safe_stacks = []

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

    # add all VPC stacks in the graph to safe stacks
    vpcs = []
    for subnet in list(G.nodes):
        vpc = G.nodes().data()[subnet]['VpcId']
        if vpc not in vpcs:
            vpcs.append(vpc)
            safe_stacks.append({
                'StackName': f"{os.environ['Prefix']}carve-managed-beacons-{vpc}",
                'Account': G.nodes().data()[subnet]['Account'],
                'Region': G.nodes().data()[subnet]['Region']
                })

    # add all private link stacks from the current account to safe stacks
    for region in sorted(unique_node_values(G, 'Region')):
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
