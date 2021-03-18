import os
from c_aws import *
from crhelper import CfnResource

### CFN custom resource setup the Carve bucket for deply
helper = CfnResource()

def custom_resource_entrypoint(event, context):
    # need to deal with DeleteStackCleanup vs SetupCarveBucket
    helper(event, context)

@helper.create
def deploy_CfnCreate(event, context):
    if 'DeployEventPath' in event['ResourceProperties']:
        path = event['ResourceProperties']['DeployEventPath']
        notification_id = event['ResourceProperties']['NotificationId']
        aws_create_s3_path(path)
        aws_put_bucket_notification(path, notification_id, context.invoked_function_arn)
        helper.Data['Path'] = path
        helper.Data['Notification'] = notification_id


@helper.update
def deploy_CfnUpdate(event, context):
    deploy_CfnDelete(event, context)
    deploy_CfnCreate(event, context)


@helper.delete
def deploy_CfnDeletePoll(event, context):
    if len(aws_states_list_executions(os.environ['CarveDeployStepFunction'])) > 0:
        return None
    else:
        return True


@helper.poll_delete
def deploy_CfnDelete(event, context):
    # elif 'OrganizationsId' in event['ResourceProperties']:
    #     delete_carve_endpoints(event, context)
    # pass
    aws_delete_bucket_notification()
    aws_purge_s3_bucket()
    return True
