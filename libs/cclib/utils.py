#!/usr/bin/env python
"""

"""
__author__ = 'aub3'

try:
    import ujson as json
except ImportError:
    import json

import base64, time, datetime, logging, gzip, StringIO
import boto.ec2
from boto.sqs.connection import SQSConnection
from boto.sqs.message import Message
from boto.s3.key import Key
import commoncrawl




class FileQueue(object):
    """
    A simple queue of files stored on SQS.
    """
    SQS = SQSConnection()

    def __init__(self,name,visibility_timeout=300,files=None):
        """
        Requires list of files and queue name
        """
        if files == None:
            files = []
        self.name = name
        self.files = files
        self.visibility_timeout = visibility_timeout
        self.queue = FileQueue.SQS.get_queue(name)
        if not self.queue:
            self.queue = FileQueue.SQS.create_queue(self.name,visibility_timeout=self.visibility_timeout) # set as default timeout

    def add_files(self,count=None):
        """
        if count is none then add all files to queue, otherwise add count files to queue
        """
        message_buffer =[]
        if count is None:
            count = len(self.files)
        while count:
            count -= 1
            message_buffer.append((count,base64.b64encode(self.files.pop()),0)) # required to maintain compatibility with
            if len(message_buffer) > 9:
                self.queue.write_batch(message_buffer)
                message_buffer = []
        if message_buffer:
            self.queue.write_batch(message_buffer)


    def clear(self):
        """
        Clears the queue. This is a costly operation.
        """
        self.queue.clear()

    def __iter__(self):
        return self

    def next(self): # wait for 5 minutes after sending message
        """ iterate over the queue"""
        if self.queue:
            messages = self.queue.get_messages(1,visibility_timeout=self.visibility_timeout)
            if messages:
                for m in messages:
                    return m
        raise StopIteration

    def delete_message(self,m):
        self.queue.delete_message(m)







class SpotInstance(object):

    @classmethod
    def get_spot_instances(cls,region,EC2_Tag):
        """
        Get all spot instances with specified EC2_Tag
        """
        connection  = boto.ec2.connect_to_region(region)
        requests = connection.get_all_spot_instance_requests()
        instances = []
        for request in requests:
            instances.append(SpotInstance(region,EC2_Tag,request.id,request.instance_id))
        return instances

    def __init__(self,region,tag,request_id=None,instance_id=None,):
        self.conn = boto.ec2.connect_to_region(region)
        self.request_id = request_id
        self.instance_id = instance_id
        self.public_dns_name = None
        self.price = None
        self.instance_type = None
        self.image_id = None
        self.key_name = None
        self.fulfilled = False
        self.instance_object = None
        self.valid_until = None
        self.tag = tag
        self.instance_profile = None
        self.user_data = ""
        if self.instance_id:
            self.fulfilled = True
            self.get_instance()

    def add_tag(self):
        if self.request_id:
            self.conn.create_tags([self.request_id], {"Tag":self.tag})


    def request_instance(self,price,instance_type,image_id,key_name,user_data,instance_profile,valid_mins):
        self.price = price
        self.instance_type = instance_type
        self.image_id = image_id
        self.key_name = key_name
        self.user_data = user_data
        self.instance_profile = instance_profile
        print "You are launching a spot instance request."
        print "It is important that you closely monitor and cancel unfilled requests using AWS web console."
        if raw_input("\n Please enter 'yes' to start >> ")=='yes':
            self.valid_until = (datetime.datetime.utcnow()+datetime.timedelta(minutes=valid_mins)).isoformat() # valid for 20 minutes from now
            print "request valid until UTC: ", self.valid_until
            spot_request = self.conn.request_spot_instances(price=price,instance_type=instance_type,image_id=image_id,key_name=key_name,valid_until=self.valid_until,user_data=self.user_data,instance_profile_name=self.instance_profile)
            self.request_id = spot_request[0].id
            time.sleep(4) # wait for some time, otherwise AWS throws up an error
            self.add_tag()
            print "requesting a spot instance"
        else:
            print "Did not request a spot instance"

    def check_allocation(self):
        if self.request_id:
            instance_id = self.conn.get_all_spot_instance_requests(request_ids=[self.request_id])[0].instance_id
            while instance_id is None:
                print "waiting"
                time.sleep(60) # Checking every minute
                print "Checking job instance id for this spot request"
                instance_id = self.conn.get_all_spot_instance_requests(request_ids=[self.request_id])[0].instance_id
                self.instance_id = instance_id
            self.get_instance()

    def get_instance(self):
            reservations = self.conn.get_all_reservations()
            for reservation in reservations:
                instances = reservation.instances
                for instance in instances:
                    if instance.id == self.instance_id:
                        self.public_dns_name =  instance.public_dns_name
                        self.instance_object = instance
                        return
    def status(self):
        return "request",self.request_id,"spot instance",self.instance_id,"with DNS",self.public_dns_name

    def terminate(self):
        print "terminating spot instance",self.instance_id,self.public_dns_name
        if self.instance_object:
            self.instance_object.terminate()


class Worker(object):
    """
    A simple worker object
    """
    def __init__(self,queue_name,crawl_id,process,output_bucket,test):
        """
        :param queue:
        :param crawl:
        :param process:
        :param output_bucket:
        :param test:
        """
        self.queue_name = queue_name
        self.queue = FileQueue(self.queue_name,files=None)
        self.crawl = commoncrawl.CommonCrawl(crawl_id)
        self.test = test
        self.output_bucket = output_bucket
        self.process = process

    def store(self, fname, data):
        try:
            item = Key(self.output_bucket)
            item.key = fname.split('segments/')[1].replace('/','__')
            stringio = StringIO.StringIO()
            gzip_file = gzip.GzipFile(fileobj=stringio, mode='w')
            gzip_file.write(json.dumps(data))
            gzip_file.close()
            item.set_contents_from_string(stringio.getvalue(),reduced_redundancy=True) # reduced_redundancy=True to save costs
        except:
            logging.exception("error while storing data on S3")

    def start(self):
        logging.debug("starting queue "+self.queue_name)
        for m in self.queue:
            fname = m.get_body()
            logging.debug("starting "+fname)
            data,store_flag,delete_flag = self.process(self.crawl.get_file(fname),fname)
            if store_flag:
                self.store(fname,data)
            if self.test or delete_flag:
                logging.debug("did not delete the message")
                break # stop after processing one message
            else:
                self.queue.delete_message(m)
            logging.debug("finished "+fname)
        logging.debug("finished queue "+self.queue_name)




if __name__ == '__main__':
    # some test code
    crawl = commoncrawl.CommonCrawl('2013_1')
    wat_queue = FileQueue('aksay_test_queue',files=crawl.wat)
    wat_queue.add_files(5)
    for m in wat_queue:
        print m.get_body()
        wat_queue.delete_message(m)
