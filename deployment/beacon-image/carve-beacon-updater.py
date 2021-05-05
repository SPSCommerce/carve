import os
import socket
import json
import ipaddress

'''
Basic socket server to receive data on port 8008
It is used to update the carve config beacon data
Data must be submitted as byte encoded valid json
'''

def socket_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('0.0.0.0', 8008))
        s.listen()
        while True:
            conn, addr = s.accept()
            with conn:
                print('Connected by', addr)
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    result = received(data)
                    if result == 'success':
                        conn.sendall(data)
                    else:
                        conn.sendall(bytes(result.encode()))

def received(data):
    try:
        post = (json.loads(data))
    except:
        post = {}
        result = 'socket did not receive json data'
    # process based on json data
    try:
        if 'beacons' in post:
            beacons = post['beacons'].split(',')
            with open('carve_update.conf', 'a') as file:
                for beacon in beacons:
                    if valid_addr(beacon):
                        file.write(f'{beacon}\n')
                    else:
                        pass
            os.replace('carve_update.conf', 'carve.conf')
            result = 'success'
        else:
            result = f'beacons not in post: {post}'
    except:
        result = 'try exception'
    return result

def valid_addr(ipaddr):
    # validate if string is a valid IP address
    try:
        ip = ipaddress.ip_address(ipaddr)
        return True
    except ValueError:
        return False
    except:
        return False

if __name__ == '__main__':
    socket_server()
