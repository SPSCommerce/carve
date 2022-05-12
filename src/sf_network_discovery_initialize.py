# import pylab as plt
import lambdavars

from aws import *


def lambda_handler(event, context):
    # discover AWS Organizations accounts/regions to pass to next step
    accounts = aws_discover_org_accounts()
    regions = aws_all_regions()
    discovery_targets = []
    for account_id, account_name in accounts.items():
        discovery_targets.append({
            "account_id": account_id,
            "account_name": account_name
        })
    
    print(f"discovered {len(accounts)} accounts")

    # need to purge S3 discovery folder before starting new discovery
    aws_purge_s3_path('discovery/')

    # return discovery_targets
    result = {'accounts': discovery_targets, 'regions': regions}

    return result


if __name__ == "__main__":
    event = {}
    result = lambda_handler(event, None)
    print(json.dumps(result))