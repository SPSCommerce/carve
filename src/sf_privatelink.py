import os
from copy import deepcopy
from aws import *
import time


def private_link_deployment(deployments, account, regions, routing=False):
    ''' deploy the private link CFN templates '''
    deploy = []
    vpcid = None
    print(f"creating {len(deployments.items())} item deployment input list for deploy-stacks state machine")
    for region, template in deployments.items():
        if region == current_region:
            internet = 'true'
        else:
            internet = 'false'

        stackname = f"{os.environ['Prefix']}carve-managed-privatelink"
        parameters = [
            {
                "ParameterKey": "InternetAccess",
                "ParameterValue": internet
            },
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
        # else:
        #     parameters.append(
        #         {
        #             "ParameterKey": "MaxSize",
        #             "ParameterValue": 'NONE'
        #         })
        
        # if peeringupdate is true, pass in the peer region's VPC id for peering
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
    # if len(templates.items()) > 0:
    #     name = f"deploying-privatelink-{int(time.time())}"
    #     aws_start_stepfunction(os.environ['DeployStacksStateMachine'], {'Input': deploy}, name)
    return deploy


def privatelink_template(region, second_octet, deploy_accounts, azs):
    template_file = f"{os.path.dirname(__file__)}/managed_deployment/private-link.cfn.json"
    
    with open(template_file) as f:
        template = json.load(f)

    print(f"creating private link CFN template for region: {region}")

    template['Resources']['PrivateLinkVPC']['Properties']['CidrBlock'] = f"10.{second_octet}.0.0/24"
    print(f"added CidrBlock 10.{second_octet}.0.0/24 to PrivateLinkVPC")

    template['Resources']['PublicNATSubnet']['Properties']['CidrBlock'] = f"10.{second_octet}.0.0/28"
    print(f"added CidrBlock 10.{second_octet}.0.0/28 to PublicNATSubnet")

    template['Resources']['AutoScaleGroup']['Properties']['MaxSize'] = len(azs)
    print(f"Set MaxSize on AutoScaleGroup to {len(azs)}")


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
        print(f"added CidrBlock 10.{second_octet}.0.{fourth_octet}/28 to {PrivateSubnetName}")

        # create routes for each subnet
        RoutingTableAssociation = deepcopy(template['Resources']['RoutingTableAssociation'])
        RoutingTableAssociation['Properties']['SubnetId'] = {"Ref": PrivateSubnetName}
        RoutingTableAssociationName = f"RoutingTableAssociation{az_count}"
        template['Resources'][RoutingTableAssociationName] = RoutingTableAssociation
        print(f"added SubnetId to {RoutingTableAssociationName}")

        # add the subnet to the NLB and ASG
        template['Resources']['EndpointServiceNLB']['Properties']['Subnets'].append({"Ref": PrivateSubnetName})
        template['Resources']['AutoScalingGroup']['Properties']['VPCZoneIdentifier'].append({"Ref": PrivateSubnetName})
        print(f"added {PrivateSubnetName} to EndpointServiceNLB and AutoScalingGroup")

        # increment the octet math
        az_count += 1

    # remove duplicated resources
    del template['Resources']['PrivateSubnet']
    del template['Resources']['RoutingTableAssociation']

    # add carve role ARN to the endpoint permissions for every account in the deployment
    for account in deploy_accounts:
        role = f"arn:aws:iam::{account}:role/{os.environ['Prefix']}carve-org-role"
        template['Resources']['EndpointServicePermissions']['Properties']['AllowedPrincipals'].append(role)
    
    print(f"added carve role ARN from {len(deploy_accounts)} accounts to EndpointServicePermissions")

    print(f"rendering complete for private link CFN template for region: {region}")

    return template

def add_peer_routes(template, deploy_regions):
    ''' add routes to the peered regions in CFN '''
    print(f"adding routes to rendered template for peered regions: {deploy_regions}")
    stackname = f"{os.environ['Prefix']}carve-managed-privatelink"
    for region in deploy_regions:
        stack = aws_describe_stack(stackname, region)
        if stack is not None:
            print(f"adding routes for {region}")
            conn_id = None
            cidr = None
            for output in stack['Outputs']:

                if output['OutputKey'] == 'VpcPeeringConnectionId':
                    conn_id = output['OutputValue']
                elif output['OutputKey'] == 'VPCCidrBlock':
                    cidr = output['OutputValue']

            if conn_id is not None and cidr is not None:
                # duplicate the VPCPeeringRoute resource and add the route
                VPCPeeringRoute = deepcopy(template['Resources']['VPCPeeringRoute'])
                VPCPeeringRoute['Properties']['VpcPeeringConnectionId'] = conn_id
                VPCPeeringRoute['Properties']['DestinationCidrBlock'] = cidr
                VPCPeeringRoute = f"VPCPeeringRoute{aws_region_dict[region]}"
                template['Resources'][VPCPeeringRoute] = VPCPeeringRoute
                print(f"added route for {conn_id} with Cidr {cidr} in {region}")
            else:
                print(f"failed to add route for {region}")

    # remove the VPCPeeringRoute template resource
    del template['Resources']['VPCPeeringRoute']
    print(f"completed adding routes for peered regions: {deploy_regions}")

    return template