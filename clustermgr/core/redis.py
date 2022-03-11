import os
from redislite import Redis

class RedisConn():
    def __init__(self):
        self.data_dir = os.path.join(os.path.expanduser('~'), '.redis')
        if not os.path.exists(self.data_dir):
            os.mkdir(self.data_dir)
        print("Starting Redis")
        self.conn = Redis(os.path.join(self.data_dir, 'redis.db'))
        print("Redis socket file", self.conn.socket_file)
