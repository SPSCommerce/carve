from http import client
import boto3

client = boto3.client('ssm', region_name='us-east-1')
cv = client.get_parameter(Name='/test-carve-resources/carve-image-builder-version')
nv = int(cv['Parameter']['Value']) + 1
client.put_parameter(
    Name='/test-carve-resources/carve-image-builder-version',
    Value=str(nv),
    Type='String',
    Overwrite=True
    )
print(nv)