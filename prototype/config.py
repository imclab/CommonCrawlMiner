__author__ = 'aub3'
import logging, inspect, base64
import ujson as json

# Put AWS credentials in /etc/boto.cfg for use on local machine
key_filename = '/users/aub3/.ssh/cornellmacos.pem' # please replace this with path to your pem


# following IAM role is used when launching instance
IAM_ROLE = "ccSpot_role"
IAM_PROFILE = "ccSpot_profile"
IAM_POLICY_NAME = "ccSpt_policy"
IAM_POLICY ="""{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Stmt1399521628000",
      "Effect": "Allow",
      "Action": [
        "s3:*"
      ],
      "Resource": [
        "*"
      ]
    },
    {
      "Sid": "Stmt1399521640000",
      "Effect": "Allow",
      "Action": [
        "sqs:*"
      ],
      "Resource": [
        "*"
      ]
    }
  ]
}"""


##########
#
# Instance Configuration
#
#########
REGION = 'us-east-1'
price = 0.40 # 60 cents per hour slightly above the reserve price of the r3.8xlarge instance on the spot market
instance_type = 'r3.8xlarge'
image_id = 'ami-978d91fe' # default AMI for Amazon Linux HVM
key_name = 'cornellmacos' # replace with name of your configured key-pair
NUM_WORKERS = 40 # Number of worker processes per machine
VISIBILITY_TIMEOUT = 1200

##########
#
# Job Configuration
#
#########
EC2_Tag = "cc_proto"
JOB_QUEUE = 'cc_proto' # SQS queue name
OUTPUT_S3_BUCKET = 'cc_proto' # S3 bucket
FILE_TYPE = "wat" # Type of files you wish to process choose from {"wat","wet","text","warc"}
CRAWL_ID = "2014_4" # ALL crawls, you can specify others  E.g. 2013_1 first crawl in 2013
SPOT_REQUEST_VALID = 20 # Minutes within which the spot request must be full filled otherwise it is cancelled
MAX_TIME_MINS = 55 # maxiumum amount of time the instance should run 60 * 10 hours = 600 minutes (This limits the cost in case you forget to terminate the instance)

#CODE_BUCKET = "akshay_code" # bucket used to store code & configuration make sure this is different from output bucket
#CODE_KEY = "akshayccdemo" # key for storing code which will be downloaded by user-data script

#######
# Worker Header
#######
WORKER_HEADER = """
__author__ = 'aub3'
import logging,os
import simplejson as json
logging.basicConfig(filename='worker_'+str(os.getpid())+'.log',level=logging.DEBUG,format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger('boto').setLevel(logging.CRITICAL)
from boto.s3.connection import S3Connection
from cclib.utils import Worker

"""

WORKER_MAIN = """


if __name__ == '__main__':
    CONN = S3Connection()
    worker = Worker('<JOB_QUEUE>','<CRAWL_ID>',example_process,CONN.get_bucket('<OUTPUT_S3_BUCKET>',validate=False),False)
    worker.start()
""".replace('<JOB_QUEUE>',JOB_QUEUE).replace('<CRAWL_ID>',CRAWL_ID).replace('<OUTPUT_S3_BUCKET>',OUTPUT_S3_BUCKET)



#########
# Process code
#########

def example_process(file_object,filename):
    error_count = 0
    index = []
    error = False
    store_flag = True
    delete_flag = False
    try:
        for line in file_object:
            line = line.strip()
            if line.startswith('{"Envelope') and '"WARC-Type":"response"' in line:
                try:
                    entry = json.loads(line)
                    url = entry['Envelope']['WARC-Header-Metadata']['WARC-Target-URI']
                    warc_type = entry['Envelope']['WARC-Header-Metadata']['WARC-Type']
                    content_length = entry['Envelope']['Actual-Content-Length']
                    fname = entry['Container']['Filename']
                    offset = entry['Container']['Offset']
                    index.append([url,warc_type,content_length,fname,offset])
                except:
                    error_count += 1
                    pass
    except:
        logging.exception("error while processing file")
        error =True
        pass
    logging.debug(str(error_count))
    logging.debug(str(error))
    logging.debug(str(len(index)))
    return {'count':len(index),
            'index':index,
            'line_errors': error_count,
            "filename":filename,
            "read_error":error
            },store_flag,delete_flag

#####
#
# Worker
#
######
WORKER_CODE = WORKER_HEADER + ''.join(inspect.getsourcelines(example_process)[0]) + WORKER_MAIN


USER_DATA= """#!/usr/bin/env python
from boto.s3.connection import S3Connection
from boto.s3 import key
import os,base64

os.system('yum update -y')
# install GCC, Make, Setuptools etc.
os.system('yum install -y gcc-c++')
os.system('yum install -y openssl-devel')
os.system('yum install -y make')
os.system('yum install -y golang')
os.system('yum install -y python-devel')
os.system('yum install -y python-setuptools')
os.system('yum install -y python-pip')
os.system('easy_install flask')
os.system('pip install --upgrade simplejson')
os.system('pip install --upgrade ujson')
os.system('easy_install --upgrade commoncrawllib')
os.system('yum install -y gcc-c++ &')
os.system('screen -d -m shutdown -h <MAX_TIME_MINS>; sleep 1')

PAYLOAD = \"\"\"<WORKER_CODE>\"\"\"
fh = open('/home/ec2-user/worker.py','w')
fh.write(base64.decodestring(PAYLOAD))
fh.close()

# S3 = S3Connection()
# code_bucket = S3.get_bucket("<CODE_BUCKET>") # Bucket where code is stored
# code = key.Key(code_bucket)
# code.key = "<CODE_KEY>" # Key for the code
# code.get_contents_to_filename("/root/code.tar.gz")
# os.system('cd /root/;tar -xzf code.tar.gz')
for worker in range(<NUM_WORKERS>):
     os.system('cd /home/ec2-user;screen -d -m python worker.py; sleep 1')

""".replace("<WORKER_CODE>",base64.encodestring(WORKER_CODE)).replace("<NUM_WORKERS>",str(NUM_WORKERS)).replace("<MAX_TIME_MINS>",str(MAX_TIME_MINS))

