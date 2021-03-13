#!/bin/bash

# update AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
./aws/install

GITHUBCURL="https://api.github.com/repos/anotherhobby/carve/commits"
GITTOKEN=$(aws secretsmanager get-secret-value --secret-id $GIT_TOKEN | jq -r '.SecretString' | jq -r '.token')
LATESTSHA=$(curl --location --request GET $GITHUBCURL --header "Authorization: Bearer ${GITTOKEN}" | jq -r '.[1].sha')

# # clean up previous deployment files
echo "cleaning up prevous deployments"
aws s3 rm s3://$DEPLOYMENT_BUCKET/carve/packages/ --recursive --exclude "${LATESTSHA}/*"
aws s3 rm s3://$DEPLOYMENT_BUCKET/carve/layer_packages/ --recursive --exclude "${LATESTSHA}/*"
aws s3 rm s3://$DEPLOYMENT_BUCKET/carve/graph_layer_packages/ --recursive --exclude "${LATESTSHA}/*"
aws s3 rm s3://$DEPLOYMENT_BUCKET/carve/graph_layer_package/ --recursive --exclude "${LATESTSHA}/*"

# future
# aws s3 rm s3://$DEPLOYMENT_BUCKET/requirements_packages/ --recursive --exclude "${LATESTSHA}/*"
# aws s3 rm s3://$DEPLOYMENT_BUCKET/lambda_packages/ --recursive --exclude "${LATESTSHA}/*"
aws s3 rm s3://$DEPLOYMENT_BUCKET/step_functions/ --recursive --exclude "${LATESTSHA}/*"

# upload deployment state machine definition
echo "uploading state machine definitions to S3"
aws s3 cp "$BUILDPATH/deployment/steps-carve-deployment.json" \
    s3://$DEPLOYMENT_BUCKET/step_functions/$GITSHA/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION
aws s3 cp "$BUILDPATH/deployment/steps-carve-discovery.json" \
    s3://$DEPLOYMENT_BUCKET/step_functions/$GITSHA/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION

# copy carve IAM template into deployment folder in lambda src
cp "$BUILDPATH/deployment/carve-iam.cfn.yml" "$BUILDPATH/src/deployment/"

# package lambda
echo "packaging lambda"
cd "$BUILDPATH/src"

# pip install -r requirements.txt -t .
zip -r "package.zip" * > /dev/null

# upload package to S3
echo "uploading lambda package to S3"
aws s3 cp "package.zip" \
    s3://$DEPLOYMENT_BUCKET/lambda_packages/$GITSHA/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION

# ######## only need to run when python requirments change/update
echo "packaging lambda requirements layer"
mkdir -p ../layer/python && cd ../layer
pip install -r ../src/requirements.txt -t ./python
zip -r "requirements_package.zip" * > /dev/null
# upload to S3
echo "uploading requirements lambda layer package to S3"
aws s3 cp "requirements_package.zip" \
    s3://$DEPLOYMENT_BUCKET/requirements_packages/$GITSHA/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION

