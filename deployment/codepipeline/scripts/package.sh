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
aws s3 rm s3://$DEPLOYMENT_BUCKET/packages/ --recursive --exclude "${LATESTSHA}/*"

# upload deployment state machine definition
echo "uploading state machine definition to S3"
aws s3 cp "$BUILDPATH/deployment/steps-carve-deployment.json" \
    s3://$DEPLOYMENT_BUCKET/carve/packages/$GITSHA/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION

# package lambda requirements
echo "packaging lambda requirements"
cd "$BUILDPATH/src"
# python3.8 -m pip install --upgrade pip 
pip install -r requirements.txt -t .
zip -r "package.zip" * > /dev/null

# upload package to S3
echo "uploading lambda package to S3"
aws s3 cp "package.zip" \
    s3://$DEPLOYMENT_BUCKET/carve/packages/$GITSHA/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION

# ONE TIME RUN: package lambda layer requirements
echo "packaging lambda layer requirements"
mkdir ../layer
cd ../layer
mkdir python
# python3.8 -m pip install --upgrade pip 
pip install -r ../src/graph_layer_requirements.txt -t ./python
zip -r "graph_layer_package.zip" * > /dev/null
# upload to S3
echo "uploading lambda layer package to S3"
aws s3 cp "graph_layer_package.zip" \
    s3://$DEPLOYMENT_BUCKET/carve/graph_layer_package/ \
    --metadata GIT_SHA=$CODEBUILD_SOURCE_VERSION

