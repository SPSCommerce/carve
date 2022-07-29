# import pylab as plt
import lambdavars

from aws import *


def lambda_handler(event, context):
    '''
    discovers AWS accounts/regions in use in an Org and returns the results as a dict
    '''

    # need to purge S3 discovery folder before starting new discovery
    aws_purge_s3_path('discovery/')

    print(event)

    # get list of accounts/regions in use in the Org
    accounts = aws_discover_org_accounts()
    regions = None

    if 'filters' in event['Input']:
        for filter in event['Input']['filters']:
            if filter == 'regions':
                regions = event['Input']['filters']['regions']
            else:
                # can add other filters here
                pass

    if regions is None:
        regions = aws_all_regions()

    discovery_targets = []
    for account_id, account_name in accounts.items():
        discovery_targets.append({
            "account_id": account_id,
            "account_name": account_name
        })
    
    print(f"discovered {len(accounts)} accounts")

    # return discovery_targets
    result = {'accounts': discovery_targets, 'regions': regions}

    return result


if __name__ == "__main__":
    event = {}
    result = lambda_handler(event, None)
    print(json.dumps(result))