#!/usr/bin/python -O
# encoding: utf-8
#
# Populate tables in DynamoDB with the following baseline data:
#   * file system data (path, timestamps, access mode) in DBLOCATIONS
#   * content-specific data (content hash, MIME type, size) in DBFILES
#
# If same (content-wise) file exists in different locations on a single
# instance, all such locations are referenced in the same `file` record
# under a key specific to the instance.
#
# Script uses HASHALGO to calculate file content hashes as well as hashes
# of file paths (to handle very long paths and speed up path verifications)
#
# To enable debug output and a fix for local execution outside AWS instance,
# run it without optimization ("-O" parameter). Change first line above to:
#   #!/usr/bin/env python
#
from __future__ import print_function

import argparse
import boto3
import copy
import datetime
import decimal
import grp
import hashlib
import json
import magic
import os
import pwd
import requests
import stat


# Create argument parser
arg_parser = argparse.ArgumentParser(description="Populate tables with the baseline data from DIRSOURCES")

# Define expected arguments
arg_parser.add_argument(
	"--region",
	dest="aws_region",
	help="AWS region of the DynamoDB tables",
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
	"--hash",
	dest="hash_algo",
	help="hashing algorithm to use",
	metavar="HASHALGO",
	choices=[
		"md5",
		"sha1",
		"sha224",
		"sha256",
		"sha384",
		"sha512",
	],
	default="sha256"
)
arg_parser.add_argument(
	"--files-table",
	dest="db_files",
	help="DynamoDB table to store file records",
	metavar="DBFILES",
	default="HashFS-Files"
)
arg_parser.add_argument(
	"--locations-table",
	dest="db_locations",
	help="DynamoDB table to store location records",
	metavar="DBLOCATIONS",
	default="HashFS-Locations"
)
arg_parser.add_argument(
	"dir_sources",
	nargs="*",
	help="Source directories to be process",
	metavar="DIR",
	default=[ "/var/www/html/" ]
)

# Parse command-line arguments
args = arg_parser.parse_args()

# DEBUG:
if __debug__:
	print ( "Preparing for hashing" )

# Source directories to populate HashFS tables
# Any sub-dir in the list fill be folded (removed)
# under a corresponding parent dir. Paths will be
# normalized (e.g. "/../" will be followed, "//" reduced, etc)
sources = args.dir_sources

# Hashing algorithm to be used for path and content hashes
hash_algorithm = args.hash_algo


# Define UTC class based on tzinfo to fix timezone specs in datetime.isoformat()
class tz_utc(datetime.tzinfo):
    def tzname(self):
        return "UTC"
    def utcoffset(self, dt):
        return datetime.timedelta(0)


# Helper class to convert a DynamoDB item to JSON.
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)


# Define function to convert numerical file mode to string
def filemode2str(st_mode):
    dic = {"7":"rwx", "6" :"rw-", "5" : "r-x", "4":"r--", "3":"-wx", "2":"-w-", "1":"--x", "0": "---"}
    perm = str(oct(st_mode)[-3:])
    return "".join(dic.get(x,x) for x in perm)


# Queries DynamoDB Table for an item matching primary KeyName:KeyVal.
# Indicates ConsistentRead in the query to get the most current version.
# If there is no item returned by DynamoDB, returns None.
def check_for_item (KeyName, KeyVal, Table):
	item = Table.get_item(
	    Key={
	        KeyName: KeyVal
	    },
	    ConsistentRead=True,
	    ReturnConsumedCapacity="NONE"
    )

	return item.get("Item", None)

# Finds mount point for a given FullPath
def find_mount_point(FullPath):
    path = os.path.realpath(FullPath)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path

# Prepare Magic lib for file MIME type guessing
m = magic.open(magic.MAGIC_MIME)
m.load()


# Normalize all source paths
for s in sources:
	sources[ sources.index( s ) ] = os.path.join( os.path.normpath( s ), '' )


# Sort sources by length (shortest first) to optimize subsequent folding
sources.sort(key = lambda s: len(s))


# Fold (remove) sources that are sub-dirs of other sources
sources_folded = []
for s in sources:
    if not any([o in s for o in sources_folded]):
        sources_folded.append(s)


# Prepare map of UID -> user name
uid2name = {}
for pwd_rec in pwd.getpwall():
    uid2name[pwd_rec[2]] = pwd_rec[0]


# Prepare map of UID -> user name
gid2name = {}
for grp_rec in grp.getgrall():
    gid2name[grp_rec[2]] = grp_rec[0]


# Prepare dynamodb client
dynamodb = boto3.resource( "dynamodb", region_name=args.aws_region )

# Get handles for HashFS tables
files_table = dynamodb.Table( args.db_files )
locations_table = dynamodb.Table( args.db_locations )


# Initialize list of locations
locations = []

# Initialize the instance name from meta-data
# Also construct a map of mount points and
# corresponding awsEBS volumes
# (for debugging should be executed without "-O")
# DEBUG
if __debug__:
	host_name = "i-debughost01"

	volumes_map = {"/home":"vol-home123", "/":"vol-root123"}
else:
	response = requests.get( "http://169.254.169.254/latest/meta-data/instance-id" )
	host_name = response.text

	# get a list of block devices attached to the instance
	device_mappings = boto3.resource( 'ec2', region_name=args.aws_region ).Instance( host_name ).block_device_mappings

	device_volume_dict = {}

	# iterate over all devices attached to the instance
	# construct a dictionary of {device-name : volume-id}
	for dev in device_mappings:
		# check the device type
		if dev.get("Ebs", None) is None:
			# skip non-EBS volumes
			continue

		# add a record to the dictionary
		device_volume_dict.update( { dev["DeviceName"] : dev["Ebs"]["VolumeId"] } )

	device_mount_dict = {}

	# read /proc/mounts to get mount points for devices
	# construct a dictionary of {device-name : mount_point}
	for line in file("/proc/mounts"):
		# split each line into fields
		fields = line.split()

		# add a record to the dictionary
		device_mount_dict.update( { fields[0] : fields[1] } )

	volumes_map = {}

	# iterate through mounted devices / volumes
	# construct a dictionary of {mount-point : volume-id}
	for dev in device_volume_dict:
		# check if device associated with a volume is matching any known mount point
		if dev in device_mount_dict:
			volumes_map.update( { device_mount_dict[ dev ] : device_volume_dict[ dev ] } )

# DEBUG:
if __debug__:
	print ( "Processing sources:" )
# Process each source
for s in sources_folded:
	# Make an absolute path
	source = os.path.abspath( s )

	# Get mount point of the source
	mount_point = find_mount_point( source )

	# Map mount point to the volume
	volume = volumes_map.get( mount_point, "UNKNOWN-NON-EBS-VOL" )

	# DEBUG:
	if __debug__:
		print ( "[" + source + "]", end="" )

	# Walk sub-directories of the source directory and get info for all the files
	for dirName, subdirList, fileList in os.walk( source, topdown=False ):
		for fileName in fileList:
			# DEBUG:
			if __debug__:
				print ( ".", end="" )

			# Properly join dir and file name into a full path
			full_path =  os.path.join( dirName, fileName )

			# Hash full file path to speed up search and avoid problems
			# with deep nested paths. Equivalent of the following:
			#   host_path_hash = hashlib.sha256( full_path ).hexdigest()
			# With the implementation below, hashing algorithm is
			# configurable through a single variable 'hash_algorithm'
			# outside of the loop.
			#
			# Hashlib object has to be created in each iteration.
			# Otherwise hashlib.update() aggregates content of files
			# from all previous iterations.
			h = hashlib.new( hash_algorithm )
			h.update( full_path )
			host_path_hash = h.hexdigest()

			# Calculate path relative to the mount point (volume path)
			volume_path = os.path.relpath( full_path, mount_point )

			# Calculate the hash of the volume path
			h = hashlib.new( hash_algorithm )
			h.update( volume_path )
			volume_path_hash = h.hexdigest()

			# Get file's content
			file_content = open( full_path,"rb" ).read()

			# Calculate the hash of the content
			h = hashlib.new( hash_algorithm )
			h.update( file_content )
			file_hash = h.hexdigest()

			# Get stat() information for the file (uid/gid, mode, size, MAC-times )
			stat_info = os.stat( full_path )

			# Get MIME type and encoding info for the file
			mime_info = m.file( full_path )

			# Assemble location record for the file
			location_rec = {
				"Volume":  volume,
				"VolumePath":  volume_path,
				"VolumePathHash": volume_path_hash,
				"Host": host_name,
				"HostPath": full_path,
				"HostPathHash": hash_algorithm + ":" + host_path_hash,
				"ContentHash": hash_algorithm + ":" + file_hash,
				"Owner": {
					"Id": stat_info.st_uid,
					"Name": uid2name[ stat_info.st_uid ],
				},
				"Group": {
					"Id": stat_info.st_gid,
					"Name": gid2name[ stat_info.st_gid ],
				},
				"AccessMode": {
					"Num": oct( stat.S_IMODE( stat_info.st_mode ) ),
					"Str": filemode2str( stat_info.st_mode ),
				},
				# Save MAC timestamps in two formats: Unix Epoch, and ISO-8601 text string
				# Epoch timestamp is always UTC timezone by definition
				# ISO timestamp requires some datetime kung fu to get strictly ISO compliant UTC timezone
				"Timestamps": {
					"Access": {
						"UNIX": str(stat_info.st_atime),
						"ISO": datetime.datetime.utcfromtimestamp( stat_info.st_atime ).replace(tzinfo=tz_utc()).isoformat(),
					},
					"Modify": {
						"UNIX": str(stat_info.st_mtime),
						"ISO": datetime.datetime.utcfromtimestamp( stat_info.st_mtime ).replace(tzinfo=tz_utc()).isoformat(),
					},
					"Change": {
						"UNIX": str(stat_info.st_ctime),
						"ISO": datetime.datetime.utcfromtimestamp( stat_info.st_ctime ).replace(tzinfo=tz_utc()).isoformat(),
					},
				},
			}
			# DEBUG:
			#if __debug__:
			#	print ( json.dumps( location_rec, sort_keys=True, indent=2, separators=(",", ": "), cls=DecimalEncoder ) )

			# Add location record to the list
			locations.append( location_rec )

			# Also, put location record into the DynamoDB table
			response = locations_table.put_item(
				Item=location_rec
			)
			# DEBUG:
			#if __debug__:
			#	print ( json.dumps( response, sort_keys=True, indent=2, separators=(",", ": "), cls=DecimalEncoder ) )

			# Get file record from DynamoDB if it exists or None if it doesn't
			file_rec = check_for_item( "ContentHash", hash_algorithm + ":" + file_hash, files_table )
			if not file_rec:
				# if it does not exist, put a new file record item into the DynamoDB table
				response = files_table.put_item(
					Item={
						"ContentHash": hash_algorithm + ":" + file_hash,
						"Type": mime_info,
						"Size": stat_info.st_size,
						"Status": "INITIAL",
						"Locations": { volume : [ hash_algorithm + ":" + volume_path_hash ] },
					}
				)
				# DEBUG:
				#if __debug__:
				#	print ( json.dumps( response, sort_keys=True, indent=2, separators=(",", ": "), cls=DecimalEncoder ) )
			else:
				# Otherwise, get all locations from the existing record
				# structured as dict of {volume: [list, of, volume, path, hashes]}
				file_locations = file_rec[ "Locations" ]

				# Check if there is a key for our host name already present in Locations
				if not (volume in file_locations):
					# and if there is none, add the key with empty list placeholder
					file_locations.update( { volume : [] } )

				# At this point, host name key is present in Locations anyway
				# Check if current location already exists in the list for the current host name
				if not ( hash_algorithm + ":" + volume_path_hash in file_locations[ volume ] ):
					# If location does not exist, add it under the key of the current host name.
					file_locations[ volume ].append( hash_algorithm + ":" + volume_path_hash )

					# Update existing item in the DynamoDB table with the new Locations
					# UpdateExpression adds empty list for host name if such key does not exists
					# and then appends the list with current location.
					#
					# This should be better than put_item() as it is the DynamoDB engine which
					# actually appends to the Locations property of the specific item. Hopefully,
					# it is robust for parallel processing (e.g. HashFS initialization
					# running in parallel on many hosts with same files) and queues / chains updates
					response = files_table.update_item(
					    Key={
					        "ContentHash": hash_algorithm + ":" + file_hash
					    },
					    UpdateExpression="set Locations.#v = list_append(if_not_exists(Locations.#v, :e), :l)",
					    ExpressionAttributeNames={
					        "#v": volume,
					    },
					    ExpressionAttributeValues={
					        ":e": [],
					        ":l": [ hash_algorithm + ":" + volume_path_hash ],
					    },
					    ReturnValues="NONE"
					)
					# DEBUG:
					#if __debug__:
					#	print ( json.dumps( response, sort_keys=True, indent=2, separators=(",", ": "), cls=DecimalEncoder ) )

	# DEBUG:
	if __debug__:
		print ( "[OK]" )

# DEBUG:
if __debug__:
	print ( "Finished hashing" )
