#!/bin/bash

# update AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
./aws/install

# install CFN flip to convert CFN YML to JSON 
pip install cfn_flip

###
###  REPLACE LOGIC IMMEDIATELY BELOW BY DETERMINING GITSHA OF CURRENTLY DEPLOYED STACK INSTEAD
###

GITHUBCURL="https://api.github.com/repos/anotherhobby/carve/commits"
GITTOKEN=$(aws secretsmanager get-secret-value --secret-id $GIT_TOKEN | jq -r '.SecretString' | jq -r '.token')
LATESTSHA=$(curl --location --request GET $GITHUBCURL --header "Authorization: Bearer ${GITTOKEN}" | jq -r '.[1].sha')

# # clean up previous deployment files
echo "cleaning up prevous deployments"
aws s3 rm s3://$DEPLOYMENT_BUCKET/requirements_packages/ --recursive --exclude "${LATESTSHA}/*"
aws s3 rm s3://$DEPLOYMENT_BUCKET/lambda_packages/ --recursive --exclude "${LATESTSHA}/*"
aws s3 rm s3://$DEPLOYMENT_BUCKET/step_functions/ --recursive --exclude "${LATESTSHA}/*"

# upload deployment state machine definitions
echo "uploading state machine definitions to S3"
aws s3 sync "$BUILDPATH/deployment/step_functions" s3://$DEPLOYMENT_BUCKET/step_functions/$GITSHA/

# upload beacon image code to S3
echo "uploading beacon image code to S3"
aws s3 sync "$BUILDPATH/deployment/beacon-image" s3://$DEPLOYMENT_BUCKET/beacon-image/

# convert the VPC template to JSON for python import (CFN yaml is not valid yaml)
echo "converting carve-vpc-stack.cfn.yml to json"
cfn-flip "$BUILDPATH/src/managed_deployment/carve-vpc-stack.cfn.yml" \
    "$BUILDPATH/src/managed_deployment/carve-vpc-stack.cfn.json"

# package lambda
echo "packaging lambda"
cd "$BUILDPATH/src"
zip -r "package.zip" * > /dev/null

# upload package to S3
echo "uploading lambda package to S3"
aws s3 cp "package.zip" \
    s3://$DEPLOYMENT_BUCKET/lambda_packages/$GITSHA/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION

# package requirements layer
echo "packaging lambda requirements layer"
mkdir -p ../layer/python && cd ../layer
pip install -r ../src/requirements.txt -t ./python
zip -r "reqs_package.zip" * > /dev/null

# upload to S3
echo "uploading requirements lambda layer package to S3"
aws s3 cp "reqs_package.zip" \
    s3://$DEPLOYMENT_BUCKET/lambda_packages/$GITSHA/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION

