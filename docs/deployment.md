# Carve Deployment

The deployment of Carve resources is split into two categories: **pipeline** and **managed**. The CodePipeline is deployed first as a CloudFormation stack. The pipeline will deploy the Carve core lambda and it's required resources. The managed deployments are the subnet beacons and their resources that the Carve core lambda deploys and manages thru CloudFormation stacks.

## Account Considerations

Carve can be deployed into its own isolated account in your AWS Organization, or it can be deployed directly into the Organization root account. At the time this was written, CodePipeline did not (an may not still) support StackSet deployments from delegated accounts. Because of this, there are two pipeline CloudFormation templates, one for each use case. Carve requires an IAM role to be deployed across the Organization via a StackSet, which is included in the pipeline if you deploy into the root account. If you deploy Carve into it's own account, you will need to deploy the [Carve-org-stackset.cfn.yml](deployment/Carve-org-stackset.cfn.yml) template manually as a StackSet from the delegate or root account, targeting your entire AWS Organization.

## Pipeline Deployment

Pipeline Prerequisites:

* If you are deploying the IAM stackset into an AWS account that is not your Organization root account, you will need to enable the account as a [Cloudformation Delegated Administrator](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacksets-orgs-enable-trusted-access.html)
* The Carve pipline requires an S3 bucket. Including a bucket resource in the pipeline stack will make the stack unable to be deleted until the bucket is emptied. Because of this, a CloudFormation template is provided here to deploy a bucket first:  [Carve-deploy-bucket.cfn.yml](deployment/codepipeline/Carve-deploy-bucket.cfn.yml)
* CodePipeline requires a GitHub OAuth token to pull from the repository. If you don't already have one, you will need to create an OAuth token on GitHub for CodePipeline and put it in AWS Secrets Manager for CodePipeline to access. A template to create the secret resource is provided here: [Carve-secret-github.yml](deployment/codepipeline/Carve-secret-github.yml)

To get started with Carve, deploy the either the CodePipeline stack template [Carve-pipeline-root.cfn.yml](deployment/codepipeline/Carve-pipeline-root.cfn.yml) in your AWS Organization root account, or deploy the CloudFormation template [Carve-pipeline-delegate.cfn.yml](deployment/codepipeline/Carve-pipeline-delegate.cfn.yml) for delegate accounts into its own account. 

The parameters for the CodePipeline stack templates are outlined below:

Parameter|Type|Default|Required|Purpose
----|----|----|----|----
GitHubOAUTHTokenASMPath|String||yes|GitHubServiceOAUTHToken path in Secrets Manager
DeployBucket|String||yes|The name of the S3 bucket to use for CodePipeline
OrgId|String||yes|Your AWS Organizations Id
RootOU|String||yes|AWS Organizations Root OU Id (not to be confused with the OrgId)
Prefix|String||no|All Carve AWS resources and stacknames will be prefixed with this value if provided
UniqueId|String||no|Carve creates S3 buckets in it's account using the naming convention `{prefix}Carve-managed-bucket-{uniqueid}-region`. To avoid global naming conflicts, it will use your AWS Organization ID as the unique id, but you may provide a different value if you wish.
ImageBuilderExistingSubnetId|String||no|EC2 Image Builder instnaces must have Internet access. Carve will create a small VPC with a public subnet for this use if they are not provided.
ImageBuilderExistingVpcId|String||no|EC2 Image Builder instnaces must have Internet access. Carve will create a small VPC with a public subnet for this use if they are not provided.
ImageBuilderVpcCIDR|String|10.0.0.0/24|no|IP range (CIDR notation) for new VPC if Carve is creating the Image Builder VPC
ImageBuilderPublicSubnetCIDR|String|10.0.0.0/28|no|IP range (CIDR notation) for subnet in new VPC if Carve is creating the Image Builder VPC

## Pipeline Resources

The Carve CodePipeline template deplo