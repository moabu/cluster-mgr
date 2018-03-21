#!/bin/sh
gunicorn  --access-logfile - --error-log - -w 2 -b 127.0.0.1:5000 clusterapp:app
