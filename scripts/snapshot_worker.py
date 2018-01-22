#!/usr/bin/python -O
# encoding: utf-8
#
# Creates snapshots for all instances matching <TAGKEY>:<TAGVALUE> pair.
# Sends a message for each created snapshot to an SQS queue to be pulled by integrity checker 
#
# To enable debug output for command-line execution, run it without optimization ("-O" parameter).
# Change first line above to:
#   #!/usr/bin/python
#
from __future__ import print_function

import boto3
from datetime import datetime

# script parameters if run not from the command line
# otherwise, they will be redefined with arg_parser
aws_region = "us-east-1"
account_id = "285176481200"
tag_key = "Project"
tag_value  = "DFIR"
dev_names = [ "/dev/xvdf" ]
queue_name = "DFIRNestedCloud-LabQueues-103V7JC06SKO4-CheckingSnapQueue-1B11Z3J7O8CGU"

# Instantiate ec2 client
ec2 = boto3.client( "ec2", region_name=aws_region )

# Instantiate SQS queue
sqs_queue = boto3.resource('sqs').get_queue_by_name(QueueName=queue_name)

# Lambda handler
def handler(event, context):
	# get all previous snapshots matching <TAGKEY>:<TAGVALUE> to be deleted below
	# TODO:
	#      get only snapshots with "Status":"CHECKED"
	snapshots = ec2.describe_snapshots(
		OwnerIds=[ account_id ],
		Filters=[
	    	{"Name": "tag:" + tag_key, "Values": [ tag_value ] },
	        # {"Name": "tag:Status", "Values": ["CHECKED"]},
	    ]
	)["Snapshots"]

	# iterate over snapshots
	for snap in snapshots:
		print( "Deleting snapshot [%s] for EBS volume [%s]" %
			 ( snap["SnapshotId"], snap["VolumeId"]) )

		# delete each snapshot
		ec2.delete_snapshot(
			SnapshotId = snap["SnapshotId"],
		)

	print ( "Looking for instances in region [%s] matching tag [%s:%s] with volumes named as %s" %
		  ( aws_region, tag_key, tag_value, dev_names) )

	# get the list of reservations containing instances matching the filter tag_key:tag_value
	reservations = ec2.describe_instances(
		Filters=[
	    	{"Name": "tag-key", "Values": [ tag_key ] },
	        {"Name": "tag-value", "Values": [ tag_value ]},
	    ]
	)["Reservations"]

	# flatten the list of instances
	instances = sum( [ [ i for i in r["Instances"] ] for r in reservations ], [])

	# iterate over all instances found
	for inst in instances:

		# iterate over all devices attached to the instance
		for dev in inst["BlockDeviceMappings"]:

			# check the device type
			if dev.get("Ebs", None) is None:
				# skip non-EBS volumes
				continue

			# check the device name
			if dev["DeviceName"] not in dev_names:
				# skip device names not mentioned in the filter
				continue

			print( "Creating snapshot for EBS volume [%s] on instance [%s]" % ( dev["Ebs"]["VolumeId"], inst["InstanceId"] ) )

			# make a volume snapshot
			vol_snapshot = ec2.create_snapshot(
				VolumeId=dev["Ebs"]["VolumeId"],
			)

			# Tag created snapshot with <TAGKEY>:<TAGVALUE> as well as "Status":"UNCKECKED" and "ForVolume":<VolumeID>
			ec2.create_tags(
				Resources=[ vol_snapshot["SnapshotId"] ],
				Tags=[
				    {"Key": tag_key, "Value": tag_value},
				    {"Key": "Status", "Value": "UNCHECKED"},
				]
			)


			print( "Posting message into the queue: SnapshotId[%s], VolumeId[%s], InstanceId[%s]" % ( vol_snapshot["SnapshotId"], dev["Ebs"]["VolumeId"], inst["InstanceId"] ) )

			# Post a message with snapshot details into the checking queue
			sqs_queue.send_message(MessageBody=vol_snapshot["SnapshotId"], MessageAttributes={
				'SnapshotId' : {
					'StringValue': vol_snapshot["SnapshotId"],
        			'DataType': 'String'
				},
				'VolumeId' : {
					'StringValue': dev["Ebs"]["VolumeId"],
        			'DataType': 'String'
				},
				'InstanceId' : {
					'StringValue': inst["InstanceId"],
        			'DataType': 'String'
				}
			})

# if executed from the command-line
if __name__ == "__main__":
	import argparse
	import json

	#JSON serializer for objects not serializable by default json code
	def json_serial(obj):
		# serialize datetime() object
	    if isinstance(obj, datetime):
	        serial = obj.isoformat()
	        return serial
	    # all other unknown objects raise exception
	    raise TypeError ("Type not serializable")

	# create argument parser
	arg_parser = argparse.ArgumentParser(description="Make snapshots of all DEVNAMEs volumes if they are EBS on instances matching <TAGKEY>:<TAGVALUE> pair")

	# define expected arguments
	arg_parser.add_argument(
		"--region",
		dest="aws_region",
		help="AWS region to use",
		metavar="AWSREGION",
		choices=[
	      "ap-northeast-1",
	      "ap-southeast-1",
	      "ap-southeast-2",
	      "eu-central-1",
	      "eu-west-1",
	      "sa-east-1",
	      "us-east-1",
	      "us-west-1",
	      "us-west-2",
	      "us-gov-west-1",
		],
		default="us-east-1"
	)
	arg_parser.add_argument(
		"--account-id",
		dest="account_id",
		help="AWS AccountID ",
		metavar="ACCOUNTID",
		default="285176481200"
	)
	arg_parser.add_argument(
		"--tag-key",
		dest="tag_key",
		help="Tag key to filter instances",
		metavar="TAGKEY",
		default="Project"
	)
	arg_parser.add_argument(
		"--tag-value",
		dest="tag_value",
		help="Tag value to filter instances",
		metavar="TAGVALUE",
		default="DFIR"
	)
	arg_parser.add_argument(
		"--check-queue",
		dest="queue_name",
		help="Name of SQS queue pulled by integrity checker",
		metavar="CHECKQUEUE",
		default="CheckingSnapQueue"
	)
	arg_parser.add_argument(
		"dev_names",
		nargs="*",
		help="Device names to be included in snapshots",
		metavar="DEVNAME",
		default=[ "/dev/xvdf" ]
	)
	# parse command-line arguments
	args = arg_parser.parse_args()

	# make placeholders for code transition to Lambda (no command-line args)
	aws_region = args.aws_region
	account_id = args.account_id
	tag_key = args.tag_key
	tag_value  = args.tag_value
	dev_names = args.dev_names
	queue_name = args.queue_name

	if __debug__:
		print ( "Started" )

	# run Lambda handler
	handler(None, None)

	# get all snapshots matching <TAGKEY>:<TAGVALUE>
	r = ec2.describe_snapshots(
		OwnerIds=[ account_id ],
		Filters=[
	    	{"Name": "tag:" + tag_key, "Values": [ tag_value ] },
	    ]
	)["Snapshots"]

	if __debug__:
		print ( json.dumps( r, sort_keys=True, indent=2, separators=(",", ": "), default=json_serial ) )

	if __debug__:
		print ( "Finished" )
