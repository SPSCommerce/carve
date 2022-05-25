import concurrent.futures
import urllib3

# import json

'''
this subnet lambda code file is kept separate from the VPC stack CFN template for easier 
editing/testing and is injected into the CFN template at deploy time by carve-core lambda
'''

def http_call(beacon):
    print(f'getting results for beacon: {beacon}')
    http = urllib3.PoolManager()
    result = None
    try:
        r = http.request('GET', beacon, retries=False, timeout=1.0)
        if r.status == 200:
            result = {'beacon': beacon, 'result': 'up'}
        else:
            result = {'beacon': beacon, 'result': 'down'}
    except urllib3.exceptions.ConnectTimeoutError:
        print(f'ERROR: ConnectTimeoutError — {beacon}')
        result = {'beacon': beacon, 'result': 'down', 'error': 'ConnectTimeoutError'}
    except urllib3.exceptions.MaxRetryError:
        print(f'ERROR: MaxRetryError — {beacon}')
        result = {'beacon': beacon, 'result': 'down', 'error': 'MaxRetryError'}
    except urllib3.exceptions.HTTPError:
        print(f'ERROR: HTTPError — {beacon}')
        result = {'beacon': beacon, 'result': 'down', 'error': 'HTTPError'}

    print(result)
    return result


def test_beacons(beacons):

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=1000) as executor:
        futures = []
        for beacon in beacons:
            futures.append(executor.submit(http_call, beacon=beacon))
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    return results


def lambda_handler(event, context):
    print(event)
    if event['action'] == 'beacons':
        return test_beacons(event['beacons'])

    elif event['action'] == 'results':
        result = None
    elif event['action'] == 'update':
        result = None

    return result

if __name__ == '__main__':
    beacon = 'https://www.google.com'
    results = http_call(beacon)
    print(results)