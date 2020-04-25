import os

redis_node_port = 16381
sentinel_node_port = 26381

cur_dir = os.path.dirname(os.path.realpath(__file__))

sentinelMasterGroupName = 'GluuCluster'

def get_stunnel_config(servers, server=None, osclone='deb'):

    # if server is None, it is local server
    # WARNING: if osclone is rpm replace service unit file

    def_dict = {
                'deb': {'uid': 'stunnel4', 'gid': 'stunnel4', 'pid': '/var/run/stunnel4/stunnel.pid'},
                'rpm': {'uid': 'nobody', 'gid': 'nobody', 'pid': '/var/run/stunnel/stunnel.pid'},
                }

    stunnel_conf_list = ['cert = /etc/stunnel/redis-server.pem',
                         'pid = ' + def_dict[osclone]['pid'],
                         'sslVersion = TLSv1',

                         ]
    if osclone == 'deb':
        stunnel_conf_list += [
                            'setuid = ' + def_dict[osclone]['uid'],
                            'setgid = ' + def_dict[osclone]['gid'],
                            ]

    stunnel_conf_list.append('')

    if server:
        stunnel_conf_list.append('[redis-server]')
        stunnel_conf_list.append('accept = {}:16379'.format(server.data.ip))
        stunnel_conf_list.append('connect = 127.0.0.1:6379')
        stunnel_conf_list.append('')

        stunnel_conf_list.append('[redis-sentinel]')
        stunnel_conf_list.append('accept = {}:36379'.format(server.data.ip))
        stunnel_conf_list.append('connect = 127.0.0.1:26379')
        stunnel_conf_list.append('')

    for i, cs in enumerate(servers):
        section_name = '[redis-node{}]'.format(i+1)
        stunnel_conf_list.append(section_name)
        stunnel_conf_list.append('client = yes')
        stunnel_conf_list.append('accept = 127.0.0.1:{}'.format(redis_node_port + i))
        stunnel_conf_list.append('connect = {}:16379'.format(cs.data.ip))
        stunnel_conf_list.append('')


    for i, cs in enumerate(servers):
        section_name = '[redis-sentinel-node{}]'.format(i+1)
        stunnel_conf_list.append(section_name)
        stunnel_conf_list.append('client = yes')
        stunnel_conf_list.append('accept = 127.0.0.1:{}'.format(sentinel_node_port + i))
        stunnel_conf_list.append('connect = {}:36379'.format(cs.data.ip))
        stunnel_conf_list.append('')

    return '\n'.join(stunnel_conf_list)



def get_redis_config(servers, conf_type, osclone='deb'):

    def_dict = {
                'deb': {'pid': '/var/run/redis/{}.pid'.format(conf_type)},
                'rpm': {'pid': '/var/run/{}.pid'.format(conf_type)},
                }

    redis_conf_tmp_filename = os.path.join(cur_dir, conf_type + '.conf.temp')

    nq = 1 if len(servers) <= 3 else 2
    quorum = len(servers) - nq

    format_dict = {'quorum': quorum, 'pidfile': def_dict[osclone]['pid'], 'sentinelMasterGroupName': sentinelMasterGroupName}
    format_dict['redis_master_node'] = redis_node_port
    confs = {}

    for i, cs in enumerate(servers):

        with open(redis_conf_tmp_filename) as f:
            conf_tmp = f.read()

        format_dict['redis_node_port'] = redis_node_port + i
        format_dict['sentinel_node_port'] = sentinel_node_port + i

        if (conf_type != 'sentinel') and cs.id != servers[0].id:
            conf_tmp += 'slaveof 127.0.0.1 {}\n'.format(redis_node_port)

        conf_tmp = conf_tmp % format_dict
        confs[cs.id] = conf_tmp

    return confs


if __name__ == '__main__':

    # Example usage

    class cache_server:
        pass

    # Cache servers
    cs1 = cache_server()
    cs1.id = 1
    cs1.data = cache_server()
    cs1.data.ip = '192.168.56.11'

    cs2 = cache_server()
    cs2.id = 2
    cs2.data = cache_server()
    cs2.data.ip = '192.168.56.12'

    cs3 = cache_server()
    cs3.id = 3
    cs3.data = cache_server()
    cs3.data.ip = '192.168.56.13'

    servers = [cs1, cs2, cs3]

    # write redis config
    for conf_type in ('redis', 'sentinel'):
        redis_confs = get_redis_config(servers, conf_type=conf_type, osclone='rpm')
        for i, c in enumerate(redis_confs):
            cdir = str(i + 1)
            if not os.path.exists(cdir):
                os.mkdir(cdir)
            with open('{}/{}.conf'.format(cdir, conf_type), 'w') as w:
                w.write(redis_confs[c])

    # write stunnel config for cache nodes
    for i, c in enumerate(servers):
        cdir = str(i + 1)
        stunnel_conf = get_stunnel_config(servers, servers[i], osclone='rpm')
        with open('{}/stunnel.conf'.format(cdir), 'w') as w:
            w.write(stunnel_conf)

    # write stunnel config to be used by gluu servers
    stunnel_conf = get_stunnel_config(servers, osclone='rpm')
    with open('stunnel-gluu.conf', 'w') as w:
            w.write(stunnel_conf)
