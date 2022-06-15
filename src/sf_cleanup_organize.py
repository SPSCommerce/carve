import json


def lambda_handler(event, context):
    '''
    organize incoming payloads from a step function's map output to a single list
    and return the list
    '''
    input = event['Payload']['Input']
    results = []
    for item in input:
        for each in item['Payload']:
            results.append(each)

    # return json to step function
    return json.dumps(results, default=str)



