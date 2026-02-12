import random
import os

def formatProxy(_ip):
    _ip = _ip.split(":")

    if len(_ip) == 2:  # means IP proxy
        _ip = {
            "http": f'http://{_ip[0]}:{_ip[1]}',
            "https": f'http://{_ip[0]}:{_ip[1]}'
        }

    else:
        _ip = {
            "http": f'http://{_ip[2]}:{_ip[3]}@{_ip[0]}:{_ip[1]}',
            "https": f'http://{_ip[2]}:{_ip[3]}@{_ip[0]}:{_ip[1]}'
        }
    return _ip


def read_proxy_file(path):
    name = os.getcwd()
    with open(name + "\\twitter\\proxies.txt") as f:
        proxyfile = f.read().splitlines()

    _list = []
    for proxy in proxyfile:
        _list.append(formatProxy(proxy))

    return _list


def getProxy():
    global proxylist
    return random.choice(proxylist)


def initialize(filename):
    global proxylist
    proxylist = read_proxy_file(filename)


proxylist = None