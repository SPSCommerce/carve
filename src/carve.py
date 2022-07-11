import lambdavars
import time
import os

from networkx.readwrite import json_graph

from utils import get_deploy_key, load_graph
from verify_routing import verify_routing

'''
Left off with errors from this current lambda
not getting graph in input verify_routing

'''



def lambda_handler(event, context):
    '''
    respond to cloudwatch events and execute carve verifications
    '''

    print(event)
    if 'detail-type' in event:
        # verify this was launched by the carve results event, else exit
        if event['source'] == 'aws.events':
            cw_rule = event['resources'][0].split('rule/')[-1]
            if cw_rule != f"{os.environ['Prefix']}carve-results":
                print('Not a carve results event')
                return

            print(f"running carve route verification")

            # verify current routes for deployed graph
            current_routes = verify_routing()

            # load the verification results as a graph
            V = json_graph.node_link_graph(current_routes)
            name = f"verification-{int(time.time())}"
            V.graph['Name'] = name

            # load the deployed graph to compare to the verification results
            deploy_key = get_deploy_key(last=True)
            if not deploy_key:
                raise Exception('No graph provided or found')
            else:
                G = load_graph(deploy_key, local=False)


            # compare the two graphs
            print(f"comparing {G.graph['Name']} to {V.graph['Name']}")
            diffs = diff_links(V, G)

            if len(diffs) > 0:
                verification = "failed" 
            else:
                verification = "passed" 
            print({"verification": verification, "results": diffs})


def diff_links(A, B, repeat=True, diffs=[]):
    '''
    Compare the links between two graphs and return any differences
    Graphs are assumed to have the same nodes
    Returns a list of dicts containing differences
    '''
    for edge in A.edges() - B.edges():
        diff = {
            'status': 'present',
            'graph': A.graph['Name'],
            'source': A.nodes().data()[edge[0]],
            'target': A.nodes().data()[edge[1]]
            }
        diffs.append(diff)

    if repeat:
        diffs = diff_links(B, A, repeat=False, diffs=diffs)
        return diffs

    else:
        return diffs


# def diff_nodes(A, B, repeat=True, diffs=[]):
#     '''
#     Compare the nodes between two graphs and return any differences
#     Returns a list of dicts containing differences
#     '''
#     for node in A.nodes() - B.nodes():
#         diff = {
#             'status': 'present',
#             'graph': A.graph['Name'],
#             'node': A.nodes().data()[node],
#             }
#         diffs.append(diff)
#     if repeat:
#         diff_links(B, A, repeat=False, diffs=diffs)
#     else:
#         return diffs


# main function to test lambda
if __name__ == '__main__':
    event = {'version': '0', 'id': '0d4a3544-ea7e-1478-e85d-647144861aa7', 'detail-type': 'Scheduled Event', 'source': 'aws.events', 'account': '816849209215', 'time': '2022-06-24T21:33:28Z', 'region': 'us-east-1', 'resources': ['arn:aws:events:us-east-1:816849209215:rule/nonprod-carve-results'], 'detail': {}}
    lambda_handler(event, lambdavars.lambda_context)