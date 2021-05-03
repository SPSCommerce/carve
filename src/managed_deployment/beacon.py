import urllib3
import socket
import json

def hc(beacon):
    http = urllib3.PoolManager()
    try:
        r = http.request('GET', f'http://{beacon}/up', timeout=0.1)
        if r.status == 200:
            result = 'up'
        else:
            result = 'down'
    except:
        result = 'down'
    return result

def get_results(beacon):
    print(f'getting results for beacon: {beacon}')
    http = urllib3.PoolManager()
    result = None
    try:
        r = http.request('GET', f'http://{beacon}/results', timeout=0.1)
        ts = http.request('GET', f'http://{beacon}/ts', timeout=0.1)
        if r.status == 200:
            result = {'status': r.status, 'result': r.data, 'health': hc(beacon), 'ts': ts.data}
        else:
            result = {'status': r.status, 'result': 'error', 'health': hc(beacon)}
    except urllib3.exceptions.ConnectTimeoutError:
        result = {'status': 'ConnectTimeoutError', 'result': 'timeout', 'health': hc(beacon)}
    except urllib3.exceptions.MaxRetryError:
        result = {'status': 'MaxRetryError', 'result': 'timeout', 'health': hc(beacon)}
    except urllib3.exceptions.HTTPError as e:
        result = {'status': 'HTTPError', 'result': 'timeout', 'health': hc(beacon)}
    print(result)
    return result

def update_beacon(beacon, beacons):
    config = json.dumps({'beacons': beacons}).encode()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((beacon, 8008))
        s.sendall(config)
        data = s.recv(1024)
    if data == config:
        print('beacon update successful')
    else:
        print(f'ERROR: beacon update confirmation failed for {beacon}')
        print(f'submitted: {config}')
        print(f'returned: {data}')

def lambda_handler(event, context):
    print(event)
    if event['action'] == 'results':
        result = get_results(event['beacon'])
    elif event['action'] == 'update':
        result = update_beacon(event['beacon'], event['beacons'])
    return result

