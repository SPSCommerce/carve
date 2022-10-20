import cfnresponse
import json
import boto3

# CloudFormation Custom Resource for VPC Lambda Deletion
#
# CloudFormation has a bug where it takes 20-40 minutes to delete a VPC attached
# Lambda due delays in communication around ENI deletion. To delete Lambdas much
# faster during stack deletion, this custom resource will delete all Lambda 
# functions and SecurityGroups in the same stack with a DeletionPolicy of Retain. 
# This makes deleting the resources extremely fast, while still being part of the 
# stack deletion.
#
# CloudFormation Bug:
# https://github.com/serverless/serverless/issues/5008


def lambda_handler(event, context):
    print('REQUEST RECEIVED:\n' + json.dumps(event))
    responseData = {}

    if event['RequestType'] == 'Create':
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        return

    if event['RequestType'] == 'Delete':
        lambda_client = boto3.client('lambda')
        cf_client = boto3.client('cloudformation')
        ec2_client = boto3.client('ec2')
        try:
            # delete all lambdas with retain policy
            stack_resources = cf_client.describe_stack_resources(StackName=event['StackId'])['StackResources']
            template = cf_client.get_template(StackName=event['StackId'])
            print('Looking for lambdas with a DeletionPolicy of Retain to delete')
            for resource in template['TemplateBody']['Resources']:
                if template['TemplateBody']['Resources'][resource]['Type'] == 'AWS::Lambda::Function':
                    policy = template['TemplateBody']['Resources'][resource].get('DeletionPolicy', '')
                    if policy == 'Retain':
                        print(f"Found lambda with a DeletionPolicy of Retain: {resource}")
                        for stack_resource in stack_resources:
                            if stack_resource['LogicalResourceId'] == resource:
                                print(f"Deleting lambda function: {stack_resource['PhysicalResourceId']}")
                                lambda_client.delete_function(FunctionName=stack_resource['PhysicalResourceId'])
                                break
            # next, delete security groups with retain policy
            print('Looking for SecurityGroups with a DeletionPolicy of Retain to delete')
            for resource in template['TemplateBody']['Resources']:
                if template['TemplateBody']['Resources'][resource]['Type'] == 'AWS::EC2::SecurityGroup':
                    policy = template['TemplateBody']['Resources'][resource].get('DeletionPolicy', '')
                    if policy == 'Retain':
                        print(f"Found security group with a DeletionPolicy of Retain: {resource}")
                        for stack_resource in stack_resources:
                            if stack_resource['LogicalResourceId'] == resource:
                                # find all ENIs attached to the security group
                                print("Finding ENIs attached to security group to delete first")
                                enis = ec2_client.describe_network_interfaces(
                                    Filters=[{'Name': 'group-id', 'Values': [stack_resource['PhysicalResourceId']]}])['NetworkInterfaces']
                                # delete all ENIs attached to the security group
                                for eni in enis:
                                    print(f"Deleting ENI: {eni['NetworkInterfaceId']}")
                                    ec2_client.delete_network_interface(NetworkInterfaceId=eni['NetworkInterfaceId'])
                                # delete security group
                                print(f"Deleting security group: {stack_resource['PhysicalResourceId']}")
                                ec2_client.delete_security_group(GroupId=stack_resource['PhysicalResourceId'])
                                break
            print("Finished deleting resources")

        except Exception as e:
            print(e)
            responseData = {'error': str(e)}
            cfnresponse.send(event, context, cfnresponse.FAILED, responseData)
            return

    cfnresponse.send(event, context, cfnresponse.SUCCESS, responseData)
    return
