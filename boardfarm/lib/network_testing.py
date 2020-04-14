# Copyright (c) 2015
#
# All rights reserved.
#
# This file is distributed under the Clear BSD license.
# The full text can be found in LICENSE in the root directory.
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

import ipaddress

import pexpect
import six
from boardfarm.lib.common import retry_on_exception


def tcpdump_capture(device,
                    interface,
                    port=None,
                    capture_file='pkt_capture.pcap',
                    filters=None):
    """Capture network traffic using tcpdump.
    Note: This function will keep capturing until you Kill tcpdump.
    The kill_process method can be used to kill the process.

    :param device: lan or wan
    :type device: Object
    :param interface: interface on which the packets to be captured (eg: eth0)
    :type interface: String
    :param port: Port number to capture. Can be a single port or range of ports (for https: 443 or 443-433)
    :type port: String
    :param capture_file: Filename to create in which packets shall be stored. Defaults to 'pkt_capture.pcap'
    :type capture_file: String, Optional
    :param filters: dictionary of additional filters and filter_values as key value pair (eg: {"-v":"","-c": "4"})
    :type filters: dict
    :return: Console ouput of tcpdump sendline command.
    :rtype: string
    """
    base = "tcpdump -i %s -n -w %s " % (interface, capture_file)
    run_background = " &"
    filter_str = ' '.join([' '.join(i)
                           for i in filters.items()]) if filters else ''
    if port:
        device.sudo_sendline(base + "\'portrange %s\' " % (port) + filter_str +
                             run_background)
    else:
        device.sudo_sendline(base + filter_str + run_background)
    device.expect_exact('tcpdump: listening on %s' % interface)
    return device.before


def kill_process(device, process="tcpdump"):
    """Kill any active process

    :param device: lan or wan
    :type device: Object
    :param process: process to kill, defaults to tcpdump
    :type process: String, Optional
    :return: Console ouput of sync sendline command after kill process
    :rtype: string
    """
    device.sudo_sendline("killall %s" % process)
    device.expect(device.prompt)
    device.sudo_sendline("sync")
    device.expect(device.prompt)
    return device.before


def tcpdump_read(device, capture_file, protocol='', opts=''):
    """Read the tcpdump packets and deletes the capture file after read

    :param device: lan or wan
    :type device: Object
    :param capture_file: Filename in which the packets were captured
    :type capture_file: String
    :param protocol: protocol to filter. Defaults to ''
    :type protocol: String, Optional
    :param opts: can be more than one parameter but it should be joined with "and" eg: ('host '+dest_ip+' and port '+port). Defaults to ''
    :type opts: String, Optional
    :return: Output of tcpdump read command.
    :rtype: string
    """
    if opts:
        protocol = protocol + ' and ' + opts
    device.sudo_sendline("tcpdump -n -r %s %s" % (capture_file, protocol))
    device.expect(device.prompt)
    output = device.before
    device.sudo_sendline("rm %s" % (capture_file))
    device.expect(device.prompt)
    return output


def tshark_read(device, capture_file, packet_details=False, filter_str=None):
    """Read the packets via tshark

    :param device: lan or wan...
    :type device: Object
    :param capture_file: Filename in which the packets were captured
    :type capture_file: String
    :param packet_details: output of packet tree (Packet Details)
    :type packet_details: Bool
    :param filter_str: capture filter, ex. 'data.len == 1400'
    :type filter_str: String
    """
    command_string = 'tshark -r {} '.format(capture_file)
    if packet_details:
        command_string += '-V '
    if filter_str:
        command_string += '\'{}\''.format(filter_str)

    device.sendline(command_string)
    device.expect(pexpect.TIMEOUT, timeout=5)
    output = device.before
    device.sudo_sendline("rm %s" % (capture_file))
    device.expect(device.prompt)
    return output


def sip_read(device, capture_file):
    """Read and filter SIP packets from the captured file.
    The Session Initiation Protocol is a signaling protocol used for initiating, maintaining, and
    terminating real-time sessions that include voice, video and messaging applications

    :param device: lan or wan
    :type device: Object
    :param capture_file: Filename in which the packets were captured
    :type capture_file: String
    :return: Output of tshark read command.
    :rtype: string
    """

    device.sudo_sendline("tshark -r %s -Y sip" % (capture_file))
    device.expect(device.prompt)
    output_sip = device.before
    return output_sip


def rtp_read_verify(device, capture_file):
    """To filter RTP packets from the captured file and verify. Delete the capture file after verify.
    Real-time Transport Protocol is for delivering audio and video over IP networks.

    :param device: lan or wan
    :type device: Object
    :param capture_file: Filename in which the packets were captured
    :type capture_file: String
    """
    device.sudo_sendline("tshark -r %s -Y rtp > rtp.txt" % (capture_file))
    device.expect_prompt()
    device.sendline("grep RTP rtp.txt|wc -l")
    device.expect("[1-9]\d*")
    device.expect_prompt()
    device.sudo_sendline("rm rtp.txt")
    device.expect_prompt()


def basic_call_verify(output_sip, ip_src):
    """To verify basic call flow with sip messages.

    :param output_sip: return value of sip_read function
    :type output_sip: String
    :param ip_src: IP of device which initiates the call
    :type ip_src: String
    """
    import re
    sip_msg = re.search(
        ".*" + ip_src + ".*INVITE.*?" + ip_src + "\s+SIP.*100\s+Trying.*?" +
        ip_src + "\s+SIP.*180\s+Ringing.*?" + ip_src +
        "\s+SIP\/SDP.*200\s+OK.*?" + ip_src + ".*ACK.*?" + ip_src +
        ".*BYE.*?" + ip_src + "\s+SIP.*200\s+OK\s+\|", output_sip, re.DOTALL)
    assert sip_msg is not None, "SIP call failed"


def nmap_cli(device,
             ip_address,
             port,
             protocol=None,
             retry=0,
             timing='',
             optional=''):
    """To run port scanning on the specified target.Port scan is a method for determining which ports on a interface are open.
    This method is used to perform port scanning on the specified port range of the target ip specified from the device specified.

    :param device: device on which nmap command to run
    :type device: object
    :param ip_address: target ip address
    :type ip_address: string
    :param port: port range to be scanned
    :type port: string
    :param protocol: protocol (tcp/ucp/both), default to None
    :type protocol: String, Optional
    :param retry: maximum number of retries, defaults to 0
    :type retry: integer, Optional
    :param timing: Timing templates(-T[1-4]), defaults to ''
                   Each template will have different timings for different actions
    :type timing: String, Optional
    :param optional: Other options like minimum rate limit(packets/sec), max rate limit(packets/sec)
    :type optional: String
    :return: Output of namp command.
    :rtype: string
    """

    if not protocol:
        protocol = "both"
    ipv6 = '-6' if 'IPv6Address' == type(
        ipaddress.ip_address(six.text_type(ip_address))).__name__ else ''
    protocol_commandmap = {"tcp": "-sT", "udp": "-sU", "both": "-sT -sU"}
    device.sudo_sendline(
        "nmap %s %s %s %s -p%s -Pn -r -max-retries %s %s > nmap_logs.txt" %
        (ipv6, timing, protocol_commandmap[protocol], ip_address, port, retry,
         optional))
    retry_on_exception(device.expect, (device.prompt, ), retries=16, tout=30)
    device.sendline("cat nmap_logs.txt")
    device.expect(device.prompt)
    nmap_output = device.before
    device.sendline("rm nmap_logs.txt")
    device.expect(device.prompt)
    return nmap_output


def ssh_service_verify(device,
                       dest_device,
                       ip,
                       opts="",
                       ssh_key="-oKexAlgorithms=+diffie-hellman-group1-sha1"):
    """This function will try to verify if SSH service is running on a target device.
    If the ssh connection expects key exchange, then ssh_key provided is used to add the target device to known hosts.
    If connection is accepted and SSH password of target device is provided for login.

    :param device: client device from which the SSH session is initaited
    :type device: object
    :param dest_device: target device to connect
    :type dest_device: string
    :param ip: target device ip address
    :type ip: string
    :param opts: SSH options if any, default to ""
    :type opts: String, Optional
    :param ssh_key: SSH key for authentication, defaults to "-oKexAlgorithms=+diffie-hellman-group1-sha1"
    :type ssh_key: String, Optional
    :raises Exception: Exception thrown on SSH connection fail
    """
    device.sendline("ssh %s@%s" % (dest_device.username, ip))
    try:
        idx = device.expect(['no matching key exchange method found'] +
                            ['(yes/no)'] + ['assword:'],
                            timeout=60)
        if idx == 0:
            device.expect(device.prompt)
            device.sendline("ssh %s %s@%s %s" %
                            (ssh_key, dest_device.username, ip, opts))
            idx = device.expect(['(yes/no)'] + ['assword:'], timeout=60)
            if idx == 0:
                idx = 1
        if idx == 1:
            device.sendline('yes')
            device.expect("assword:")
        device.sendline(dest_device.password)
        device.expect(dest_device.prompt)
        device.sendline("exit")
        device.expect(device.prompt, timeout=20)
    except Exception as e:
        print(e)
        raise Exception("Failed to connect SSH to :%s" % device.before)


def telnet_service_verify(device, dest_device, ip, opts=""):
    """Verify telent service connection

    :param device: client device from which the telent session is initaited
    :type device: object
    :param dest_device: target device to connect
    :type dest_device: string
    :param ip: target device ip address
    :type ip: string
    :param opts: telent options if any, default to ""
    :type opts: String, Optional
    :raises Exception: Exception thrown on telnet connection fail
    """
    device.sendline("telnet%s %s" % (opts, ip))
    try:
        device.expect(["Username:"] + ["login:"], timeout=60)
        device.sendline(dest_device.username)
        device.expect(["assword:"])
        device.sendline(dest_device.password)
        device.expect(dest_device.prompt, timeout=40)
        device.sendline("exit")
        device.expect(device.prompt, timeout=20)
    except Exception as e:
        print(e)
        raise Exception("Failed to connect telnet to :%s" % device.before)
