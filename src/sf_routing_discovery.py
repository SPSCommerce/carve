import lambdavars
import os
import time
from verify_routing import verify_routing


def lambda_handler(event, context):
    '''
    function to start routing discovery
    '''
    key = f"discovered/routing-discovery-{int(time.time())}.json"
    verify_routing(output_key=key)
    return {"discovered": f"s3://{os.environ['CarveS3Bucket']}/{key}"}


if __name__ == '__main__':
    result = lambda_handler(None, None)
    print(result)
