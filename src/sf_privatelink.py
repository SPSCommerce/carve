import os
from copy import deepcopy
from aws import *
import time


#
# first seed just a small VPC stack template to the current region to create the VPC
# can just be straight JSON
# resource name must stay the same
# then deploy the primary with the rest of the regions once you have the VPC id
#


def private_link_deployment(deployments, account, regions, routing=False):
    ''' deploy the private link CFN templates '''
    deploy = []
    vpcid = None
    print(f"creating {len(deployments.items())} item deployment input list for deploy-stacks state machine")
    for region, template in deployments.items():
        # if region == current_region:
        #     internet = 'true'
        # else:
        #     internet = 'false'

        stackname = f"{os.environ['Prefix']}carve-managed-privatelink-{region}"
        parameters = [
            # {
            #     "ParameterKey": "InternetAccess",
            #     "ParameterValue": internet
            # },
            {
                "ParameterKey": "CoreRegion",
                "ParameterValue": current_region
            },
            {
                "ParameterKey": "PrivateLinkRegions",
                "ParameterValue": ','.join(regions)
            }
        ]

        # pass in the primary region's VPC id for peering
        if region != current_region:
            if vpcid is None:
                stack = aws_describe_stack(stackname, current_region)
                for output in stack['Outputs']:
                    if output['OutputKey'] == 'VpcId':
                        vpcid = output['OutputValue']
            parameters.append(
                {
                    "ParameterKey": "PeerVpcId",
                    "ParameterValue": vpcid
                })
        
        # if multiple regions, pass in the peer region's VPC id for peering
        if routing:
            parameters.append(
                {
                    "ParameterKey": "CoreRegionPeering",
                    "ParameterValue": "true"
                })

        # add this region to the deployment
        deploy.append({
            "StackName": stackname,
            "Parameters": parameters,
            "Account": account,
            "Region": region,
            "Template": template
        })

    print(f"deploy list: {deploy}")

    return deploy


def privatelink_template(region, second_octet, deploy_accounts, azs):
    template_file = f"{os.path.dirname(__file__)}/managed_deployment/private-link.cfn.json"
    
    with open(template_file) as f:
        template = json.load(f)

    print(f"{region} template: creating private link CFN template for region")

    template['Resources']['PrivateLinkVPC']['Properties']['CidrBlock'] = f"10.{second_octet}.0.0/24"
    print(f"{region} template: added CidrBlock 10.{second_octet}.0.0/24 to PrivateLinkVPC")

    template['Resources']['PublicNATSubnet']['Properties']['CidrBlock'] = f"10.{second_octet}.0.0/28"
    print(f"{region} template: added CidrBlock 10.{second_octet}.0.0/28 to PublicNATSubnet")

    template['Resources']['AutoScalingGroup']['Properties']['MaxSize'] = len(azs)
    template['Resources']['AutoScalingGroup']['Properties']['DesiredCapacity'] = len(azs)
    print(f"{region} template: set MaxSize and DesiredCapacity on AutoScalingGroup to {len(azs)}")

    az_count = 1
    for az, azid in azs.items():
        # create one private /28 subnet for each AZ
        fourth_octet = az_count * 16
        PrivateSubnet = deepcopy(template['Resources']['PrivateSubnet'])
        PrivateSubnet['Properties']['CidrBlock'] = f"10.{second_octet}.0.{fourth_octet}/28"
        PrivateSubnet['Properties']['AvailabilityZone'] = az
        PrivateSubnet['Properties']['Tags'] = [
            {
                "Key": "Name",
                "Value": f"{os.environ['Prefix']}carve-privatelink-{azid}"
            }]

        # add private subnet to template
        PrivateSubnetName = f"PrivateSubnet{az_count}"
        template['Resources'][PrivateSubnetName] = PrivateSubnet
        print(f"{region} template: added CidrBlock 10.{second_octet}.0.{fourth_octet}/28 to {PrivateSubnetName}")

        # use the first subnet for AWS SSM interface endpoints
        if az_count == 1:
            template['Resources']['SSMInterfaceEndpoint']['Properties']['SubnetIds'] = [{"Ref": PrivateSubnetName}]
            template['Resources']['SSMMessagesInterfaceEndpoint']['Properties']['SubnetIds'] = [{"Ref": PrivateSubnetName}]

        # create routes for each subnet
        RoutingTableAssociation = deepcopy(template['Resources']['RoutingTableAssociation'])
        RoutingTableAssociation['Properties']['SubnetId'] = {"Ref": PrivateSubnetName}
        RoutingTableAssociationName = f"RoutingTableAssociation{az_count}"
        template['Resources'][RoutingTableAssociationName] = RoutingTableAssociation
        print(f"{region} template: added SubnetId to {RoutingTableAssociationName}")

        # add the subnet to the NLB and ASG
        template['Resources']['EndpointServiceNLB']['Properties']['Subnets'].append({"Ref": PrivateSubnetName})
        template['Resources']['AutoScalingGroup']['Properties']['VPCZoneIdentifier'].append({"Ref": PrivateSubnetName})
        print(f"{region} template: added {PrivateSubnetName} to EndpointServiceNLB and AutoScalingGroup")

        # increment the octet math
        az_count += 1

    # remove duplicated resources
    del template['Resources']['PrivateSubnet']
    del template['Resources']['RoutingTableAssociation']

    # add carve role ARN to the endpoint permissions for every account in the deployment
    for account in deploy_accounts:
        role = f"arn:aws:iam::{account}:role/{os.environ['Prefix']}carve-org-role"
        template['Resources']['EndpointServicePermissions']['Properties']['AllowedPrincipals'].append(role)
    
    print(f"{region} template: added carve role ARN from {len(deploy_accounts)} accounts to EndpointServicePermissions")

    print(f"{region} template: rendering complete for private link CFN template for region")

    return template


def add_peer_routes(template, deploy_regions):
    ''' add routes to the peered regions in CFN '''
    stackname = f"{os.environ['Prefix']}carve-managed-privatelink-{current_region}"
    for region in deploy_regions:
        if region == current_region:
            continue
        outputs = aws_get_stack_outputs_dict(stackname, region)
        if 'VpcPeeringConnectionId' in outputs:
            print(f"{current_region}: adding route to {current_region} template for peered region: {region}")

            # duplicate the VPCPeeringRoute resource and add the route
            VPCPeeringRoute = deepcopy(template['Resources']['VPCPeeringRoute'])
            VPCPeeringRoute['Properties']['VpcPeeringConnectionId'] = outputs['VpcPeeringConnectionId']
            VPCPeeringRoute['Properties']['DestinationCidrBlock'] = outputs['VPCCidrBlock']
            VPCPeeringRouteName = f"VPCPeeringRoute{aws_region_dict[region]}"
            template['Resources'][VPCPeeringRouteName] = VPCPeeringRoute

            print(f"{current_region}: added route to {region} vpc using {outputs['VpcPeeringConnectionId']} with Cidr {outputs['VPCCidrBlock']}")
        else:
            print(f"{current_region}: failed to add route to {region} vpc")

    # remove the VPCPeeringRoute template resource
    del template['Resources']['VPCPeeringRoute']
    print(f"{current_region}: completed adding routes for peered regions: {deploy_regions}")

    return template

def discover_privatelink_services(deploy_regions):
    print(f"discovering privatelink services in regions: {deploy_regions}")
    services = []
    for region in deploy_regions:
        outputs = aws_get_stack_outputs_dict(f"{os.environ['Prefix']}carve-managed-privatelink", region)
        if 'EndpointService' in outputs:
            print(f"{region}: found privatelink service: {outputs['EndpointService']}")
            service_data = aws_describe_vpc_endpoint_service_configuration(outputs['EndpointService'], region)
            services.append(service_data['ServiceName'])
        else:
            print(f"{region}: failed to find privatelink service")
    
    return services
