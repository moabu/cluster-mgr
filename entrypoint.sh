#!/bin/bash
set -e

ssh-keygen -b 2048 -t rsa -f $HOME/.ssh/id_rsa -q -N ""
service redis-server start
clustermgr-celery & clustermgr-beat & clustermgr-cli run
