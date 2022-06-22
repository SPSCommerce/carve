import lambdavars
from carve import get_deploy_key, carve_role_arn
from aws import *
import concurrent.futures


def inventory_beacons():
    """
    Inventory beacons from the deployed graph
    """
    pass


def create_account_threads(account_list):
    '''
    run the account_thread() function in parallel in all accounts in the list
    '''
    futures = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=300) as executor:
            # create threads
            for account_id in account_list:
                futures.add(executor.submit(account_thread, account_id=account_id))
            # collect thread results
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                for each in result:
                    print(each)


def account_thread(account_id, stackname, region):
    # this function will search for stacks containing the stackname
    # and return a dict of the stack outputs
    credentials = aws_assume_role(carve_role_arn(account_id), f"carve-inventory")
    outputs = aws_get_stack_outputs_dict(stackname, region, credentials=credentials)
    
    return outputs
    



def lambda_handler(event, context):
    # copy deployment object
    deploy_key = get_deploy_key()
    if not deploy_key:
        raise Exception('No deployment key found')

    key_name = deploy_key.split('/')[-1]
    aws_copy_s3_object(deploy_key, f'deployed_graph/{key_name}')

    # delete deployment object
    aws_delete_s3_object(deploy_key)
