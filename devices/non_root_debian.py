# Copyright (c) 2015
#
# All rights reserved.
#
# This file is distributed under the Clear BSD license.
# The full text can be found in LICENSE in the root directory.

import sys
import time
import pexpect
import base
import argparse

from termcolor import colored, cprint


class NonRootDebianBox(base.BaseDevice):
    '''
    A linux machine running an ssh server, not running as root.

    This class is different from DebianBox in some unique ways. First, most of
    the function calls here call shell scripts via sudo. Those shell
    scripts, not included, call into local_debian_runner.py on the actual box itself.
    This requires a copy of Boardfarm on your debian box.
    '''

    prompt = ['root\\@.*:.*#', '/ # ', ".*:~ #", ".*:~.*\\$", ".*\\@.*:.*\\$" ]

    def __init__(self,
                 name,
                 color,
                 username,
                 password,
                 port,
                 output=sys.stdout,
                 reboot=False,
                 location=None
                 ):
        if name is None:
            return
        pexpect.spawn.__init__(self,
                               command="ssh",
                               args=['%s@%s' % (username, name),
                                     '-p', port,
                                     '-o', 'StrictHostKeyChecking=no',
                                     '-o', 'UserKnownHostsFile=/dev/null'])
        self.name = name
        self.color = color
        self.output = output
        self.username = username
        self.password = password
        self.port = port
        self.location = location
        cprint("%s device console = %s" % (name, colored(color, color)), None, attrs=['bold'])
        try:
            i = self.expect(["yes/no", "assword:", "Last login"], timeout=30)
        except pexpect.TIMEOUT as e:
            raise Exception("Unable to connect to %s." % name)
        except pexpect.EOF as e:
            if hasattr(self, "before"):
                print(self.before)
            raise Exception("Unable to connect to %s." % name)
        if i == 0:
            self.sendline("yes")
            i = self.expect(["Last login", "assword:"])
        if i == 1:
            self.sendline(password)
        else:
            pass
        self.expect(self.prompt)

        if reboot:
            self.reset()

        self.logfile_read = output

    def reset(self):
        self.sendline('sudo reboot')
        self.expect(['going down','disconnected', 'closed'])
        try:
            self.expect(self.prompt, timeout=10)
        except:
            pass
        time.sleep(15)  # Wait for the network to go down.
        for i in range(0, 20):
            try:
                pexpect.spawn('ping -w 1 -c 1 ' + self.name).expect('64 bytes', timeout=1)
            except:
                time.sleep(1)
                print(self.name + " not up yet, after %s tries." % (i))
            else:
                print("%s is back after %s tries, waiting for network daemons to spawn." % (self.name, i))
                time.sleep(15)
                break
        self.__init__(self.name, self.color,
                      self.username,
                      self.password, self.port,
                      output=self.output,
                      reboot=False)

    def get_ip_addr(self, interface):
        self.sendline("\nifconfig %s" % interface)
        self.expect('addr:(\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3}).*(Bcast|P-t-P):', timeout=5)
        ipaddr = self.match.group(1)
        self.expect(self.prompt)
        return ipaddr

    def ip_neigh_flush(self):
        self.sendline('\nsudo ip_neigh_flush')
        self.expect('flush all')
        self.expect(self.prompt)

    def turn_on_pppoe(self):
        self.sendline('sudo turn_on_pppoe')
        self.expect(self.prompt)

    def turn_off_pppoe(self):
        pass

    def restart_tftp_server(self):
        self.sendline('\nsudo restart_tftp_server')
        self.expect('Restarting')
        self.expect(self.prompt)

    def configure(self, kind):
        if kind == "wan_device":
            self.setup_as_wan_gateway()
        elif kind == "lan_device":
            self.setup_as_lan_device()

    def setup_as_wan_gateway(self):
        self.sendline('\necho "needs to be setup via root. If not setup, this is bad."')

    def setup_as_lan_device(self):
        self.sendline('\necho "needs to be setup via root. If not setup, this is bad"')

    def start_lan_client(self):
        self.sendline('\nsudo start_lan_client')
        self.expect(self.prompt)
