# Copyright (c) 2015
#
# All rights reserved.
#
# This file is distributed under the Clear BSD license.
# The full text can be found in LICENSE in the root directory.

from boardfarm.devices import prompt
from boardfarm.tests import rootfs_boot


class IGMPv3_Running(rootfs_boot.RootFSBootTest):
    '''IGMP Proxy daemon mcproxy is up and running.'''
    def runTest(self):
        board = self.dev.board

        board.sendline('\nps | grep mcproxy')
        board.expect('/usr/sbin/mcproxy -f /etc/mcproxy.conf', timeout=5)
        board.expect(prompt)


class IGMPv3_Config(rootfs_boot.RootFSBootTest):
    '''IGMP Proxy daemon mcproxy config is set correctly.'''
    def runTest(self):
        board = self.dev.board

        board.sendline('\nuci show mcproxy')
        board.expect_exact('mcproxy.config=mcproxy', timeout=5)
        board.expect_exact('mcproxy.config.protocol=IGMPv3', timeout=5)
        board.expect_exact('mcproxy.@pinstance[0]=pinstance', timeout=5)
        board.expect_exact('mcproxy.@pinstance[0].name=mcproxy1', timeout=5)
        board.expect(prompt)
        board.sendline('cat /etc/mcproxy.conf')
        board.expect('protocol IGMPv3;', timeout=5)
        board.expect('pinstance mcproxy1: "eth0" ==> "br-lan";')
        board.expect(prompt)


class IGMPv3_StopStart(rootfs_boot.RootFSBootTest):
    '''IGMP Proxy daemon mcproxy can be stopped and started without rebooting.'''
    def runTest(self):
        board = self.dev.board

        board.sendline('\n/etc/init.d/mcproxy stop')
        board.expect(prompt)
        board.sendline('ps | grep mcproxy')
        board.expect(prompt)
        assert '/usr/sbin/mcproxy' not in board.before
        board.sendline('/etc/init.d/mcproxy start')
        board.sendline('ps | grep mcproxy')
        board.expect('/usr/sbin/mcproxy -f /etc/mcproxy.conf', timeout=5)
        board.expect(prompt)
