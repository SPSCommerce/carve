import lambdavars
import os
import time

from aws import (aws_codepipeline_success, aws_copy_s3_object,
                 aws_create_s3_path, aws_put_bucket_notification,
                 aws_start_stepfunction)
from carve import get_deploy_key


def lambda_handler(event, context):
    print(event)
    if 'CodePipeline.job' in event:
        code_pipeline(event, context)
    elif 's3' in event['Records'][0]:
        if event['Records'][0]['s3']['bucket']['name'] == os.environ['CarveS3Bucket']:
            key = event['Records'][0]['s3']['object']['key']
            input = {'graph': key}
            name = f'bucket-trigger-{key}-{int(time.time())}'
            aws_start_stepfunction(os.environ['DeployBeaconsStateMachine'], input, name)


def code_pipeline(event, context):
        param = event['CodePipeline.job']['data']['actionConfiguration']['configuration']['UserParameters']

        if param == 'UpdateManagedStacks':
            if os.environ['PropogateUpdates'] == 'True':
                deploy_key = get_deploy_key(last=True)
                if deploy_key is not None:
                    # copy deploy key to start deployment
                    key_name = deploy_key.split('/')[-1]
                    aws_copy_s3_object(deploy_key, f'deploy_input/{key_name}')
                    # start_carve_deployment(event, context, key=deploy_key)
                else:
                    print('No previous deploy key to run updates with')
            else:
                print('Updating Managed Stacks is disabled')

        elif param == 'BucketNotification':
            aws_create_s3_path('deploy_input/')
            aws_put_bucket_notification('deploy_input/', context.invoked_function_arn)

        # let the pipeline continue
        aws_codepipeline_success(event['CodePipeline.job']['id'])

# main function
if __name__ == '__main__':
    lambda_handler(None, None)