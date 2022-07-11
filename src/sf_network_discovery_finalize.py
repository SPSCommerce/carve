import lambdavars

import os
import time

import networkx as nx
from networkx.readwrite import json_graph

from aws import *
from utils import load_graph, save_graph


def lambda_handler(event, context):
    print(event)

    # subnets = aws_s3_list_objects(prefix='discovery/accounts')
    discovered = aws_s3_list_objects(prefix='discovery')

    print(f"discovered subnets in {len(discovered)} accounts")

    # create new graph for all subnets
    name = f"carve-discovered-{int(time.time())}"
    G = nx.Graph(Name=name)

    # Load all org discovered subnets into graph G
    for account in discovered:
        print(f"adding subnets from: {account}")
        S = load_graph(account, local=False)
        G.add_nodes_from(S.nodes.data())

    # push graph to S3
    save_graph(G, f"/tmp/{name}.json")
    aws_upload_file_s3(f'discovered/{name}.json', f"/tmp/{name}.json")

    result = {"discovered": f"s3://{os.environ['CarveS3Bucket']}/discovered/{name}.json"}

    return result


if __name__ == "__main__":
    event = {}
    # event = {}
    result = lambda_handler(event, None)
    print(result)