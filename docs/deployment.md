# Carve Deployment

The deployment of Carve resources is split into two categories: **pipeline** and **managed**. The CodePipeline is deployed first as a CloudFormation stack. The pipeline will deploy the Carve core lambda and it's required resources. The managed deployments are the subnet beacons and their resources that the Carve core lambda deploys and manages thru CloudFormation stacks.

## Organization CloudFormation StackSet for IAM

Carve requires an IAM role to be deployed across the Organization via a StackSet. You will need to deploy the [carve-org-stackset.cfn.yml](deployment/carve-org-stackset.cfn.yml) as a StackSet, targeting your entire AWS Organization.

## Pipeline Deployment

Pipeline Prerequisites:

* If you are deploying the IAM stackset into an AWS account that is not your Organization root account, you will need to enable the account as a [Cloudformation Delegated Administrator](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacksets-orgs-enable-trusted-access.html)
* CodePipeline requires a GitHub OAuth token to pull from the repository. If you don't already have one, you will need to create an OAuth token on GitHub for CodePipeline and put it in AWS Secrets Manager for CodePipeline to access. A template to create the secret resource is provided here: [pipeline-secret-github.yml](templates/pipeline-secret-github.yml)

To get started with Carve, deploy the CodePipeline CloudFormation stack template [deployment-pipeline.cfn.yml](deployment/deployment-pipeline.cfn.yml) into a dedicated account in your AWS Organization. 

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

## Pipeline Actions & Resources

The Carve CodePipeline template deploys 