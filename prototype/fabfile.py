__author__ = 'aub3'
import logging, sys, random, os
import simplejson as json
logging.basicConfig(filename='logs/fab.log',level=logging.DEBUG,format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

import boto
logging.getLogger('boto').setLevel(logging.CRITICAL)
from boto.s3.connection import S3Connection
from boto.s3 import key
from boto.iam.connection import IAMConnection

from fabric.api import env,local, sudo,put,puts,run,lcd

from config import *
from cclib.utils import FileQueue, SpotInstance, Worker
from cclib.commoncrawl import CommonCrawl



env.user = 'ec2-user'
try:
    env.hosts = [line.strip() for line in file("temp/hosts").readlines()]
except:
    env.hosts = []

env.key_filename = key_filename

def setup_iam():
    """
    Sets up IAM policy, roles and instance profile
    """
    IAM = IAMConnection()
    profile = IAM.create_instance_profile(IAM_PROFILE)
    role = IAM.create_role(IAM_ROLE)
    IAM.add_role_to_instance_profile(IAM_PROFILE, IAM_ROLE)
    IAM.put_role_policy(IAM_ROLE, IAM_POLICY_NAME, IAM_POLICY)

def setup_common():
    """
    """
    #IAM
    try:
        setup_iam()
    except:
        print "Error while setting up IAM PROFILE, most likely due to existing profile"
        logging.exception("Error while setting up IAM PROFILE, most likely due to existing profile")
        pass
    #S3 bucket
    logging.getLogger('boto').setLevel(logging.CRITICAL)
    S3 = S3Connection()
    logging.info("Creating bucket "+OUTPUT_S3_BUCKET)
    S3.create_bucket(OUTPUT_S3_BUCKET)
    logging.info("bucket created")

def setup_job():
    """
    Sets up the queue adds all files (text or warc or wat or wet), creates bucket to store output
    """
    setup_common()
    crawl = CommonCrawl(CRAWL_ID)
    file_list = crawl.get_file_list(FILE_TYPE) # Text files
    file_queue = FileQueue(JOB_QUEUE,VISIBILITY_TIMEOUT,file_list)
    logging.debug("Adding "+str(len(file_list))+" "+FILE_TYPE+" files to queue "+JOB_QUEUE)
    file_queue.add_files()
    logging.debug("Finished adding files")
    print "Finished adding files"


def setup_test():
    """
    Sets up the queue adds all files (text or warc or wat or wet), creates bucket to store output
    """
    setup_common()
    crawl = CommonCrawl(CRAWL_ID)
    file_list = crawl.get_file_list(FILE_TYPE) # Text files
    file_queue = FileQueue(JOB_QUEUE,VISIBILITY_TIMEOUT,file_list)
    logging.debug("Adding "+str(len(file_list))+" "+FILE_TYPE+" files to queue "+JOB_QUEUE)
    file_queue.add_files(count=5)
    logging.debug("Finished adding files")
    print "Finished adding files"




def ls_ec2():
    """
    Lists current EC2 instances with current Job tag, and stores their public_dns_name to hosts.
    """
    with open('temp/hosts','w') as fh:
        for i,instance in enumerate(SpotInstance.get_spot_instances(REGION,EC2_Tag)):
            print instance.status()
            if instance.public_dns_name:
                fh.write(instance.public_dns_name+'\n')
                print instance.public_dns_name
                with open("temp/connect_"+str(i)+'.sh','w') as fssh:
                    fssh.write("#!/usr/bin/env sh\nssh -i "+env.key_filename+" "+env.user+'@'+instance.public_dns_name)
    with lcd('temp'):
        local('chmod a+x *.sh')
    print "Information about current spot instance has been added to temp/hosts"


def get_ec2():
    """
    Requests a spot EC2 instance
    """
    spot = SpotInstance(REGION,EC2_Tag)
    spot.request_instance(price,instance_type,image_id,key_name,USER_DATA,IAM_PROFILE,SPOT_REQUEST_VALID)


def rm_ec2():
    """
    Terminates all spot instances, clear hosts file
    """
    for s in SpotInstance.get_spot_instances(REGION,EC2_Tag):
        print "terminating", s.status()
        if s.instance_object and s.instance_object.state_code != 48:
            s.terminate()
        print "terminated"
    with file("temp/hosts","w") as f:
        f.write("")


def rm_bucket(bucket_name):
    """
    Deletes the specified bucket
    bucket_name : str
    """
    os.system('aws s3 rb s3://'+bucket_name+' --force') # faster

def ls_bucket():
    """
    Retrieves information about content stored in output bucket.
    """
    S3 = S3Connection()
    bucket = S3.get_bucket(OUTPUT_S3_BUCKET)
    keys = [example_key for example_key in bucket.list()]
    if keys:
        example = boto.s3.key.Key(bucket)
        example.key = random.sample(keys,1)[0]
        example.get_contents_to_filename("temp/example.json.gz")
    with open("data/index.json",'w') as fh:
        fh.write(json.dumps([str(key) for key in keys]))
    print "Number of keys in the output bucket ",len(keys)
    print "a randomly selected key is written to temp/example.json.gz"
    print "list of keys are stored in data/index.json\n"

def test_worker():
    """
    Runs worker.py in test mode after updating the local version of the common crawl library
    """
    worker = Worker(JOB_QUEUE,CRAWL_ID,example_process,S3Connection().get_bucket(OUTPUT_S3_BUCKET,validate=False),True)
    worker.start()

def test_init():
    """
    This task generates AWS cloud init user_data, and worker.py payload
    :return:
    """
    try:
        os.remove("temp/user_data.py")
        os.remove("temp/worker.py")
    except:
        pass
    fh = open("temp/user_data.py",'w')
    fh.write(USER_DATA)
    fh.close()
    fh = open("temp/worker.py",'w')
    fh.write(WORKER_CODE)
    fh.close()


def test_ec2(home_dir='/home/ec2-user'):
    """
    Updates, installs necessary packages on an EC2 instance.
    Upload library, boto configuration, worker code.
    Make sure that any changes made here are also reflected in USER_DATA script in config
    """
    test_init() # generate worker.py payload first
    sudo('yum update -y')
    sudo('yum install -y gcc-c++')
    sudo('yum install -y openssl-devel')
    sudo('yum install -y make')
    sudo('yum install -y python-devel')
    sudo('yum install -y python-setuptools')
    sudo('easy_install flask')
    sudo('pip install -y commoncrawllib')
    put('temp/worker.py','worker.py')


def reset_ec2():
    """
    Regenerates user_data.py and then kills all jobs on each host and launches user_data.py
    :return:
    """
    test_init()
    put('temp/user_data.py','user_data.py')
    try:
        sudo('killall python')
    except:
        pass
    sudo('python /home/ec2-user/user_data.py')


def purge():
    """
    Clear temp directory
    """
    local('rm -f temp/*')