import lambdavars
import os
import time
from verify_routing import verify_routing, vpc_routing_report
from aws import aws_copy_s3_object


def lambda_handler(event, context):
    '''
    function to start routing discovery
    '''
    output = f"discovered/routing-discovery-{int(time.time())}.json"
    discovered = verify_routing(output_key=output)
    print(f"routing discovery complete, saved to: {discovered}")
    print(f"copy routing discovery to: s3://{os.environ['CarveS3Bucket']}/discovered/last-routing-discovery.json")
    aws_copy_s3_object(f"{output}", f"discovered/last-routing-discovery.json")

    if 'report' in event and event['report'] == True:
        report = vpc_routing_report(output)
    else:
        report = None

    return {"discovered": f"{discovered}", "report": report}

if __name__ == '__main__':
    event = {'report':True}
    result = lambda_handler(event, None)
    # print(result)
