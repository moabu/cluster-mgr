#!/usr/bin/python

import json
import os
import sys

criteria = {'time':'', 'type':''}

for arg in sys.argv[1:]:
    if ':' in arg:
        n = arg.find(':')
        k = arg[:n]
        v = arg[n+1:]
        criteria[k] = v

filebeat_fn = '/tmp/gluu-filebeat'

matched = False
if os.path.exists(filebeat_fn):
    with open(filebeat_fn) as f:
        for l in f:
            jl = json.loads(l)
            if not matched and jl['fields']['type'] == criteria['type'] and jl['@timestamp'] > criteria['time']:
                matched = True

            if matched:
                print l,

    if not matched:
        with open(filebeat_fn) as f:
            for l in f:
                print l,
