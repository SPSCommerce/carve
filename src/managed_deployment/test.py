import concurrent.futures
import os
import time
import urllib3

def threaded_test(addr):
    http = urllib3.PoolManager()
    try:
        r = http.request('GET', f'http://{addr}/up', timeout={os.environ['BeaconTimeout']})
        if r.status == 200:
            result = 'pass'
        else:
            result = 'fail'
    except:
        result = 'fail'
    return {addr: result}

def lambda_handler(event, context):
    if len(event) < 1:
        print('no payload to test')
        return None
    else:
        print(f'testing endpoints: {event}')
    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for addr in event:
            futures.append(executor.submit(threaded_test, addr=addr))
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    print(results)
    test_result = {f"{os.environ[VpcSubnetId]}": results}
    return test_result