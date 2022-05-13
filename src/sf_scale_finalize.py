import json
import os

import lambdavars

from aws import *
from carve import update_beacon_inventory, update_beacon_list

from pprint import pprint


def lambda_handler(event, context):
    print(event)

    print("updating beacon inventory")
    beacon_targets = update_beacon_inventory()

    if len(beacon_targets) > 0:
        print(f"updating inventory on all {len(beacon_targets)} beacons")
        update_beacon_list(beacon_targets)
    else:
        print("no beacons to update")


if __name__ == "__main__":
    event = {}
    result = lambda_handler(event, None)
    # print(result)