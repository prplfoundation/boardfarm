# Copyright (c) 2015
#
# All rights reserved.
#
# This file is distributed under the Clear BSD license.
# The full text can be found in LICENSE in the root directory.

import time

from boardfarm.devices import prompt
from boardfarm.lib.installers import install_lighttpd
from boardfarm.tests import rootfs_boot


class Connection_Stress(rootfs_boot.RootFSBootTest):
    '''Measured CPU use while creating thousands of connections.'''

    concurrency = 25
    num_conn = 5000

    # for results
    reqs_per_sec = 0

    def runTest(self):
        board = self.dev.board
        wan = self.dev.wan
        lan = self.dev.lan

        install_lighttpd(wan)
        wan.sendline('/etc/init.d/lighttpd start')
        wan.expect(prompt)
        # Wan device: Create small file in web dir
        fname = 'small.txt'
        cmd = '\nhead -c 10000 /dev/urandom > /var/www/%s' % fname
        wan.sendline(cmd)
        wan.expect(prompt)
        # Lan Device: download small file a lot
        # TODO: this is actually a 404 for lighthttpd config issues?
        url = 'http://%s/%s' % (wan.gw, fname)
        # Start CPU monitor
        board.collect_stats(stats=['mpstat'])
        # Lan Device: download small file a lot
        lan.sendline('\nab -dn %s -c %s %s' %
                     (self.num_conn, self.concurrency, url))
        lan.expect('Benchmarking')
        timeout = 0.05 * self.num_conn
        if 0 != lan.expect([
                r'Requests per second:\s+(\d+)',
                'apr_socket_recv: Connection reset by peer'
        ],
                           timeout=timeout):
            raise Exception("ab failed to run")
        self.reqs_per_sec = int(lan.match.group(1))
        lan.expect(prompt)

        self.recover()

    def recover(self):
        board = self.dev.board
        lan = self.dev.lan

        lan.sendcontrol('c')
        time.sleep(5)  # Give router a few seconds to recover
        board.parse_stats(dict_to_log=self.logged)
        avg_cpu = self.logged['mpstat']
        msg = "ApacheBench measured %s connections/second, CPU use = %s%%." % (
            self.reqs_per_sec, avg_cpu)
        self.result_message = msg


class Connection_Stress_Lite(Connection_Stress):
    '''Measured CPU use while creating thousands of connections.'''

    concurrency = 5
    num_conn = 500


class Connection_Stress_Intense(Connection_Stress):
    '''Measured CPU use while creating thousands of connections.'''

    concurrency = 25
    num_conn = 20000
