# Copyright (c) 2019
#
# All rights reserved.
#
# This file is distributed under the Clear BSD license.
# The full text can be found in LICENSE in the root directory.

import json
import os
import re

import boardfarm
import pexpect
import six
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiStarParser
from pysmi.reader import FileReader, HttpReader
from pysmi.searcher import StubSearcher
from pysmi.writer import CallbackWriter
from pysnmp.hlapi import ObjectIdentifier

from .installers import install_pysnmp
from .regexlib import AllValidIpv6AddressesRegex, ValidIpv4AddressRegex


def find_directory_in_tree(pattern, root_dir):
    """
    Looks for all the directories where the name matches pattern
    Avoids paths patterns already in found, i.e.:
    root/dir/pattern (considered)
    root/dir/pattern/dir1/pattern (not considered since already in the path)

    Parameters:
    pattern:  name to match against
    root_dir: root of tree to traverse

    Returns a list of dirs
    """
    dirs_list = []
    for root, dirs, files in os.walk(root_dir):
        for name in dirs:
            if 'mib' in name or 'mibs' in name:
                d = os.path.join(root, name)
                if any(s in d for s in dirs_list):
                    continue
                else:
                    dirs_list.append(d)
    return dirs_list


def find_files_in_tree(root_dir, no_ext=True, no_dup=True, ignore=[]):
    """
    Looks for all the files in a directry tree

    Parameters:
    root_dir: root of tree to traverse, can be a list of directory

    Returns a list of files
    """

    if (type(root_dir) is not list) and len(root_dir):
        root_dir = [root_dir]

    file_list = []

    if len(root_dir):
        for d in root_dir:
            for root, dirs, files in os.walk(d):
                for f in files:
                    if any(map(lambda x: x in f, ignore)):
                        continue
                    if no_ext:
                        f = os.path.splitext(f)[0]
                    file_list.append(f)
        if no_dup:
            file_list = list(dict.fromkeys(file_list))
    return file_list


class SnmpMibsMeta(type):
    @property
    def default_mibs(self):
        return SnmpMibs.get_mib_parser()


class SnmpMibs(six.with_metaclass(SnmpMibsMeta, object)):
    """
    Look up specific ASN.1 MIBs at configured Web and FTP sites,
    compile them into JSON documents and print them out to stdout.
    Try to support both SMIv1 and SMIv2 flavors of SMI as well as
    popular deviations from official syntax found in the wild.
    Source:
    http://snmplabs.com/pysmi/examples/download-and-compile-smistar-mibs-into-json.html

    DEBUG:
        BFT_DEBUG=y     shows which mib module is being parsed
        BFT_DEBUG=yy    VERY verbose, shows the compiled dictionary and
                        mibs/oid details
    """
    dbg = None
    mib_dict = {}

    # this is to map unknown pysmi datatypes to ASN.1 datatypes
    mib_type_map = {"OctetString": ["DisplayString"]}

    snmp_parser = None

    @classmethod
    def get_mib_parser(cls,
                       snmp_mib_files=None,
                       snmp_mib_dirs=None,
                       http_sources=None):

        if cls.snmp_parser is not None:
            return cls.snmp_parser

        if snmp_mib_files is None:
            snmp_mib_files = []

        if snmp_mib_dirs is None:
            snmp_mib_dirs = ['/usr/share/snmp/mibs']

        # looks for the boardfarm directory path
        thisfiledir = os.path.realpath(__file__)
        boardfarmdir = thisfiledir[:thisfiledir.rfind('boardfarm')]

        # add the boardfarm dir as it is not in the overlays
        snmp_mib_dirs.extend(find_directory_in_tree('mibs', boardfarmdir))

        for modname in sorted(boardfarm.plugins):
            # finds all dirs with the word mibs in it
            # avoid adding a directory that is already
            # contained in the directory tree
            location = os.path.dirname(boardfarm.plugins[modname].__file__)
            snmp_mib_dirs.extend(find_directory_in_tree('mib', location))

        if 'BFT_DEBUG' in os.environ:
            print('Mibs directory list: %s' % snmp_mib_dirs)

        # if the mibs file are given, we do not want to add other mibs, as it may
        # results in unresolved ASN.1 imports
        if len(snmp_mib_files) == 0:
            # only traverses the mib dirs and compile all the files
            # /usr/share/snmp/mibs has miblist.txt which MUST be ignored
            snmp_mib_files = find_files_in_tree(
                snmp_mib_dirs, ignore=['miblist.txt', '__', '.py'])
        if 'BFT_DEBUG' in os.environ:
            print('Mibs file list: %s' % snmp_mib_files)

        # creates the snmp parser object
        cls.snmp_parser = cls(snmp_mib_files, snmp_mib_dirs)
        return cls.snmp_parser

    def __init__(self, mib_list, src_dir_list, http_sources=None):
        self.dbg = os.environ.get('BFT_DEBUG', '')

        if "yy" in self.dbg:
            # VERY verbose, but essential for spotting
            # possible  ASN.1 errors
            from pysmi import debug
            debug.setLogger(debug.Debug('reader', 'compiler'))

        # Initialize compiler infrastructure
        mibCompiler = MibCompiler(SmiStarParser(), JsonCodeGen(),
                                  CallbackWriter(self.callback_func))

        # search for source MIBs here
        mibCompiler.addSources(*[FileReader(x) for x in src_dir_list])

        if http_sources:
            # search for source MIBs at Web sites
            mibCompiler.addSources(*[HttpReader(*x) for x in http_sources])

        # never recompile MIBs with MACROs
        mibCompiler.addSearchers(StubSearcher(*JsonCodeGen.baseMibs))

        # run recursive MIB compilation
        mib_dict = mibCompiler.compile(*mib_list)

        err = False

        if mib_dict is None or mib_dict == {}:
            print(
                "ERROR: failed on mib compilation (mibCompiler.compile returned an empty dictionary)"
            )
            err = True

        for key, value in mib_dict.items():
            if value == 'unprocessed':
                print("ERROR: failed on mib compilation: " + key + ": " +
                      value)
                err = True

        if err:
            raise Exception("SnmpMibs failed to initialize.")
        elif 'BFT_DEBUG' in os.environ:
            print('# %d MIB modules compiled' % len(mib_dict))

    def callback_func(self, mibName, jsonDoc, cbCtx):
        if "y" in self.dbg:
            print('# MIB module %s' % mibName)

        for k, v in json.loads(jsonDoc).items():
            if "oid" in v:
                if "objects" in v or "revisions" in v:
                    # we want to skip objects that have no use
                    continue
                # add it to my dict
                if "yy" in self.dbg:
                    print("adding %s:{%s}" % (k, v))
                self.mib_dict[k] = v
        if "yy" in self.dbg:
            print(json.dumps(self.mib_dict, indent=4))

    def get_dict_mib(self):
        return self.mib_dict

    def get_mib_oid(self, mib_name):
        """
        Given a mib name, return the Object Identifier (OID).
        """
        oid = None
        try:
            oid = self.mib_dict[mib_name]['oid']
        except KeyError:
            raise Exception("ERROR: mib '%s' not found in mib_dict." %
                            mib_name)
        return oid


def snmp_v2(device,
            ip,
            mib_name,
            index=0,
            value=None,
            timeout=10,
            retries=3,
            community="private",
            walk_cmd=None,
            stype=None):
    """
    Performs an snmp get/set on ip from device's console.
    If value is provided, action = snmpget else action = snmpset

    Parameters:
        (bft_pexpect_helper.spawn) device : device used to perform snmp
        (str) ip : ip address used to perform snmp
        (str) mib_name : mib name used to perform snmp
        (int) index : index used along with mib_name
        (str) walk_cmd : If walk_cmd is passed(eg: head -15) the walk output will be returned
                         If walk_cmd is "walk_verify" it will verify walk is done and return True or False
        (str) stype: If datatype is passed pysnmp script for get method to get datatype is skipped

    Returns:
        (str) result : snmp result
    """

    if not getattr(device, "pysnmp_installed", False):
        install_pysnmp(device)
        setattr(device, "pysnmp_installed", True)

    try:
        ObjectIdentifier(mib_name)
        oid = mib_name
    except Exception:
        oid = get_mib_oid(mib_name)

    def _run_snmp(py_set=False):
        action = "getCmd"
        set_value = ""
        if py_set:
            action = "setCmd"
            if str(value).lower().startswith("0x"):
                set_value = ', %s(hexValue="%s")' % (stype, value[2:])
            else:
                set_value = ', %s("%s")' % (stype, value)
        pysnmp_cmd = 'cmd = %s(SnmpEngine(), CommunityData("%s"), UdpTransportTarget(("%s", 161), timeout=%s, retries=%s), ContextData(), ObjectType(ObjectIdentity("%s.%s")%s))' % \
                (action, community, ip, timeout, retries, oid, index, set_value)

        py_steps = [
            'from pysnmp.hlapi import *', pysnmp_cmd,
            'errorIndication, errorStatus, errorIndex, varBinds = next(cmd)',
            'print(errorIndication == None)',
            'if errorIndication: result=errorIndication; print(result)',
            'else: result=varBinds[0][1]; print(result.prettyPrint())',
            'print(result.__class__.__name__)'
        ]

        device.sendline("cat > snmp.py << EOF\n%s\nEOF" % "\n".join(py_steps))
        for e in py_steps:
            device.expect_exact(e[-40:])
        device.expect_exact('EOF')
        device.expect_prompt()
        device.sendline("python snmp.py")
        device.expect_exact("python snmp.py")
        tout = (timeout * retries) + 15
        device.expect_prompt(timeout=tout)
        if "Traceback" in device.before:
            data = False, "Python file error :\n%s" % device.before.split(
                "\n")[-1].strip(), None
        else:
            result = [
                i.strip() for i in device.before.split('\n') if i.strip() != ""
            ]
            data = result[0] == "True", "\n".join(result[1:-1]), result[-1]
        device.sendline("rm snmp.py")
        device.expect_prompt()
        return data

    if walk_cmd:
        return snmp_asyncore_walk(device, ip, oid, read_cmd=walk_cmd)

    if not stype:
        status, result, stype = _run_snmp()
        assert status, "SNMP GET Error:\nMIB:%s\nError:%s" % (mib_name, result)

        for k, v in SnmpMibs.mib_type_map.items():
            if stype in v:
                stype = k
                break

    if value != None:  # some operations require zero as a value
        status, result, stype = _run_snmp(True)
        assert status, "SNMP SET Error:\nMIB:%s\nError:%s" % (mib_name, result)

    return result


def get_mib_oid(mib_name):
    """
    Returns the oid for the given mib name.
    Uses the singleton of the SnmpHelper.SnmpMibs class, and instantiate one if none were
    previously created.
    Note: if the singleton is instatiated via this function the overlays are automatically
    scanned for mib files inside ".../mibs/" directories.

    Parameters:
    mib_name    a string (e.g. "sysObjectID", "docsDevSwAdminStatus")
    Returns:
    string      the oid (e.g. "1.3.6.1.2.1.69.1.4.5")
    """
    obj = SnmpMibs.default_mibs
    return obj.get_mib_oid(mib_name)


##############################################################################################

if __name__ == '__main__':

    import sys

    class SnmpMibsUnitTest(object):
        """
        Unit test for the SnmpMibs class to be run as a standalone module
        DEBUG:
            BFT_DEBUG=y     shows the compiled dictionary
            BFT_DEBUG=yy    VERY verbose, shows the compiled dictionary and
                            mibs/oid details
        """
        test_singleton = False  # if True it will invoke get_mib_parser() static method

        mibs = [
            'docsDevSwAdminStatus', 'snmpEngineMaxMessageSize',
            'docsDevServerDhcp', 'ifCounterDiscontinuityTime',
            'docsBpi2CmtsMulticastObjects', 'docsDevNmAccessIp'
        ]

        mib_files = ['DOCS-CABLE-DEVICE-MIB', 'DOCS-IETF-BPI2-MIB'
                     ]  # this is the list of mib/txt files to be compiled
        srcDirectories = [
            '/usr/share/snmp/mibs'
        ]  # this needs to point to the mibs directory location
        snmp_obj = None  # will hold an instance of the  SnmpMibs class

        def __init__(self,
                     mibs_location=None,
                     files=None,
                     mibs=None,
                     err_mibs=None):
            """
            Takes:
                mibs_location:  where the .mib files are located (can be a list of dirs)
                files:          the name of the .mib/.txt files (without the extension)
                mibs:           e.g. sysDescr, sysObjectID, etc
                err_mibs:       wrong mibs (just for testing that the compiler rejects invalid mibs)
            """

            # where the .mib files are located
            if mibs_location:
                self.srcDirectories = mibs_location

            if type(self.srcDirectories) != list:
                self.srcDirectories = [self.srcDirectories]

            for d in self.srcDirectories:
                if not os.path.exists(str(d)):
                    msg = 'No mibs directory {} found test_SnmpHelper.'.format(
                        str(d))
                    raise Exception(msg)

            if files:
                self.mib_files = files

            if SnmpMibsUnitTest.test_singleton:
                self.snmp_obj = SnmpMibs.get_mib_parser(
                    self.mib_files, self.srcDirectories)
                print("Using class singleton: %r" % self.snmp_obj)
            else:
                self.snmp_obj = SnmpMibs(self.mib_files, self.srcDirectories)
                print("Using object instance: %r" % self.snmp_obj)

            if mibs:
                self.mibs = mibs

            if type(self.mibs) != list:
                self.mibs = [self.mibs]

        def unitTest(self):
            """
            Compiles the ASN1 and gets the oid of the given mibs
            Asserts on failure
            """

            if 'y' in self.snmp_obj.dbg:
                print(self.snmp_obj.mib_dict)
                for k in self.snmp_obj.mib_dict:
                    print(k, ":", self.snmp_obj.mib_dict[k])

            print("Testing get mib oid")

            for i in self.mibs:
                oid = self.snmp_obj.get_mib_oid(i)
                print('mib: %s - oid=%s' % (i, oid))

            return True

    # this section can be used to test the classes above
    # (maybe by redirecting the output to a file)
    # BUT for this to run as a standalone file, it needs an
    # absolute import (see the file import section)

    location = None

    if '-h' in sys.argv or '--help' in sys.argv or len(sys.argv) < 2:
        print("Usage:\n%s <path_to_mibs>  [<path_to_mibs> ...]" % sys.argv[0])
        print(
            "\nE.g.: python %s  ../boardfarm-docsis/mibs /usr/share/snmp/mibs "
            % sys.argv[0])
        sys.exit(1)

    print('sys.argv=' + str(sys.argv))
    location = sys.argv[1:]

    SnmpMibsUnitTest.test_singleton = False
    unit_test = SnmpMibsUnitTest(mibs_location=location)
    assert (unit_test.unitTest())

    SnmpMibsUnitTest.test_singleton = True
    unit_test = SnmpMibsUnitTest(mibs_location=location)
    assert (unit_test.unitTest())

    print('Done.')


def snmp_asyncore_walk(device,
                       ip_address,
                       mib_oid,
                       community='public',
                       time_out=200,
                       read_cmd='walk_verify'):
    """Function to do a snmp walk using asyncore script
    Python's asyncore provides an event loop that can handle transactions from multiple non-blocking sockets
    Usage: snmp_asyncore_walk(wan, cm_ipv6, "1.3", private, 150)

    :param device: device where SNMP command shall be executed
    :type device: Object
    :param ip_address: Management ip of the DUT
    :type ip_address: String
    :param mib_oid: Snmp mib to walk
    :type mib_oid: String
    :param community: SNMP Community string that allows access to DUT, defaults to 'public'
    :type community: String, optional
    :param time_out: time out for every snmp walk request, default to 200 seconds
    :type time_out: Integer, Optional
    :param read_cmd: linux command to raed the snmp output(Eg: head -10 snmp_output.txt)
                     defaults to 'walk_verify'
    :type read_cmd: string, Optional
    :return: True or False or snmp output
    :rtype: Boolean or string
    """
    if re.search(ValidIpv4AddressRegex, ip_address):
        mode = 'ipv4'
    elif re.search(AllValidIpv6AddressesRegex, ip_address):
        mode = 'ipv6'
    install_pysnmp(device)
    asyncore_script = 'asyncore_snmp.py'
    fname = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                         'scripts/' + asyncore_script)
    dest = asyncore_script
    device.copy_file_to_server(fname, dest)
    device.sendline(
        'time python %s %s %s %s %s %s > snmp_output.txt' %
        (asyncore_script, ip_address, mib_oid, community, time_out, mode))
    device.expect(device.prompt, timeout=time_out)
    device.sendline('rm %s' % asyncore_script)
    device.expect(device.prompt)
    device.sendline('ls -l snmp_output.txt --block-size=kB')
    device.expect([r'.*\s+(\d+)kB'])
    file_size = device.match.group(1)
    device.expect(device.prompt)
    if file_size == '0':
        return False
    if read_cmd == 'walk_verify':
        device.sendline('tail snmp_output.txt')
        if 0 == device.expect(
            ["No more variables left in this MIB View", pexpect.TIMEOUT]):
            device.expect_prompt()
            output = True
        else:
            output = False
    else:
        output = device.check_output('{} snmp_output.txt'.format(read_cmd),
                                     timeout=60)
    device.sendline('rm snmp_output.txt')
    device.expect_prompt()
    return output
