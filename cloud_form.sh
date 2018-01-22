#!/bin/bash -xe

aws s3 sync ./cf-templates/ s3://cf-templates-xaw369ZM
aws s3 sync ./scripts/ s3://hashfs-bucket-xaw369ZM

aws cloudformation create-stack \
  --region us-east-1 \
  --stack-name LabDFIRNested \
  --template-url https://s3.amazonaws.com/cf-templates-xaw369ZM/Template_DFIR_Master.json \
  --parameters \
    ParameterKey=ProjectTag,ParameterValue=LabDFIR \
    ParameterKey=InstanceCount,ParameterValue=2 \
    ParameterKey=InstanceType,ParameterValue=t2.micro \
    ParameterKey=StorageType,ParameterValue=EBS-SSD \
    ParameterKey=CacheNodeType,ParameterValue=cache.t2.micro \
    ParameterKey=NumberOfCacheNodes,ParameterValue=1 \
    ParameterKey=DBInstanceType,ParameterValue=db.t2.micro \
    ParameterKey=DBName,ParameterValue=bWAPP \
    ParameterKey=DBUser,ParameterValue=bWAPPuser \
    ParameterKey=DBPassword,ParameterValue=`/usr/bin/apg -d -M NCL -n 1 -m 16` \
    ParameterKey=WebAppGitRepo,ParameterValue="https://git-codecommit.us-east-1.amazonaws.com/v1/repos/DFIRbWAPPRepo" \
    ParameterKey=ReadCapacityUnits,ParameterValue=10 \
    ParameterKey=WriteCapacityUnits,ParameterValue=10 \
    ParameterKey=SnapshotWorkerCodeS3Bucket,ParameterValue=hashfs-bucket-xaw369ZM \
    ParameterKey=SnapshotWorkerCodeS3Key,ParameterValue=snapshot_worker.zip \
    ParameterKey=SnapshotWorkerTimeout,ParameterValue=60 \
    ParameterKey=SnapshotWorkerMemSize,ParameterValue=128 \
    ParameterKey=SnapshotWorkerScheduleExpression,ParameterValue="rate(15 minutes)" \
    ParameterKey=VpcId,ParameterValue=vpc-abcd4d4f \
    ParameterKey=VpcSubnet,ParameterValue=subnet-abcd4d4f \
    ParameterKey=SSLCertName,ParameterValue=snakeoil \
    ParameterKey=SSHKeyName,ParameterValue=aws-test-key \
    ParameterKey=SSHLocation,ParameterValue=`/usr/bin/dig +short myip.opendns.com @resolver1.opendns.com`/32 \
  --capabilities CAPABILITY_IAM
