import lambdavars
from carve import get_deploy_key
from aws import *


def lambda_handler(event, context):
    # move deployment object
    deploy_key = get_deploy_key()
    if not deploy_key:
        raise Exception('No deployment key found')

    key_name = deploy_key.split('/')[-1]
    aws_copy_s3_object(deploy_key, f'deployed_graph/{key_name}')
    aws_delete_s3_object(deploy_key, current_region)
