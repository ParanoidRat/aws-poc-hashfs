# AWS PoC lab for automated detection of a compromised web app
This repository contains CloudFormation templates and python scripts for an
automated deployment of the environment depicted below. This was my way
of testing some automated incident detection ideas and learning AWS.

**HashFS name in the diagram, code and comments is NOT a reference to [this][3] project.** I coincidentally have chosen the same name for my work, sorry.

![lab environment][dfir-lab-pic]

## Getting Started
1.  Clone repository
```bash
git clone https://github.com/ParanoidRat/aws-poc-hashfs.git
```

2.  Create S3 bucket for CloudFormation templates and scripts
```bash
aws s3 mb s3://cf-templates-xaw369ZM
aws s3 mb s3://hashfs-bucket-xaw369ZM
```

3.  Upload a vulnerable web app (e.g. [bWAPP from OWASP][4]) into your git repo or use existing one. Adjust `WebAppGitRepo` parameter accordingly in `cloud_form.sh`

4.  Adjust `VpcId` and `VpcSubnet` parameters for your own values in `cloud_form.sh`

5.  Run bash script uploading templates and scripts to S3 and starting CloudFormation
```bash
cloud_form.sh
```

6.  If you want to apply some of your local changes later, run
```bash
cloud_update.sh
```

## Overview
Project goal was to automate creation of a lab environment with vulnerable web application and provisions for automated detection of a compromise and automated response to it taking into account limitations of the AWS Free Tier. Compromise is defined as upload of unauthorized code to a web server.

Provided CloudFormation templates build the following:
-   Auto-scaling group with the HTTP/HTTPS ELB that uses Ubuntu 16.04 (ephemeral or EBS root volume) as a reference AMI. Such choice of the OS triggered all sorts of little compatibility pitfalls as most of the AWS CloudFormation Metadata examples and scripts are done for AWS Linux AMIs. The corresponding launch configuration ensures that:
    -   CloudFormation bootstrap helper is installed and configured
    -   Dedicated 1GB EBS volume is created for the webapp code and mounted as /var/www/
    -   Git client is installed and configured to work with CodeCommit
    -   PHP webapp code is downloaded from Git repository to the dedicated volume
    -   Apache2 and PHP7 are installed and configured to support HTTPS
    -   ElastiCache Cluster Client (memcache) is deployed and PHP is configured to load it and use memcache as a storage for session info
        -   Note: this allows true load balancing without sticky sessions on the ELB and provides better resiliency and recovery of the environment
    -   Python script generating a one-time patch for PHP configuration is deployed and executed to specify all nodes of the ElastiCache Cluster as session storage for PHP inside the php.ini
      -   Note: While the ElastiCache Cluster Client has an auto-discovery feature, it only works when memcache is used by the PHP code, the engine itself does not have this feature. Future improvement here is to either run this script and apply current list of nodes as a patch periodically or have a watchdog script that would do describe_cache_clusters() looking for changes and apply them to php.ini
    -   Patches for PHP configuration and the webapp settings are applied to use the right credentials for the MySQL node deployed as part of the template
    -   Test PHP script that performs MySQL connection test and presents current session cookies is deployed (used in the ELB HealthCheck)
    -   Python script `secured_init.py` is deployed and executed. It collects data about files like hash of the content, file system metadata (e.g. owner, MAC timestamps, etc), hash of the path (to support long nested paths and speed up path checks) and stores it in two DynamoDB tables. Script is written with the idea that it will be executed in parallel on more than one instance.
-   ElastiCache Cache Cluster (memcahce)
-   RDS DB instance (MySQL)
-   Two DynamoDB tables to hold HashFS data
-   Lambda function `snapshot_worker.py` that periodically creates snapshots for all instances matching <TAGKEY>:<TAGVALUE> pair, deletes old snapshots and posts a corresponding message in the SQS queue. It is used to create snapshots of the EBS volumes holding the PHP code. TheTogether with file integrity baseline data (hashes, FS metadata) it allows automatic creation of a temporary volume that could be mounted to a separate watchdog instance and checked for changes (e.g. upload of unauthorized code)
-   Different security groups are created to facilitate connectivity between aforementioned components in a VPC.

## TODO
Watchdog instance with a Python script creating volumes out of snapshots and mounting them for verification against baseline data in DynamoDB and taking instances to a separate security group for quarantine if discrepancy has been detected.

## Tested On
*   Ubuntu 16.04 LTS

## Authors
*   [ParanoidRat][1]

## License
The work is licensed under the CC-BY-SA 4.0 License. Unless otherwise stated, modifications are also licensed under the CC-BY-SA 4.0 License. See the [LICENSE.md](LICENSE.md) file for details and specific licensing of the modifications.

You should have received a copy of the license along with this work (see the [CC-BY-SA-4.txt](CC-BY-SA-4.txt) file for details). If not, see [here][2].

[1]: https://github.com/ParanoidRat
[2]: https://creativecommons.org/licenses/by-sa/4.0/legalcode
[3]: https://github.com/dgilland/hashfs
[4]: http://www.itsecgames.com/
[dfir-lab-pic]: pictures/dfir-lab.jpg
