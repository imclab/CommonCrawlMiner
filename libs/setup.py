#!/usr/bin/env python
__author__ = 'aub3'
from distutils.core import setup

setup(name='commoncrawllib',
      version='0.7',
      description='Common Crawl Library with utilities',
      author='Akshay Bhat',
      author_email='aub3@cornell.edu',
      url='http://www.akshaybhat.com/',
      packages=['cclib'],
      package_dir={'cclib': 'cclib'},
      package_data={'cclib': ['data/*.gz']},
      requires=['boto']
     )