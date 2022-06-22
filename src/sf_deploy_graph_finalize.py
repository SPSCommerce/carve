import lambdavars
from carve import get_deploy_key, carve_role_arn, load_graph
# from sf_deploy_graph_deployment_list import deployment_list
from aws import *
import concurrent.futures


def inventory_beacons():
    """
    Inventory beacons from the deployed graph
    """
    pass


def create_account_threads(account_dict):
    '''
    run the account_thread() function in parallel in all accounts in the list
    '''
    futures = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=300) as executor:
            # create threads
            for account_id, stacks in account_dict.items():
                futures.add(executor.submit(
                    account_thread,
                    account_id=account_id,
                    stacks=stacks
                    ))
            # collect thread results
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                for each in result:
                    print(each)


def account_thread(account_id, stacks):
    # this function will search for stacks containing the stackname
    # and return a dict of the stack outputs
    credentials = aws_assume_role(carve_role_arn(account_id), f"carve-inventory")
    outputs = aws_get_stack_outputs_dict(stackname, region, credentials=credentials)

    return outputs
    

def deployed_stacks(G):
    # determine all deployed stacks for VPCs in the graph, and their account and region
    account_stacks = {}
    vpcs = []
    for subnet in list(G.nodes):
        vpc = G.nodes().data()[subnet]['VpcId']
        if vpc not in vpcs:
            account = G.nodes().data()[subnet]['Account']
            region = G.nodes().data()[subnet]['Region']
            stackname = f"{os.environ['Prefix']}carve-managed-beacons-{vpc}"
            if account not in account_stacks:
                account_stacks[account] = {}
            account_stacks[account][stackname] = 

    return vpcs


def lambda_handler(event, context):
    # copy deployment object
    deploy_key = get_deploy_key(last=True)
    if not deploy_key:
        raise Exception('No deployment key found')

    G = load_graph(deploy_key, local=False)
    # stack_deployments = deployment_list(G, upload_template=False)

    # print(stack_deployments)

    # # move deployment key to deployed_graph
    # key_name = deploy_key.split('/')[-1]
    # aws_copy_s3_object(deploy_key, f'deployed_graph/{key_name}')
    # aws_delete_s3_object(deploy_key)

# main handler
if __name__ == '__main__':
    lambda_handler(None, None)