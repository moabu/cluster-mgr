#!/bin/sh

docker build \
    --rm \
    --force-rm \
    --build-arg CM_DOWNLOAD_TS=$(date +'%s') \
    -t gluufederation/clustermgr .
