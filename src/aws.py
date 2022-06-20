import boto3
from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import ClientError
import json
import os
import shelve
import sys
import time
import datetime

current_region = os.environ['AWS_REGION']
boto_config = Config(retries=dict(max_attempts=10))

aws_region_dict = {"us-east-1": "use1",
    "us-east-2": "use2",
    "us-west-1": "usw1",
    "us-west-2": "usw2",
    "us-gov-west-1": "usgw2",
    "ca-central-1": "cac1",
    "eu-west-1": "ew1",
    "eu-west-2": "ew2",
    "eu-central-1": "ec1",
    "ap-southeast-1": "apse1",
    "ap-southeast-2": "apse2",
    "ap-south-1": "aps1",
    "ap-northeast-1": "apne1",
    "ap-northeast-2": "apne2",
    "sa-east-1": "sae1",
    "cn-north-1": "cn1"
}


def _get_credentials(arn=None, account=None):
    if arn is not None:
        account = arn.split(':')[4]        
    role = f"arn:aws:iam::{account}:role/{os.environ['OrgRoleName']}"
    session_name = "carve-network-test"
    credentials = aws_assume_role(role, session_name)
    credentials['Account'] = account
    return credentials


def aws_assume_role(role_arn, session_name, token_life=900):
    # a function for this lambda to assume a given role
    sts_client = boto3.client(
        'sts',
        region_name=current_region,
        endpoint_url=f'https://sts.{current_region}.amazonaws.com',
        config=boto_config
        )
    try:
        assumed_role_object = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            DurationSeconds=int(token_life))
        assumed_role_object['Credentials']['Account'] = role_arn.split(':')[4]
        return assumed_role_object['Credentials'] 
    except ClientError as e:
        print(f'Failed to assume {role_arn}: {e}')
        sys.exit()



def aws_current_account():
    sts = boto3.client('sts')
    account = sts.get_caller_identity()['Account']
    return account

def aws_discover_org_accounts():
    ''' discover all accounts in the AWS Org'''
    orgs = boto3.client('organizations')
    root = orgs.describe_organization()['Organization']['MasterAccountArn'].split(':')[4]
    account = aws_current_account()
    if account == root:
        client = orgs
    else:
        credentials = _get_credentials(account=root)
        client = boto3.client(
            'organizations',
            aws_access_key_id = credentials['AccessKeyId'],
            aws_secret_access_key = credentials['SecretAccessKey'],
            aws_session_token = credentials['SessionToken']
            )

    paginator = client.get_paginator('list_accounts')
    pages = paginator.paginate(PaginationConfig={'PageSize': 20})
    accounts = {}
    for page in pages:
        # add each account that is active
        for account in page['Accounts']:
            if account['Status'] == 'ACTIVE':
                # create new account object
                accounts[account['Id']] = account['Name']
    return accounts


def aws_all_regions():
    # get all regions
    if 'Regions' in os.environ:
        all_regions = os.environ['Regions'].split(",")
        if len(all_regions) == 0:
            all_regions = Session().get_available_regions('cloudformation')        
    else:
        all_regions = Session().get_available_regions('cloudformation')
    # not all regions support what carve does (SNS and other limitations)
    unavailable = ['af-south-1', 'eu-south-1', 'ap-east-1', 'me-south-1']
    regions = []
    for region in all_regions:
        if region not in unavailable:
            regions.append(region)
    # this will disable regions for testing
    print(f'using regions: {regions}')
    return regions


def aws_codepipeline_success(job_id):
    client = boto3.client('codepipeline', region_name=current_region)
    try:
        response = client.put_job_success_result(jobId=job_id)
        return response
    except ClientError as e:
        print(f'error returning success to codepipeline: {e}')


def aws_start_stepfunction(sf_arn, sf_input, name):
    ''' start a step function workflow with the given input '''

    client = boto3.client('stepfunctions', region_name=current_region)
    sm_input = json.dumps(sf_input)

    response = client.start_execution(
        stateMachineArn=sf_arn,
        name=name,
        input=sm_input)

    return response


def aws_describe_stack(stackname, region, credentials=None):
    ''' return a stack description if it exists ''' 
    if credentials is None:
        client = boto3.client(
            'cloudformation',
            config=boto_config,
            region_name=region
            )
    else:
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
        if e.response['Error']['Code'] == 'ValidationError':
            stack = None
        else:
            raise e

    return stack


def aws_get_stack_outputs_dict(stackname, region, credentials=None):
    ''' get the outputs of the stack '''
    stack = aws_describe_stack(stackname, region, credentials)
    outputs = {}
    if stack is not None:
        for output in stack['Outputs']:
            outputs[output['OutputKey']] = output['OutputValue']
    return outputs



def aws_describe_vpc_endpoint_service_configuration(service, region):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region
        )
    try:
        response = client.describe_vpc_endpoint_service_configurations(
            ServiceIds=[service],
        )
        return response['ServiceConfigurations'][0]
    except ClientError as e:
        raise(e)


def aws_get_template(stackname, region, credentials=None):
    ''' return the template for a stack '''
    if credentials is None:
        client = boto3.client(
            'cloudformation',
            config=boto_config,
            region_name=region
            )
    else:
        client = boto3.client(
            'cloudformation',
            config=boto_config,
            region_name=region,
            aws_access_key_id = credentials['AccessKeyId'],
            aws_secret_access_key = credentials['SecretAccessKey'],
            aws_session_token = credentials['SessionToken']
            )
    try:
        template = client.get_template(StackName=stackname)
    except ClientError as e:
        if e.response['Error']['Code'] == 'ValidationError':
            template = None
        else:
            raise e
    return template


def aws_describe_vpc_endpoint_permissions(service_id):
    ''' get allowed principals on vpc endpoint ''' 
    client = boto3.client('ec2',config=boto_config)
    try:
        paginator = client.get_paginator('describe_vpc_endpoint_service_permissions')
        results = []
        for page in paginator.paginate(ServiceId=service_id, PaginationConfig={'PageSize': 100}):
            for allowed in page['AllowedPrincipals']:
                results.append(allowed['Principal'])
        return results

    except ClientError as e:
        results = []

    return results


def aws_modify_vpc_endpoint_permissions(service_id, add_principals=[], remove_principals=[]):
    ''' update allowed principals on vpc endpoint ''' 
    client = boto3.client('ec2',config=boto_config)
    try:
        response = client.modify_vpc_endpoint_service_permissions(
            ServiceId=service_id,
            AddAllowedPrincipals=add_principals,
            RemoveAllowedPrincipals=remove_principals
        )
    except ClientError as e:
        print(f'error modifying vpc endpoint permissions: {e}')



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


def aws_execute_change_set(changesetname, stackname, region, credentials):
    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    response = client.execute_change_set(
        ChangeSetName=changesetname,
        StackName=stackname)
    return response


def aws_describe_instances(instances, region, credentials):
    if len(instances) == 0:
        return []
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
    )
    paginator = client.get_paginator('describe_instances')
    results = []
    for page in paginator.paginate(InstanceIds=instances):
        for reservation in page['Reservations']:
            for instance in reservation['Instances']:
                results.append(instance)
    return results


def aws_create_ec2_tag(instance, tags, region, credentials):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
    )
    response = client.create_tags(
        Resources=[instance],
        Tags=tags # [{'Key': 'Name', 'Value': name}]
    )


def aws_describe_transit_gateways(region, credentials):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
    )
    paginator = client.get_paginator('describe_transit_gateways')
    results = []
    for page in paginator.paginate():
        for each in page['TransitGateways']:
            results.append(each)
    return results


def aws_describe_transit_gateway_attachments(region, credentials):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
    )
    paginator = client.get_paginator('describe_transit_gateway_attachments')
    results = []
    for page in paginator.paginate():
        for each in page['TransitGatewayAttachments']:
            results.append(each)
    return results


def aws_describe_transit_gateway_vpc_attachments(region, credentials):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
    )
    paginator = client.get_paginator('describe_transit_gateway_vpc_attachments')
    results = []
    for page in paginator.paginate():
        for each in page['TransitGatewayVpcAttachments']:
            results.append(each)
    return results


def aws_describe_transit_gateway_route_tables(region, credentials):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
    )
    paginator = client.get_paginator('describe_transit_gateway_route_tables')
    results = []
    for page in paginator.paginate():
        for each in page['TransitGatewayRouteTables']:
            results.append(each)
    return results


# def aws_describe_transit_gateway_peering_attachments(tgw_id, region, credentials):
#     client = boto3.client(
#         'ec2',
#         config=boto_config,
#         region_name=region,
#         aws_access_key_id = credentials['AccessKeyId'],
#         aws_secret_access_key = credentials['SecretAccessKey'],
#         aws_session_token = credentials['SessionToken']
#     )
#     paginator = client.get_paginator('describe_transit_gateway_peering_attachments')
#     ta = []

#     for page in paginator.paginate(TransitGatewayAttachmentIds=[tgw_id]):
#         for t in page['TransitGatewayAttachmentIds']:
#             ta.append(t)
#     return ta


# def aws_describe_transit_gateway_vpc_attachments(tgw_id, region, credentials):
#     client = boto3.client(
#         'ec2',
#         config=boto_config,
#         region_name=region,
#         aws_access_key_id = credentials['AccessKeyId'],
#         aws_secret_access_key = credentials['SecretAccessKey'],
#         aws_session_token = credentials['SessionToken']
#     )
# paginator = client.get_paginator('describe_transit_gateway_attachments')
# ta = []

# for page in paginator.paginate(TransitGatewayAttachmentIds=[tgw_id]):
#     for t in page['TransitGatewayAttachmentIds']:
#         ta.append(t)
# return ta





def aws_create_stack(stackname, region, template, parameters, credentials, tags):

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
        TemplateBody=template,
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


def aws_create_changeset(stackname, changeset_name, region, template, parameters, credentials, tags):
    '''deploy CFN/SAM templates thru changesets'''
    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    size = len(template.encode('utf-8'))
    if size < 51000:
        response = client.create_change_set(
            StackName=stackname,
            ChangeSetName=changeset_name,
            TemplateBody=template,
            Tags=tags,
            Parameters=parameters,
            Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND']
            )
    else:
        # put larger templates into managed S3 bucket
        if os.environ['UniqueId'] == "":
            unique = os.environ['OrgId']
        else:
            unique = os.environ['UniqueId']

        rb = f"{os.environ['Prefix']}carve-managed-bucket-{unique}-{region}"
        key = f'managed_deployment/{stackname}-changeset.json'
        aws_put_direct(template, key, bucket=rb)
        response = client.create_change_set(
            StackName=stackname,
            ChangeSetName=changeset_name,
            TemplateURL=f"https://s3.amazonaws.com/{rb}/{key}",
            Tags=tags,
            Parameters=parameters,
            Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND']
            )
    return response


def aws_describe_change_set(changesetname, region, credentials):
    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    response = client.describe_change_set(ChangeSetName=changesetname)
    return response


def aws_find_stacks(startswith, account, region, credentials):
    client = boto3.client(
        'cloudformation',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    sfilter = [
        'CREATE_FAILED', 'CREATE_COMPLETE', 'ROLLBACK_IN_PROGRESS',
        'ROLLBACK_FAILED', 'ROLLBACK_COMPLETE', 'DELETE_FAILED', 
        'UPDATE_IN_PROGRESS', 'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS',
        'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_IN_PROGRESS', 'UPDATE_ROLLBACK_FAILED',
        'UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS', 'UPDATE_ROLLBACK_COMPLETE'
    ]

    stacks = []
    try:
        paginator = client.get_paginator('list_stacks')
        for page in paginator.paginate(StackStatusFilter=sfilter):
            for stack in page['StackSummaries']:
                if stack['StackName'].startswith(startswith):
                    stacks.append(stack)
    except ClientError as e:
        print(f"cannot list stacks in {account} in {region}: {e}")

    return stacks


def aws_describe_asg(asg, region, credentials):
    client = boto3.client(
        'autoscaling',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )
    response = client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg])
    return response


def aws_update_asg_size(asg, desired, region, credentials):
    client = boto3.client(
        'autoscaling',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )
    response = client.update_auto_scaling_group(
        AutoScalingGroupName=asg,
        # MinSize=minsize,
        # MaxSize=maxsize,
        DesiredCapacity=desired
        )
    return response


def aws_newest_s3(path, bucket=os.environ['CarveS3Bucket']):
    # return the newest file in an S3 path
    client = boto3.client('s3', config=boto_config)
    objs = client.list_objects_v2(Bucket=bucket, Prefix=path)
    if objs['KeyCount'] > 0:
        contents = objs['Contents']
        get_last_modified = lambda obj: int(obj['LastModified'].strftime('%s'))
        newest = [obj['Key'] for obj in sorted(contents, key=get_last_modified)][-1]
        return newest
    else:
        return None


def aws_read_s3_direct(key, region):
    # get graph from S3
    resource = boto3.resource('s3', config=boto_config)
    try:
        obj = resource.Object(os.environ['CarveS3Bucket'], key)
        return obj.get()['Body'].read().decode('utf-8')
    except ClientError as e:
        print(f"error reading s3: {e}")
        return None


def aws_put_direct(data, key, bucket=os.environ['CarveS3Bucket']):
    client = boto3.client('s3', config=boto_config)
    try:
        response = client.put_object(
            Bucket=bucket,
            Body=data,
            Key=key)
        return response
    except ClientError as e:
        print(f"error writing to s3: {e}")
        return None


def aws_s3_list_objects(prefix='', bucket=os.environ['CarveS3Bucket']):
    keys = []
    client = boto3.client('s3', config=boto_config)
    paginator = client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for key in page['Contents']:
            keys.append(key['Key'])
    return(keys)


def aws_s3_upload(file_name, object_name=None, bucket=os.environ['CarveS3Bucket']):
    client = boto3.client('s3', config=boto_config)

    if object_name is None:
        object_name = file_name
    try:
        response = client.upload_file(file_name, bucket, object_name)
    except ClientError as e:
        print(f"error writing to s3: {e}")
        return False
    return True


def aws_copy_s3_object(key, target_key, source_bucket=os.environ['CarveS3Bucket'], target_bucket=os.environ['CarveS3Bucket']):
    resource = boto3.resource('s3', config=boto_config)
    src = {
        "Bucket": source_bucket,
        "Key": key
    }
    bucket = resource.Bucket(target_bucket)
    response = bucket.copy(src, target_key)
    return response

def aws_delete_s3_object(key):
    # delete object from S3
    print(f"deleting from s3: {key}")
    resource = boto3.resource('s3', config=boto_config)
    response = resource.Object(os.environ['CarveS3Bucket'], key).delete()
    print(response)
    return response

def aws_get_carve_s3(key, file_path, bucket=None):
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


def aws_register_targets(arn, targets, region):
    client = boto3.client('elbv2', config=boto_config, region_name=region)
    response = client.register_targets(
        TargetGroupArn=arn,
        Targets=targets
        # [
        #     {
        #         'Id': '10.0.0.1',
        #         'Port': 80,
        #         'AvailabilityZone': 'all'
        #     },
        # ]
    )
    return response


def aws_states_list_executions(arn, results=100):
    client = boto3.client('stepfunctions', config=boto_config)
    if results < 10:
        executions = client.list_executions(
            stateMachineArn=arn,
            maxResults=results
        )['executions']
    else:
        paginator = client.get_paginator('list_executions')
        executions = []
        for page in paginator.paginate(maxResults=results, stateMachineArn=arn):
            for e in page['executions']:
                executions.append(e)
    return executions


def aws_states_describe_execution(arn):
    client = boto3.client('stepfunctions', config=boto_config)
    response = client.describe_execution(executionArn=arn)
    return response


def aws_create_s3_path(path):
    if path.endswith("/"):
        s3path = path
    else:
        s3path = f'{path}/'

    client = boto3.client('s3', config=boto_config)
    try:
        client.put_object(
            Bucket=os.environ['CarveS3Bucket'],
            Key=s3path,
            ACL='bucket-owner-full-control'
            )
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


def aws_tag_value( tags, key ):
    if type(tags) != list:
        return None
    res = map( lambda tag: tag['Value'] , filter( lambda tag: tag['Key'] == key, tags ) )
    if len(res) == 0:
        return None
    else:    # tags are unique, so this is the _only_ value
        return res[0]


# def aws_latest_ami(region=current_region):
#     client = boto3.client(
#         'ec2',
#         config=boto_config,
#         region_name=region,
#         )
#     response = client.describe_images(Owners=['self'])
#     return response['Images'][0]


def aws_copy_image(name, source_image, region):
    client = boto3.client('ec2', region_name=region, config=boto_config)
    response = client.copy_image(
        # ClientToken='string',
        Description='Carve AMI',
        Encrypted=False,
        # KmsKeyId=source_kms,
        Name=name,
        SourceImageId=source_image,
        SourceRegion=current_region
    )
    return {"ImageId": response['ImageId'], "region": region}


def aws_describe_image(image, region=current_region):
    client = boto3.client('ec2', config=boto_config, region_name=region)
    response = client.describe_images(ImageIds=[image])
    if len(response['Images']) > 0:
        return response['Images'][0]
    else:
        return None

def aws_share_image(image, accounts, region=current_region):
    lp = {}
    lp['Add'] = []
    lp['Remove'] = []

    # add permission for all requested accounts
    for a in accounts:
        lp['Add'].append({'UserId': a})

    # remove permission for any account in org not requested
    for a in aws_discover_org_accounts():
        if a not in accounts:
            lp['Remove'].append({'UserId': a})

    print(f'AMI LaunchPermission: {lp}')

    client = boto3.client('ec2', config=boto_config, region_name=region)
    response = client.modify_image_attribute(
        ImageId=image,
        LaunchPermission=lp
        )
    return response



def aws_ssm_put_parameter(parameter, value, region=current_region, param_type='String'):
    client = boto3.client('ssm', config=boto_config, region_name=region)
    # if "/" not in parameter:
    #     param = f"{os.environ['Prefix']}carve-resources/"
    response = client.put_parameter(
        Name=parameter,
        Description='Carve managed config data',
        Type=param_type,
        Value=value,
        Overwrite=True,
    )
    return response


def aws_ssm_get_parameter(parameter, region=current_region):
    client = boto3.client('ssm', config=boto_config, region_name=region)
    try:
        response = client.get_parameter(Name=parameter, WithDecryption=True)
        value = response['Parameter']['Value']
    except ClientError as e:
        print(f"Error getting paramter {parameter}: {e}")
        value = None
    return value


def aws_ssm_get_parameters(path):
    # return parameters from a path as a dict 
    client = boto3.client('ssm', config=boto_config)
    params = {}
    try:
        paginator = client.get_paginator('get_parameters_by_path')
        for page in paginator.paginate(Path=path, Recursive=True, WithDecryption=True):
            for param in page['Parameters']:
                name = param['Name'].split('/')[-1]
                params[name] = param['Value']
    except ClientError as e:
        pass
    return params

def aws_ssm_delete_parameter(path):
    client = boto3.client('ssm', config=boto_config)
    try:
        response = client.delete_parameter(Name=path)
    except ClientError:
        pass


def aws_invoke_lambda(arn, payload, region=current_region, credentials=None):
    if credentials is None:
        credentials = _get_credentials(arn=arn)

    client = boto3.client(
        'lambda',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )
    response = client.invoke(
        FunctionName=arn,
        Payload=json.dumps(payload)
        )
    data = json.loads(response['Payload'].read().decode('utf-8'))
    return data


def schedule_cron(minutes):
    # return cron fields for a schedule for a self-invocation in 'minutes'
    now = datetime.datetime.now()
    m = now + datetime.timedelta(minutes = minutes)
    cron = f"({m.minute} {m.hour} {m.day} {m.month} ? {m.year})"
    return cron


# def aws_schedule_invoke(name, minutes, payload, context):
#     client = boto3.client('events', config=boto_config)
#     response = client.put_rule(
#         Name=name,
#         ScheduleExpression=schedule_cron(minutes),
#         Description='scheduled event for carve',
#         RoleArn=f"{os.environ['Prefix']}carve-core",
#     )
#     # rule_arn = response['RuleArn']
#     response = client.put_targets(
#         Rule=name,
#         Description='scheduled event for carve',
#         RoleArn=f"{os.environ['Prefix']}carve-core",
#         Targets=[{
#             'Id': 'carve-lambda',
#             'Arn': context.invoked_function_arn,
#             'Input': json.dumps(payload)            
#         }]
#     )


def aws_delete_rule(name):
    client = boto3.client('events', config=boto_config)
    response = client.delete_rule(Name=name)
    return response


def aws_update_tags(resource: str, tags: dict):
    # return all images created by carve in a region
    client = boto3.client('ec2', config=boto_config, region_name=current_region)
    response = client.create_tags(Resources=[resource], Tags=tags)
    return response


def aws_describe_all_carve_images(region):
    # return all images created by carve in a region
    client = boto3.client('ec2', config=boto_config, region_name=region)
    response = client.describe_images(
        Filters=[
            {
                'Name': 'tag-key',
                'Values': ['carve-image-version']
            }
        ])
    return response


def aws_deregister_image(image, region):
    client = boto3.resource('ec2', config=boto_config, region_name=region)
    response = client.deregister_image(ImageId=image)


def aws_delete_snapshot(snapshot, region):
    client = boto3.resource('ec2', config=boto_config, region_name=region)
    response = client.delete_snapshot(SnapshotId=snapshot)


# def aws_invoke_self(arn, payload):
#     client = boto3.client('lambda', config=boto_config)
#     response = client.invoke(
#         FunctionName=arn,
#         Payload=json.dumps(payload)
#         )
#     data = response['Payload'].read()
#     return data

# def aws_empty_bucket():
#     bucket = os.environ['CarveS3Bucket']
#     client = boto3.client('s3', config=boto_config)
#     paginator = client.get_paginator('list_object_versions')

#     delete_list = []
#     for response in paginator.paginate(Bucket=bucket):
#         if 'DeleteMarkers' in response:
#             for mark in response['DeleteMarkers']:
#                 delete_list.append({'Key': mark['Key'], 'VersionId': mark['VersionId']})

#         if 'Versions' in response:
#             for version in response['Versions']:
#                 delete_list.append({'Key': version['Key'], 'VersionId': version['VersionId']})

#     for i in range(0, len(delete_list), 1000):
#         response = client.delete_objects(
#             Bucket=bucket,
#             Delete={
#                 'Objects': delete_list[i:i+1000],
#                 'Quiet': True
#             }
#         )
#         print(f"purged s3 bucket: {bucket}")

def aws_describe_peers(region, credentials):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    paginator = client.get_paginator('describe_vpc_peering_connections')
    pcxs = []
    for page in paginator.paginate():
        for pcx in page['VpcPeeringConnections']:
            pcxs.append(pcx)
    return pcxs


def aws_describe_availability_zones(region):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region
        )
    response = client.describe_availability_zones()
    return response


def aws_describe_subnets(region, account_id, credentials, subnet_id=None):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )
    try:
        paginator = client.get_paginator('describe_subnets')

        if subnet_id is None:
            pages = paginator.paginate()
        else:
            pages = paginator.paginate(SubnetIds=[subnet_id])

        subnets = []
        for page in pages:
            for subnet in page['Subnets']:
                subnets.append(subnet)
        return subnets

    except ClientError as e:
        print(f"error descibing subnets in {region} in {account_id}: {e}")
        return []


def aws_active_region(region, credentials, account_id):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )
    try:
        client.describe_subnets()
        return True
    except ClientError as e:
        return False



def aws_describe_vpcs(region, credentials, account_id):
    client = boto3.client(
        'ec2',
        config=boto_config,
        region_name=region,
        aws_access_key_id = credentials['AccessKeyId'],
        aws_secret_access_key = credentials['SecretAccessKey'],
        aws_session_token = credentials['SessionToken']
        )

    vpcs = []
    try:
        paginator = client.get_paginator('describe_vpcs')
        vpcs = []
        for page in paginator.paginate():
            for vpc in page['Vpcs']:
                vpcs.append(vpc)
    except ClientError as e:
        print(f"error descibing subnets in {region} in {account_id}: {e}")
        vpcs = []
    return vpcs


def aws_purge_s3_bucket(bucket=os.environ['CarveS3Bucket']):
    client = boto3.resource('s3', config=boto_config)
    print(f"purging bucket: {bucket}") 
    bucket = client.Bucket(bucket)
    try:
        bucket.objects.all().delete()
    except ClientError as e:
        print(f'error purging bucket {bucket}: {e}')

def aws_purge_s3_path(path):
    client = boto3.resource('s3', config=boto_config)
    bucket = client.Bucket(os.environ['CarveS3Bucket'])
    bucket.objects.filter(Prefix=path).delete()


def aws_list_s3_path(path, max_keys=1):
    client = boto3.client("s3")
    response = client.list_objects_v2(
            Bucket=os.environ['CarveS3Bucket'],
            Prefix=path,
            MaxKeys=max_keys)
    return response

def aws_put_bucket_policy(bucket, function_arn):
    client = boto3.client('s3', config=boto_config)
    try:
        response = client.put_bucket_policy(
            Bucket=os.environ['CarveS3Bucket'],
            Policy='policy'
        )
        return response
    except ClientError as e:
        print(f'error putting bucket policy: {e}')



def aws_get_bucket_policy(bucket):
    s3_resource = boto3.resource('s3', config=boto_config)
    try:
        policy = s3_resource.BucketPolicy(bucket)
        return policy
    except ClientError as e:
        print(f'error getting bucket policy for {bucket}: {e}')


def aws_put_bucket_notification(path, function_arn, notification_id="CarveDeploy"):
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
        raise(f'error creating bucket notification: {e}')


def aws_upload_file_s3(key, file_path):
    '''
    writes file_path to the carve s3 bucket
    '''
    client = boto3.client('s3', config=boto_config)

    try:
        # print(f"bucket = {os.environ['CarveS3Bucket']}")
        # print(f"file_path = {file_path}")
        # print(f"key = {key}")
        response = client.upload_file(
            Filename=file_path,
            Bucket=os.environ['CarveS3Bucket'],
            Key=key,
            ExtraArgs={'ACL': 'bucket-owner-full-control'}
            )
        return response
    except ClientError as e:
        print(f's3 error: {e}')
        # logger.exception(f'Failed to write outputs/logs s3 bucket')



# if __name__ == '__main__':
#     main()