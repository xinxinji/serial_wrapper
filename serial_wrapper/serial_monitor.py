# -*- coding: utf-8 -*-
from __future__ import print_function
import sys
import socket
import threading
import time

_ver = sys.version_info
is_py2 = (_ver[0] == 2)
is_py3 = (_ver[0] == 3)

if is_py2:
    from contextlib import contextmanager

    @contextmanager
    def ignored(*exceptions):
        try:
            yield
        except exceptions:
            pass

elif is_py3:
    from contextlib import suppress as ignored

from serial_wrapper import SOCKET_STOPFLAG
from serial_wrapper import LOCALHOST

BUFSIZ = 1024
CONSOLE_CODING = 'UTF-8'

class SerialMonitor(object):
    def __init__(self, port, coding):
        self.sleep_time = 0.001
        self.connect_retry = 3
        self.coding = coding
        self.client=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        for _ in range(self.connect_retry):
            try:
                self.client.connect((LOCALHOST, int(port)))
            except Exception as e:
                print("Connect Exception: {!r}".format(e))
                print("Wait 3s then retry")
                time.sleep(3)
            else:
                print("Connect Success")
                break
        else:
            print("Retry {} connect fail".format(self.connect_retry))
            input('Press Any Key to exit')
            sys.exit(1)

    def __del__(self):
        with ignored(Exception):
            self.client.close()

    def start(self):
        self.thread = threading.Thread(target=self.receive_data)
        self.thread.daemon = True
        self.thread.start()

    def join(self):
        self.thread.join()

    def receive_data(self):
        data=u''
        while 1:
            try:
                data = self.client.recv(BUFSIZ)
            except Exception as e:
                print("")
                print("="*40)
                print("Receive Exception: {!r}".format(e))
                print("="*40)
                break
            if data == SOCKET_STOPFLAG:
                print("")
                print("="*40)
                print("Receive STOPFLAG, will close soon")
                print("="*40)
                time.sleep(10)
                break
            try:
                print(data.decode(self.coding), end='')
            except Exception as e:
                print("")
                print("="*40)
                print("Print Exception: {!r}".format(e))
                print("="*40)
                continue
            time.sleep(self.sleep_time)

if __name__ == '__main__':
    client = SerialMonitor(sys.argv[1], sys.argv[2])
    client.start()
    client.join()
