# import pylab as plt
import os
import time

import networkx as nx
from botocore.exceptions import ClientError
from networkx.readwrite import json_graph

from aws import *
from carve import (carve_results, carve_role_arn, get_subnet_beacons,
                   load_graph, save_graph, update_carve_beacons)


def discover_subnets(region, account_id, account_name, credentials):
    ''' get VPCs in account/region, returns nx.Graph object of VPC nodes'''


    # create graph structure for VPCs
    G = nx.Graph()

    # get all non-default VpcIds owned by this account
    vpcids = []

    vpcs = aws_describe_vpcs(region, credentials, account_id)
    for vpc in vpcs:

        if vpc['OwnerId'] != account_id:
            # don't add shared VPCs
            continue

        if vpc['IsDefault']:
            # don't add default VPCs
            continue

        vpcids.append(vpc['VpcId'])


    for subnet in aws_describe_subnets(region, credentials, account_id):

        # ignore default VPCs and shared subnets
        if subnet['VpcId'] not in vpcids:
            continue

        # get subnet name from tag if available
        name = subnet['SubnetId']
        if 'Tags' in subnet:
            for tag in subnet['Tags']:
                if tag['Key'] == 'Name':
                    name = tag['Value']
                    break

        if name == f"{os.environ['Prefix']}carve-imagebuilder-public-subnet":
            # do not discover carve image builder subnet
            continue

        # create graph nodes
        G.add_node(
            subnet['SubnetId'],
            Name=name,
            Account=account_id,
            AccountName=account_name,
            Region=region,
            CidrBlock=vpc['CidrBlock'],
            VpcId=subnet['VpcId']
            )

    return G
 

def discover_resources(resource, region, account_id, account_name, credentials):
    # if resource == 'vpcs':
    #     G = discover_vpcs(region, account_id, account_name, credentials)
    # if resource == 'pcxs':
    #     G = discover_pcxs(region, account_id, account_name, credentials)

    G = discover_subnets(region, account_id, account_name, credentials)
    
    name = f'{resource}_{account_id}_{region}_{int(time.time())}'
    G.graph['Name'] = name

    save_graph(G, f"/tmp/{name}.json")

    aws_upload_file_s3(f'discovery/{name}.json', f"/tmp/{name}.json")

    return {resource: f'discovery/{name}.json'}



def lambda_handler(event, context):
    discovered = []

    print(event)

    # account_id = event['Input']['account_id']
    # account_name = event['Input']['account_name']
    # regions = event['Input']['regions']

    # credentials = aws_assume_role(carve_role_arn(account_id), f"carve-discovery")

    # # for resource in ['vpcs', 'pcxs']:
    # for region in regions:
    #     discovered.append(discover_resources('subnets', region, account_id, account_name, credentials))

    # return {'Discovered': True}



if __name__ == "__main__":
    event = {}
    result = lambda_handler(event, None)
    print(json.dumps(result))

    # event = {"accounts": [{"account_id": "218645821098", "account_name": "shared_accountdummyprod"}, {"account_id": "557732467378", "account_name": "spssolutionsengprod"}, {"account_id": "634358168068", "account_name": "spssecuritydummyprod"}, {"account_id": "322384046982", "account_name": "spssharedservices"}, {"account_id": "872994156236", "account_name": "spsfulfillmentnonprod"}, {"account_id": "103086796224", "account_name": "spscommercetranslatornonprod"}, {"account_id": "234276412529", "account_name": "spscorpdummyaccountnonprod"}, {"account_id": "539473073908", "account_name": "spscorpsysnavprod"}, {"account_id": "155286110238", "account_name": "spsupliftprod"}, {"account_id": "689399476883", "account_name": "spscscesandbox"}, {"account_id": "345837284570", "account_name": "spsrulesapiprod"}, {"account_id": "424779663964", "account_name": "security_dummyaccountprod"}, {"account_id": "488718967548", "account_name": "corp_dummyaccountnonprod2"}, {"account_id": "756270639344", "account_name": "spssfdevassistantprod"}, {"account_id": "517440190904", "account_name": "spsartifactsprod"}, {"account_id": "547438833790", "account_name": "Audit"}, {"account_id": "507061929859", "account_name": "spsciasuppliergeniusnonprod"}, {"account_id": "969333048312", "account_name": "spsnetworkdummyaccountprod"}, {"account_id": "414251475300", "account_name": "spsanalyticsopnonprod"}, {"account_id": "682273737756", "account_name": "spsworkbenchnonprod"}, {"account_id": "128411165148", "account_name": "spslabelenginenonprod"}, {"account_id": "558978425783", "account_name": "spsprojectcreationnonprod"}, {"account_id": "163713998825", "account_name": "corp_dummyaccountnonprod"}, {"account_id": "359062871627", "account_name": "spsncsprod"}, {"account_id": "397571683079", "account_name": "spscorpsyscrmprod"}, {"account_id": "787245755735", "account_name": "spsdnsnonprod"}, {"account_id": "529647421943", "account_name": "spscustomerdummynonprod"}, {"account_id": "638413214142", "account_name": "phishing_dummyaccountnonprod"}, {"account_id": "265751409781", "account_name": "spsinterviewerappnonprod"}, {"account_id": "575471310372", "account_name": "spsdrenonprod"}, {"account_id": "719142240386", "account_name": "spscommsnonprod"}, {"account_id": "736527455428", "account_name": "spsdeepracer04"}, {"account_id": "602068278189", "account_name": "spsartifactsnonprod"}, {"account_id": "939494087901", "account_name": "spscommercetranslatorprod"}, {"account_id": "473776538454", "account_name": "spstesttokencontrollerprod"}, {"account_id": "444907149104", "account_name": "spsmapadoc"}, {"account_id": "267477796349", "account_name": "spsdomaincontrollersnonprod"}, {"account_id": "812741704418", "account_name": "spsbisandbox"}, {"account_id": "247379584147", "account_name": "spsinventoryapiprod"}, {"account_id": "863912626012", "account_name": "spsidentityprod"}, {"account_id": "884612314744", "account_name": "spseventmessagingprod"}, {"account_id": "145868325788", "account_name": "spsinternalauth0nonprod"}, {"account_id": "620434882252", "account_name": "spsacccreationtest1"}, {"account_id": "056684691971", "account_name": "spscommerce"}, {"account_id": "658720431124", "account_name": "spsworkflowsharedprod"}, {"account_id": "578844544200", "account_name": "spsxrefprod"}, {"account_id": "473631299205", "account_name": "spsworkflowsharednonprod"}, {"account_id": "241682814720", "account_name": "phishing_dummyaccountprod"}, {"account_id": "264677663148", "account_name": "spsenterprisedataprod"}, {"account_id": "568414972161", "account_name": "corp_dummyaccountprod"}, {"account_id": "960260317581", "account_name": "spsapigwprod"}, {"account_id": "383318116347", "account_name": "spsoppprocessprod"}, {"account_id": "304853455096", "account_name": "spsprojectcreationprod"}, {"account_id": "185912574309", "account_name": "spscustomerdummyaccountprod"}, {"account_id": "782315404375", "account_name": "spssrenonprod"}, {"account_id": "149024239040", "account_name": "spsanalyticsopprod"}, {"account_id": "058897189524", "account_name": "spsanalyticssharedprod"}, {"account_id": "207681879772", "account_name": "spsdbeprod"}, {"account_id": "410935075392", "account_name": "spsenterprisedatanonprod"}, {"account_id": "562327461703", "account_name": "spsparcelservicenonprod"}, {"account_id": "891454074692", "account_name": "spssecphishdummyprod"}, {"account_id": "902762528775", "account_name": "spssecuritynonprod"}, {"account_id": "194017248349", "account_name": "spsfulfillmentbackendprod"}, {"account_id": "736253939431", "account_name": "spsprivatecaprod"}, {"account_id": "613803741820", "account_name": "spssharedsvcdummynonprod"}, {"account_id": "484131474837", "account_name": "spsshippingdocnonprod"}, {"account_id": "713498113935", "account_name": "spscianonprod"}, {"account_id": "047570900573", "account_name": "spsinterviewerappprod"}, {"account_id": "064736363911", "account_name": "spsaccountcreationtest3"}, {"account_id": "451690457892", "account_name": "spstesttokencontrollernonprod"}, {"account_id": "885708717705", "account_name": "spsshippingdocprod"}, {"account_id": "813915336875", "account_name": "spsstorage"}, {"account_id": "752785695266", "account_name": "spscomputeprod"}, {"account_id": "800983409128", "account_name": "spsworkbenchprod"}, {"account_id": "939381905650", "account_name": "spsexchangenonprod"}, {"account_id": "347833511843", "account_name": "spstpdnonprod"}, {"account_id": "158297657311", "account_name": "spsportal"}, {"account_id": "636866390727", "account_name": "spstransformationsharedprod"}, {"account_id": "555883433868", "account_name": "spsdevcenterprod"}, {"account_id": "645896758999", "account_name": "spssreprod"}, {"account_id": "579330054676", "account_name": "spssecurityphishdummynonprod"}, {"account_id": "756285575441", "account_name": "spssecuritydummynonprod"}, {"account_id": "361177530380", "account_name": "spscorpsysnavdev"}, {"account_id": "983141143894", "account_name": "spssharedsvcdummyprod"}, {"account_id": "735373007788", "account_name": "spsbuyonlineprod"}, {"account_id": "822282873068", "account_name": "spslabelengineprod"}, {"account_id": "880325723926", "account_name": "spsanadataengineprod"}, {"account_id": "776969521278", "account_name": "spsupliftnonprod"}, {"account_id": "625246690944", "account_name": "spsintouchopsnonprod"}, {"account_id": "364643910852", "account_name": "spsdevcenternonprod"}, {"account_id": "365849160317", "account_name": "spscloudopsnonprod"}, {"account_id": "776182453594", "account_name": "spscloudopssandbox"}, {"account_id": "220759238760", "account_name": "spsciasuppliergeniusprod"}, {"account_id": "772780693226", "account_name": "spsdefaultchartprod"}, {"account_id": "982875807494", "account_name": "spsxrefnonprod"}, {"account_id": "107921392818", "account_name": "spsamqbrokersprod"}, {"account_id": "881131606442", "account_name": "spsauthzprod"}, {"account_id": "148199178391", "account_name": "spsanadataenginenonprod"}, {"account_id": "335101068804", "account_name": "network_dummyaccountprod"}, {"account_id": "972478634081", "account_name": "spsdevcntrpocprod"}, {"account_id": "854280122463", "account_name": "spsdeepracer01"}, {"account_id": "987960539289", "account_name": "security_dummyaccountnonprod"}, {"account_id": "253977942483", "account_name": "spseventmessagingnonprod"}, {"account_id": "031699915087", "account_name": "spsfulfillmentprod"}, {"account_id": "741792080734", "account_name": "spsdeepracer02"}, {"account_id": "129946327277", "account_name": "spsbuyonlinenonprod"}, {"account_id": "622918308850", "account_name": "spsauthznonprod"}, {"account_id": "295046242866", "account_name": "spsassortmentnonprod"}, {"account_id": "684217692238", "account_name": "spsdeepracer03"}, {"account_id": "939966911798", "account_name": "spssecphishdummynonprod"}, {"account_id": "979883100379", "account_name": "spswebsandbox"}, {"account_id": "022660963626", "account_name": "spscomputenonprod"}, {"account_id": "632292198595", "account_name": "spsdefaultchartnonprod"}, {"account_id": "582881724802", "account_name": "spssharedservicesdev"}, {"account_id": "331787820826", "account_name": "nukesandbox"}, {"account_id": "488958548839", "account_name": "spsdnsprod"}, {"account_id": "353961288804", "account_name": "network_dummyaccountnonprod"}, {"account_id": "930090106623", "account_name": "spsdreprod"}, {"account_id": "466058717980", "account_name": "spsrulesapinonprod"}, {"account_id": "233724499874", "account_name": "spsamqbrokersnonprod"}, {"account_id": "113373587530", "account_name": "spsdbenonprod"}, {"account_id": "242593066326", "account_name": "spscarrierserviceprod"}, {"account_id": "882353228661", "account_name": "spssecurityphishingnonprod"}, {"account_id": "567717846481", "account_name": "spsncsnonprod"}, {"account_id": "803720667623", "account_name": "spsdomaincontrollersprod"}, {"account_id": "022915863975", "account_name": "spscorpsyscrmnonprod"}, {"account_id": "445094321643", "account_name": "spsprivatecanonprod"}, {"account_id": "951674939512", "account_name": "spssolutionsengnonprod"}, {"account_id": "234473414902", "account_name": "spsemojiverifynonprod"}, {"account_id": "094619684579", "account_name": "spsnetworkprod"}, {"account_id": "901594318945", "account_name": "spstranssandbox"}, {"account_id": "413345170962", "account_name": "spsshire"}, {"account_id": "054710025684", "account_name": "spsiamnonprod"}, {"account_id": "284282354207", "account_name": "spstpdprod"}, {"account_id": "595883171258", "account_name": "spsmgmt"}, {"account_id": "128265684646", "account_name": "spssecurityphishingprod"}, {"account_id": "167835801234", "account_name": "spscommsprod"}, {"account_id": "633919963860", "account_name": "Log archive"}, {"account_id": "552971540574", "account_name": "spsidentitynonprod"}, {"account_id": "463233306394", "account_name": "spsediadmin"}, {"account_id": "878120878580", "account_name": "spsdeepracer1"}, {"account_id": "880141098094", "account_name": "spsroot"}, {"account_id": "928184168613", "account_name": "spsassortmentprod"}, {"account_id": "523833198678", "account_name": "spsdeploytestingnonprod"}, {"account_id": "412893577244", "account_name": "spscloudopsprod"}, {"account_id": "237932634184", "account_name": "spsinternalauth0prod"}, {"account_id": "196313191101", "account_name": "spsanalyticssharednonprod"}, {"account_id": "318512389406", "account_name": "spscustomerdummyaccountnonprod"}, {"account_id": "171723327451", "account_name": "spsfulfillmentbackendnonprod"}, {"account_id": "415106849015", "account_name": "spssecurityprod"}, {"account_id": "466847686915", "account_name": "spsiamprod"}, {"account_id": "555745536724", "account_name": "spsdeepracer11"}, {"account_id": "275210250900", "account_name": "spsworkflowprod"}, {"account_id": "519877730436", "account_name": "spsfinops"}, {"account_id": "648847288219", "account_name": "spscustomerdummyprod"}, {"account_id": "088986507559", "account_name": "spsdevcntrpocnonprod"}, {"account_id": "205628952115", "account_name": "spsfimapservicenonprod"}, {"account_id": "257603148529", "account_name": "spsstylesheettransformnonprod"}, {"account_id": "445144152630", "account_name": "spssalesdemo"}, {"account_id": "967929781393", "account_name": "spsapigwnonprod"}, {"account_id": "578497762544", "account_name": "spsauth0nonprod"}, {"account_id": "011754564238", "account_name": "spscorpdummyaccountprod"}, {"account_id": "833379347452", "account_name": "spsauth0prod"}, {"account_id": "379784731310", "account_name": "spsreportingnonprod"}, {"account_id": "642013005867", "account_name": "spsaccountcreationtest1"}, {"account_id": "333808835704", "account_name": "spsbdp"}, {"account_id": "106920632453", "account_name": "spsworkflownonprod"}, {"account_id": "259018431749", "account_name": "spstransformationsharednonprod"}, {"account_id": "760174706457", "account_name": "shared_accountdummynonprod"}, {"account_id": "292095470506", "account_name": "spsemojiverifyprod"}, {"account_id": "726425380899", "account_name": "spscsenonprod"}, {"account_id": "097202842911", "account_name": "spssandbox"}, {"account_id": "933783489366", "account_name": "spsexchangeprod"}, {"account_id": "394266872273", "account_name": "spsinventoryapinonprod"}, {"account_id": "940773763929", "account_name": "spsaccountcreationtest2"}, {"account_id": "893925574780", "account_name": "spsanapacanonprod"}, {"account_id": "048670870908", "account_name": "spsoppprocessnonprod"}, {"account_id": "398846813286", "account_name": "spsciaprod"}, {"account_id": "054015537794", "account_name": "spsatlassian"}, {"account_id": "104966627370", "account_name": "spsc"}, {"account_id": "103548765907", "account_name": "spssfdevassistantnonprod"}, {"account_id": "144996113099", "account_name": "spsdeploytestingprod"}, {"account_id": "232058395963", "account_name": "spsfimapserviceprod"}, {"account_id": "350441132401", "account_name": "spsintouchopsprod"}, {"account_id": "645113555958", "account_name": "spsstylesheettransformprod"}, {"account_id": "493794657987", "account_name": "spscseprod"}, {"account_id": "330902272183", "account_name": "spsintouchnonprod"}, {"account_id": "454586565479", "account_name": "corp_dummyaccountprod2"}, {"account_id": "923722167449", "account_name": "spsnetworknonprod"}, {"account_id": "705613635874", "account_name": "spscarrierservicenonprod"}, {"account_id": "390255599420", "account_name": "spstechopssandbox"}, {"account_id": "922371398847", "account_name": "spsbdepdev"}, {"account_id": "221543577525", "account_name": "spsnetworkdummyaccountnonprod"}, {"account_id": "047077570360", "account_name": "spsanapacaprod"}, {"account_id": "466342371916", "account_name": "spsparcelserviceprod"}, {"account_id": "781683095799", "account_name": "spsintouchprod"}, {"account_id": "955924120273", "account_name": "spsacccreationtest2"}, {"account_id": "079528373200", "account_name": "spsreportingprod"}, {"account_id": "343303738329", "account_name": "spssandboxdummy"}], "regions": ["ap-northeast-1", "ap-northeast-2", "ap-northeast-3", "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ca-central-1", "eu-central-1", "eu-north-1", "eu-west-1", "eu-west-2", "eu-west-3", "sa-east-1", "us-east-1", "us-east-2", "us-west-1", "us-west-2"]}