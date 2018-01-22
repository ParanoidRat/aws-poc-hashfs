#!/bin/bash -xe

aws s3 sync ./cf-templates/ s3://cf-templates-xaw369ZM
aws s3 sync ./scripts/ s3://hashfs-bucket-xaw369ZM

aws cloudformation update-stack \
  --region us-east-1 \
  --stack-name LabDFIRNested \
  --template-url https://s3.amazonaws.com/cf-templates-xaw369ZM/Template_DFIR_Master.json \
  --parameters \
    ParameterKey=ProjectTag,UsePreviousValue=true \
    ParameterKey=InstanceCount,UsePreviousValue=true \
    ParameterKey=InstanceType,UsePreviousValue=true \
    ParameterKey=StorageType,UsePreviousValue=true \
    ParameterKey=CacheNodeType,UsePreviousValue=true \
    ParameterKey=NumberOfCacheNodes,UsePreviousValue=true \
    ParameterKey=DBInstanceType,UsePreviousValue=true \
    ParameterKey=DBName,UsePreviousValue=true \
    ParameterKey=DBUser,UsePreviousValue=true \
    ParameterKey=DBPassword,UsePreviousValue=true \
    ParameterKey=WebAppGitRepo,UsePreviousValue=true \
    ParameterKey=ReadCapacityUnits,UsePreviousValue=true \
    ParameterKey=WriteCapacityUnits,UsePreviousValue=true \
    ParameterKey=SnapshotWorkerCodeS3Bucket,UsePreviousValue=true \
    ParameterKey=SnapshotWorkerCodeS3Key,UsePreviousValue=true \
    ParameterKey=SnapshotWorkerTimeout,UsePreviousValue=true \
    ParameterKey=SnapshotWorkerMemSize,UsePreviousValue=true \
    ParameterKey=SnapshotWorkerScheduleExpression,UsePreviousValue=true \
    ParameterKey=VpcId,UsePreviousValue=true \
    ParameterKey=VpcSubnet,UsePreviousValue=true \
    ParameterKey=SSLCertName,UsePreviousValue=true \
    ParameterKey=SSHKeyName,UsePreviousValue=true \
    ParameterKey=SSHLocation,ParameterValue=`/usr/bin/dig +short myip.opendns.com @resolver1.opendns.com`/32 \
  --capabilities CAPABILITY_IAM
