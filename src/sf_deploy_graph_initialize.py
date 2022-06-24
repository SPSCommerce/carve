from re import A
import lambdavars
import networkx as nx
import concurrent.futures
from networkx.readwrite import json_graph
import json
import os
from carve import load_graph, unique_node_values
from aws import *
import time


def lambda_handler(event, context):

    print(event)

    if 'graph' in event:
        key = event['graph']
    elif 'graph' in event['Input']:
        key = event['Input']['graph']
    else:
        raise Exception("no graph provided in input. input format: {'input': {'graph': 'carve-privatelink-graph.json'}}")

    try:
        G = load_graph(key, local=False)
        print(f"successfully loaded graph: {key}")
    except:
        raise Exception(f"failed to load graph: {key}")

    # move deployment artifact to deploy_active/ path
    filename = key.split('/')[-1]
    deploy_key = f"deploy_active/{filename}"
    aws_purge_s3_path("deploy_active/")
    aws_copy_s3_object(key, deploy_key)

    # # remove the old deployment artifact from s3
    # if cleanup:
    #     aws_delete_s3_object(key, current_region)

    print(f"deploying uploaded graph: {key}")

    # create deploy buckets in all required regions for deployment files
    regions = unique_node_values(G, 'Region')
    if current_region in regions:
        regions.remove(current_region)

    deploy_buckets = []

    key = "managed_deployment/carve-managed-bucket.cfn.yml"
    with open(key) as f:
        template = f.read()

    aws_put_direct(template, key)

    for r in regions:
        stackname = f"{os.environ['Prefix']}carve-managed-bucket-{r}"
        parameters = [
            {
                "ParameterKey": "OrgId",
                "ParameterValue": os.environ['OrgId']
            },
            {
                "ParameterKey": "Prefix",
                "ParameterValue": os.environ['Prefix']
            },
            {
                "ParameterKey": "UniqueId",
                "ParameterValue": os.environ['UniqueId']
            }
        ]
        deploy_buckets.append({
            "StackName": stackname,
            "Parameters": parameters,
            "Account": context.invoked_function_arn.split(":")[4],
            "Region": r,
            "Template": key
        })

    # return deploy_buckets
    print(f"creating buckets: {deploy_buckets}")

    return json.dumps(deploy_buckets, default=str)




# if __name__ == '__main__':
#     lambda_handler(event, context)