import lambdavars
from utils import get_deploy_key, carve_role_arn, load_graph
from sf_cleanup_initialize import deployed_vpc_stacks
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
    ''' 
    this function is used as a thread and will return a dict of the stack outputs for the provided stack
    '''
    outputs = aws_get_stack_outputs_dict(stackname, region, credentials=credentials)
    try:
        beacons = {}
        stack_outputs = json.loads(outputs['Beacons'])
        for subnet, ip in stack_outputs.items():
            beacons[subnet] = {
                'type': 'managed',
                'region': region,
                'account': credentials['Account'],
                'address': f"http://{ip}/up"
            }
        return beacons
    except KeyError:
        raise Exception(f"No Beacons stack output found in {stackname} in account {credentials['Account']}")
    

def update_beacon_inventory(G):
    '''
    update the inventory of beacons in the graph G
    '''
    # get all deployed stacks and organize by account
    account_dict = {}
    stacks = deployed_vpc_stacks(G)  # [{'StackName': 's', 'Account': 'a', 'Region': 'r'}, ...]
    for stack in stacks:
        if stack['Account'] not in account_dict:
            account_dict[stack['Account']] = []

        account_dict[stack['Account']].append({
            'stackname': stack['StackName'],
            'region': stack['Region']
        })

    # add managed beacons to inventory
    beacons = inventory_beacons(account_dict)

    # add external targets
    for node in list(G.nodes):
        if G.nodes[node]['Type'] == 'external':
            beacons[node] = {
                'type': 'external',
                'address': G.nodes[node]['Address']
            }

    print("beacons:", beacons)

    # push inventory to S3
    data = json.dumps(beacons, ensure_ascii=True, indent=2, sort_keys=True)
    aws_put_direct(data, "managed_deployment/beacon-inventory.json")



def lambda_handler(event, context):
    # load graph
    deploy_key = get_deploy_key()
    if not deploy_key:
        raise Exception('No deployment key found')
    G = load_graph(deploy_key, local=False)

    # get inventory of all beacons (endpoint private IP addresses)
    update_beacon_inventory(G)

    # move deployment key to deployed_graph
    key_name = deploy_key.split('/')[-1]
    aws_copy_s3_object(deploy_key, f'deployed_graph/{key_name}')
    aws_delete_s3_object(deploy_key)


# main handler for local testing
if __name__ == '__main__':
    # lambda_handler(None, None)
    # G = load_graph("deployed_graph/carve-test-pl-subnets.json", local=False)

    deploy_key = "ignore/carve-test-pl-subnets.json"
    G = load_graph(deploy_key, local=True)

    update_beacon_inventory(G)
