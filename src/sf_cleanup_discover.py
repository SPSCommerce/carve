import concurrent.futures
import json
import os

from aws import aws_all_regions, aws_assume_role, aws_find_stacks
from utils import carve_role_arn


def lambda_handler(event, context):
    '''
    discover all deployments of carve named stacks and determine if they should exist
    by checking against the safe_stacks list
    - returns a list of stacks to be deleted

    event = {'Input': {'Account': '123456789012', 'SafeStacks': []}}

    '''
    print(event)

    account = event['Input']['Account']
    safe_stacks = event['Input']['SafeStacks']

    credentials = aws_assume_role(carve_role_arn(account), f"carve-cleanup")
    startswith = f"{os.environ['Prefix']}carve-managed-"

    futures = set()
    delete_stacks = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for region in aws_all_regions():
            futures.add(executor.submit(
                threaded_find_stacks,
                account=account,
                region=region,
                safe_stacks=safe_stacks,
                startswith=startswith,
                credentials=credentials
            ))
        for future in concurrent.futures.as_completed(futures):
            for stack in future.result():
                delete_stacks.append(stack)

    # return json to step function
    return delete_stacks


def threaded_find_stacks(account, region, safe_stacks, startswith, credentials):
    # find all carve managed stacks in an account
    stacks = aws_find_stacks(startswith, account, region, credentials)

    if stacks is None:
        # print(f"cannot list stacks in {account} in {region}.")        
        return []        
    elif len(stacks) == 0:
        # print(f"found no stacks to delete in {account} in {region}.")        
        return []
    else:
        delete_stacks = []
        print(f"safe_stacks: {safe_stacks}")
        for stack in stacks:
            if stack['StackName'] not in safe_stacks:
                print(f"found {stack['StackName']} for deletion in {account} in {region}.")
                # create payloads for delete iterator in state machine
                del_stack = {}
                del_stack['StackName'] = stack['StackName']
                del_stack['StackId'] = stack['StackId']
                del_stack['Region'] = region
                del_stack['Account'] = account
                delete_stacks.append(del_stack)
            else:
                print(f"{stack['StackName']} is protected")

        return delete_stacks



