mkdir -p /root/influxdb/meta &
/opt/influxdb-1.4.3-1/influxd &
clustermgr-cli db upgrade &
redis-server /etc/redis.conf&
clustermgr-beat &
clustermgr-celery &
clustermgr-cli run -h 0.0.0.0 -p 5000