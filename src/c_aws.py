import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import json
import sys
import os
from multiprocessing import Process, Pipe
import time
import shelve

boto_config = Config(retries=dict(max_attempts=10))


def aws_assume_role(role_arn, session_name, token_life=900):
    # a function for this lambda to assume a given role
    sts_client = boto3.client('sts', config=boto_config)
    try:
        assumed_role_object = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            DurationSeconds=int(token_life))
        # expiration date is not used in carve, remove for smaller payloads
        del assumed_role_object['Credentials']['Expiration']
        return assumed_role_object['Credentials'] 
    except ClientError as e:
        print(f'Failed to assume {role_arn}: {e}')
        sys.exit()


def _aws_assume_role_process(account, role, child_conn):
    '''bakground process to use the aws_assume_role function in parallel'''

    credentials = aws_assume_role(
        role_arn=role.replace(":*:", f":{account}:"), 
        session_name=f"org_session_{account}"
        )

    response = {"account": account, "credentials": credentials}
    child_conn.send(response)
    child_conn.close()


def aws_parallel_role_creation(accounts, role):
    '''assume roles in every account in parallel, return session creds as dict'''
    print(f'assuming roles in {len(accounts)} accounts')
    a_processes = []
    a_parent_connections = []
    credentials = {}

    for account in accounts:
        a_parent_conn, a_child_conn = Pipe()
        a_parent_connections.append(a_parent_conn)
        a_process = Process(
            target=_aws_assume_role_process,
            args=(account, role, a_child_conn)
            )
        a_processes.append(a_process)
        a_process.start()

    # wait for all processes to finish
    for process in a_processes:
        process.join()

    # add all credentials to a dictionary       
    for parent_connection in a_parent_connections:
        account_creds = parent_connection.recv()
        credentials[account_creds['account']] = account_creds['credentials']

    return credentials


def aws_start_stepfunction(sf_arn, sf_input):
    ''' start a step function workflow with the given input '''

    sm_client = boto3.client('stepfunctions', region_name=os.environ['AWS_REGION'])
    sm_input = json.dumps(sf_input)

    response = sm_client.start_execution(stateMachineArn=sf_arn, input=sm_input)

    return response


def aws_describe_stack(stackname, region, credentials):
    ''' return a stack description if it exists ''' 
    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )
    try:
        stack = client.describe_stacks(StackName=stackname)['Stacks'][0]
    except ClientError as e:
        stack = None

    return stack


def aws_get_carve_tags(lambda_arn):
    ''' get my own tags and format for CFN calls '''

    # check for cached tags to save API calls
    cfn_tags = shelve.open('/tmp/tags_cache', writeback=True)

    # if not cached, get tags
    if len(cfn_tags) == 0:
        client = boto3.client('lambda')
        response = client.list_tags(Resource=lambda_arn)

        cfn_tags = []
        for key, value in response['Tags'].items():
            if key.startswith("aws:"):
                pass
            else:
                tag = {}
                tag['Key'] = key
                tag['Value'] = value
                cfn_tags.append(tag)
    else:
        print(f"found cached tags: {cfn_tags}")

    return cfn_tags


def aws_get_orgid():
    client = boto3.client('organizations', config=boto_config)
    response = client.describe_organization()
    return(response['Organization']['MasterAccountId'])


def aws_execute_change_set(change_set_name, region, credentials):
    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    response = client.execute_change_set(ChangeSetName=change_set_name)
    return response


def aws_create_stack(stackname, region, template_url, parameters, credentials, tags):

    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    response = client.create_stack(
        StackName=stackname,
        TemplateURL=template_url,
        Parameters=parameters,
        Capabilities=['CAPABILITY_NAMED_IAM'],
        Tags=tags
        )

    return response


def aws_delete_stack(stackname, region, credentials):

    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    response = client.delete_stack(StackName=stackname)

    return response


def aws_create_changeset(stackname, region, template_url, parameters, credentials, tags):
    '''deploy SAM template thru changesets'''
    changeset_name = f"stackname-{int(time.time())}"

    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    response = client.create_change_set(
        StackName=stackname,
        ChangeSetName=changeset_name,
        TemplateURL=template_url,
        Tags=tags,
        Parameters=parameters
        )

    # returns...
    # {
    #     'Id': 'string',
    #     'StackId': 'string'
    # }

    return changeset_name


def aws_describe_change_set(change_set_name, stackname, region, credentials):
    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    response = client.describe_change_set(
      ChangeSetName=change_set_name,
      StackName=stackname
    )
    return response['Status']



def aws_find_stacks(startswith, region, credentials):
    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    response = client.get_paginator('list_stacks')

    stacks = []
    for page in response:
        for stack in page['StackSummaries']:
            if stack['StackName'].startswith(startswith):
                stacks.append(stack)

    return stacks


def aws_read_s3_direct(key, region):
    # get graph from S3
    resource = boto3.resource('s3', config=boto_config)
    obj = resource.Object(os.environ['CarveS3Bucket'], key)
    return obj.get()['Body'].read().decode('utf-8')


def aws_copy_s3_object(key, target, region):
    # get graph from S3
    resource = boto3.resource('s3', config=boto_config)
    response = resource.Object(os.environ['CarveS3Bucket'], target).copy_from(CopySource=key)
    return response

def aws_delete_s3_object(key, region):
    # get graph from S3
    resource = boto3.resource('s3', config=boto_config)
    response = resource.Object(os.environ['CarveS3Bucket'], key).delete()
    return response

def aws_download_file_carve_s3(key, file_path, bucket=None):
    '''
    writes file_path to the carve s3 bucket
    '''
    client = boto3.client('s3', config=boto_config)
    if bucket is None:
        bucket = os.environ['CarveS3Bucket']

    try:
        response = client.download_file(Bucket=bucket, Key=key, Filename=file_path)
        return response
    except ClientError as e:
        print(f's3 error: {e}')
        # logger.exception(f'Failed to write outputs/logs s3 bucket')


def aws_states_list_executions(arn):
    client = boto3.client('stepfunctions', config=boto_config)
    response = client.list_executions(stateMachineArn=arn)
    return response['executions']


def aws_create_s3_path(path):
    if path.endswith("/"):
        s3path = path
    else:
        s3path = f'{path}/'

    client = boto3.client('s3', config=boto_config)
    try:
        client.put_object(Bucket=os.environ['CarveS3Bucket'], Key=s3path)
    except ClientError as e:
        print(f'error creating s3 path: {e}')


def aws_delete_bucket_notification():
    client = boto3.client('s3', config=boto_config)
    try:
        response = client.put_bucket_notification_configuration(
          Bucket=os.environ['CarveS3Bucket'],
          NotificationConfiguration={}
        )
        return response
    except ClientError as e:
        print(f'error creating bucket notification: {e}')


def aws_empty_bucket():
    bucket = os.environ['CarveS3Bucket']
    client = boto3.client('s3', config=boto_config)
    paginator = client.get_paginator('list_object_versions')

    delete_list = []
    for response in paginator.paginate(Bucket=bucket):
        if 'DeleteMarkers' in response:
            for mark in response['DeleteMarkers']:
                delete_list.append({'Key': mark['Key'], 'VersionId': mark['VersionId']})

        if 'Versions' in response:
            for version in response['Versions']:
                delete_list.append({'Key': version['Key'], 'VersionId': version['VersionId']})

    for i in range(0, len(delete_list), 1000):
        response = client.delete_objects(
            Bucket=bucket,
            Delete={
                'Objects': delete_list[i:i+1000],
                'Quiet': True
            }
        )
        print(f"purged s3 bucket: {bucket}")



def aws_put_bucket_notification(path, notification_id, function_arn):
    client = boto3.client('s3', config=boto_config)
    try:
        response = client.put_bucket_notification_configuration(
          Bucket=os.environ['CarveS3Bucket'],
          NotificationConfiguration={
            'LambdaFunctionConfigurations': [
              {
                'Id': notification_id,
                'LambdaFunctionArn': function_arn,
                'Events': [
                  's3:ObjectCreated:*'
                ],
                'Filter': {
                  'Key': {
                    'FilterRules': [
                      {
                        'Name': 'prefix',
                        'Value': path
                      },
                      {
                        'Name': 'suffix',
                        'Value': '.json'
                      }
                    ]
                  }
                }
              }
            ]
          }
        )
        return response
    except ClientError as e:
        print(f'error creating bucket notification: {e}')


def aws_upload_file_carve_s3(key, file_path):
    '''
    writes file_path to the carve s3 bucket
    '''
    client = boto3.client('s3', config=boto_config)

    try:
        print(f"bucket = {os.environ['CarveS3Bucket']}")
        print(f"file_path = {file_path}")
        print(f"key = {key}")
        response = client.upload_file(Filename=file_path, Bucket=os.environ['CarveS3Bucket'], Key=key)
        return response
    except ClientError as e:
        print(f's3 error: {e}')
        # logger.exception(f'Failed to write outputs/logs s3 bucket')



# if __name__ == '__main__':
#     main()