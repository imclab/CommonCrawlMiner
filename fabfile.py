__author__ = 'aub3'
from fabric.api import env,local,sudo,put,cd,lcd

def test_lib():
    with lcd("libs"):
        local("python setup.py install")


def deploy_lib():
    with lcd("libs"):
        local("python setup.py sdist upload")

