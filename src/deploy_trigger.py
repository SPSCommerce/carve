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
            print('creating deploy_input path')
            aws_create_s3_path('deploy_input/')
            print(f'creating bucket notification for lambda arn: {context.invoked_function_arn}')
            aws_put_bucket_notification('deploy_input/', context.invoked_function_arn)

        # let the pipeline continue
        aws_codepipeline_success(event['CodePipeline.job']['id'])

# main function
if __name__ == '__main__':

    event = {'CodePipeline.job': {'id': '145c229a-39fc-42ff-8166-013f56f7a33e', 'accountId': '816849209215', 'data': {'actionConfiguration': {'configuration': {'FunctionName': 'nonprod-carve-core-deploy_trigger', 'UserParameters': 'BucketNotification'}}, 'inputArtifacts': [], 'outputArtifacts': [], 'artifactCredentials': {'accessKeyId': 'ASIA34MABY57SOFGIA3A', 'secretAccessKey': '0+myVphQsY0PQKglCkBdXjwED91tbP7K30Rz1W2T', 'sessionToken': 'IQoJb3JpZ2luX2VjEC4aCXVzLWVhc3QtMSJIMEYCIQCd9z9pgRSAia0FfI0oTv5aeYnJne0FLacvjP4go5MmhwIhALT5RA2yv7Of8tjPH4H9oynvRNbOrz6OXLPjG/fzaH1rKocDCEcQABoMODE2ODQ5MjA5MjE1IgytPCGIYW7So+SVGE8q5ALJDvv1078aSTuDQEcW5AKScrrhk5BbdkKFU30ULOzS5RbFjzUlmVPXUfJR8sla5yD5o7uPboVJN+KKFNVoiM+YHcl0Zp2XU3YFv7rLp0ZqtbAVtqZYhzij2SmZPqc3rj3YmyqBCbEbrhZMf0ArJ4ud/kJHg5iZAdtAFkA6PrkCSOca6zmnWku3+dGLjvwmBEISqx3RbqODEGlnYkI6uK/1N0DO0eKyKmM/NAOsNnveZu3ne4JnDEdlhc3lIHpAttaFFYV88tDUdcDjbeRMJhdqeNp+2R+vvr6xlw0wToIlSzeBGoNRab3j2yPu4D9XAZmmEwXhhB/NcT8QiIwgmuwsOEKqYzkx7qTz6N6oqxY4A3qPYi0k7liYeypRsjInB25KUUYCSzBeta7xtYchS+J+kkGaKjJuGJWq/JlME5VlHIbTEBkwX1GZdXif3DRAu0dfH1J65uj1gaerLqRo+H7UNNkF1DCOjseVBjqOAaZXAb7j/tGu8WdTNGdCfkXEY+YweuZr0lUtcLBmIWHXwC7ghpcy1qX5ItlkSLmU25it5yR9Ca1mhF6EHrRPQjeLUP4PdtRTIpZtXmqsAxgahzuDnCZAz/ZKHBEf25e8AJpgSFmSwHLUTDWDip3UTFOkJ1FHXRQSa/y85pc4BjhC7Zkqw7xWS+NEOAQUCfs=', 'expirationTime': 1655818898000}}}}
    lambda_handler(event, lambdavars.context)