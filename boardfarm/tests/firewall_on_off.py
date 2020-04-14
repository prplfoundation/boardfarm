# Copyright (c) 2015
#
# All rights reserved.
#
# This file is distributed under the Clear BSD license.
# The full text can be found in LICENSE in the root directory.

from boardfarm.devices import prompt
from boardfarm.tests import rootfs_boot


class FirewallOFF(rootfs_boot.RootFSBootTest):
    '''Turned router firewall off.'''
    def runTest(self):
        board = self.dev.board

        board.sendline('\nuci set firewall.@defaults[0].forward=ACCEPT')
        board.expect('uci set firewall')
        board.expect(prompt)
        board.sendline('uci set firewall.@zone[0].forward=ACCEPT')
        board.expect(prompt)
        board.sendline('uci set firewall.@zone[1].input=ACCEPT')
        board.expect(prompt)
        board.sendline('uci set firewall.@zone[1].forward=ACCEPT')
        board.expect(prompt)
        board.sendline('uci commit firewall')
        board.expect(prompt)
        board.firewall_restart()


class FirewallON(rootfs_boot.RootFSBootTest):
    '''Turned router firewall on.'''
    def runTest(self):
        board = self.dev.board

        board.sendline('\nuci set firewall.@defaults[0].forward=REJECT')
        board.expect('uci set firewall')
        board.expect(prompt)
        board.sendline('uci set firewall.@zone[0].forward=REJECT')
        board.expect(prompt)
        board.sendline('uci set firewall.@zone[1].input=REJECT')
        board.expect(prompt)
        board.sendline('uci set firewall.@zone[1].forward=REJECT')
        board.expect(prompt)
        board.sendline('uci commit firewall')
        board.expect(prompt)
        board.firewall_restart()
