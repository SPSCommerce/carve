import lambdavars
from carve import get_deploy_key, carve_role_arn, load_graph
# from sf_deploy_graph_deployment_list import deployment_list
from aws import *
import concurrent.futures



def inventory_beacons(account_dict):
    '''
    run the stack_outputs_thread() function in parallel for all stacks in the account_dict
    account_dict = {account_id: [{stackname: stackname1, region: region}, {stackname: stackname2, region: region}], ...}
    '''
    futures = set()
    beacons = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=300) as executor:
            # create threads
            for account_id, stacks in account_dict.items():
                credentials = aws_assume_role(carve_role_arn(account_id), f"endpoint-inventory")
                for stack in stacks:
                    futures.add(executor.submit(
                        stack_outputs_thread,
                        credentials=credentials,
                        region=stack['region'],
                        stackname=stack['stackname']
                        ))
            # collect thread results
            for future in concurrent.futures.as_completed(futures):
                beacons.update(future.result())

    return beacons


def stack_outputs_thread(credentials, region, stackname):
    # this function will search for stacks containing the stackname
    # and return a dict of the stack outputs
    outputs = aws_get_stack_outputs_dict(stackname, region, credentials=credentials)
    try:
        return json.loads(outputs['Beacons'])
    except KeyError:
        raise Exception(f"No Beacons stack output found in {stackname} in account {credentials['Account']}")
    

def stacks_by_account(G):
    # determine all deployed stacks for VPCs in the graph, and their account and region
    # need to generate an account dictionary of stacks:
    #     account_dict = {account_id: [{stackname: stackname1, region: region}, {stackname: stackname2, region: region}], ...}

    account_dict = {}
    vpcs = []
    for subnet in list(G.nodes):
        vpc = G.nodes().data()[subnet]['VpcId']
        if vpc not in vpcs:
            account = G.nodes().data()[subnet]['Account']
            region = G.nodes().data()[subnet]['Region']
            stackname = f"{os.environ['Prefix']}carve-managed-beacons-{vpc}"
            if account not in account_dict:
                account_dict[account] = []
            account_dict[account].append({'stackname': stackname, 'region': region}) 
    return account_dict


def lambda_handler(event, context):
    # copy deployment object
    deploy_key = get_deploy_key(last=True)
    if not deploy_key:
        raise Exception('No deployment key found')

    # get inventory of all beacons (endpoint private IP addresses)
    G = load_graph(deploy_key, local=False)
    account_dict = stacks_by_account(G)
    beacons = inventory_beacons(account_dict)
    print("beacons:", beacons)
    data = json.dumps(beacons, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, "managed_deployment/beacon_inventory.json")

    # move deployment key to deployed_graph
    key_name = deploy_key.split('/')[-1]
    aws_copy_s3_object(deploy_key, f'deployed_graph/{key_name}')
    aws_delete_s3_object(deploy_key)

# main handler
if __name__ == '__main__':
    lambda_handler(None, None)