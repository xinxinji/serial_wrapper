# -*- coding: utf-8 -*-
import re
from datetime import datetime
import string
import random

from .serial_wrapper import SerialThread
from .serial_wrapper import DEFAULTCODING
from .serial_wrapper import BaseSerialWrapperException
from .serial_wrapper import SerialTimeoutException

class LinuxBaseException(BaseSerialWrapperException):
    pass

class InvalidOutputException(LinuxBaseException):
    pass

class NotFoundException(LinuxBaseException):
    pass

class ExitNonZeroException(LinuxBaseException):
    pass

class NoSupportException(LinuxBaseException):
    pass

class SerialLinux(SerialThread):

    exitecho = u'echo "ExitCode:$?."'
    file_property_re = re.compile(r'([-lspbcdrwx]{10}) *(\S*) *(\S*) *(\d{0,10}) *(\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{1,2}) *(.*)')
    file_property_nose_re = re.compile((r'(?P<permission>[-lspbcdrwx\.]{10}) *'
                                        r'(?P<linknum>\d*) *'
                                        r'(?P<group>\S*) *(?P<owner>\S*) *'
                                        r'(?P<filesize>\d{0,10}) *'
                                        r'(?P<datetime>\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{1,2}) *'
                                        r'(?P<filename>.*)'))
    exitcode_re = re.compile(r'ExitCode:(\d+)\.')
    ifconfig_re = re.compile((r'(?P<interfacename>[\w\-]+)\s*Link encap:(?P<linkencap>\w+)\s*'
                              r'(?:Loopback|\s*?HWaddr (?P<mac>[0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}))\s*'
                              r'(?:Driver (?P<driver>\w+)\s*)?'
                              r'(?:inet addr:(?P<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*)?'
                              r'(?:Bcast:(?P<bcast>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*)?'
                              r'(?:Mask:(?P<mask>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}) *)?'))

    def __init__(self, serial_port, coding=DEFAULTCODING, serial_config=None, console_monitor=True, logger=None):
        super(SerialLinux, self).__init__(serial_port, coding, serial_config, console_monitor, logger)

    def exitcode_expect_for_write(self, cmd, repeat=False, repeat_gap=1, timeout=None):
        '''Try get run command exit with unified id to avoid conflict with out command
        Mainly call expect_for_write, but will add echo exitcode cmd / and target exitcode return
        '''
        def exitecho_cmd(uid):
            return u'echo "({})ExitCode:$?."'.format(uid)
        def exitecho_re(uid):
            return re.compile(r'\({}\)ExitCode:(\d+)\.'.format(uid))
        uid = u''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(8))
        ret, res_l, raw_data = self.expect_for_write(
            u'{cmd};{echo_cmd}\n'.format(cmd=cmd, echo_cmd=exitecho_cmd(uid)),
            exitecho_re(uid), repeat=repeat, repeat_gap=repeat_gap, timeout=timeout)
        exit_code = exitecho_re(uid).findall(res_l[0])[0]
        ext_str_pos = raw_data.find('({})ExitCode:{}'.format(uid, exit_code))
        self.logger.debug("Exit Code Position: %d", ext_str_pos)
        raw_data = raw_data[:ext_str_pos]
        return ret, exit_code, raw_data

    def command_output(self, cmd, timeout=None):
        '''Try input some command and get output and exitcode of it'''
        cmd_ = u'echo \'[!Start!]\';{}'.format(cmd)
        _, exit_code, raw_data = self.exitcode_expect_for_write(cmd_, timeout=timeout)
        raw_data = raw_data[raw_data.rfind('[!Start!]')+9:].strip()
        return exit_code, raw_data

    def is_root(self):
        '''
        Check whether target is root or not
        '''
        self.write(chr(26))
        self.write('\n')
        id_re = re.compile(r'uid=(\d+)\(([^)]+)\)')
        try:
            ret, res_l, _ = self.expect_for_write(u'id\n', id_re, repeat=True, timeout=3)
        except SerialTimeoutException:
            self.logger.warning("Checking id No response")
            raise InvalidOutputException
        else:
            if ret:
                pair = id_re.search(res_l[0])
                id_id = pair.group(1)
                id_name = pair.group(2)
                self.logger.info("Current User: uid=%s(%s)", id_id, id_name)
                if id_id == u'0' and id_name == u'root':
                    return True
                else:
                    return False
            else:
                raise InvalidOutputException

    def remount(self, target, options=u'rw'):
        cmd = u'mount -o {0},remount {1}'.format(options, target)
        try:
            ret, exitcode, raw_data = self.exitcode_expect_for_write(cmd, timeout=5)
        except SerialTimeoutException:
            self.logger.warning("remount No response")
            raise InvalidOutputException
        else:
            if not ret:
                raise InvalidOutputException
        if exitcode == u'0':
            return
        self.logger.error("remount exit with %s. Raw Data: %r", exitcode, raw_data)
        raise ExitNonZeroException

    def remount_system(self):
        self.remount(u'/system', u'rw')

    def reboot(self):
        self.write(u'reboot\n')

    def files_property(self, folderpath, timeformat='%Y-%m-%d %H:%M'):
        cmd = u'ls -al "{}"'.format(folderpath)
        try:
            ret, _, raw_data = self.exitcode_expect_for_write(cmd, timeout=5)
        except SerialTimeoutException:
            self.logger.warning("ls No response")
            raise InvalidOutputException
        else:
            if not ret:
                if u'No such file or directory' in raw_data:
                    raise NotFoundException
                self.logger.info("Files Property: %r", raw_data)
                raise InvalidOutputException
        property_iter = self.file_property_nose_re.finditer(raw_data)
        files = {}
        for match in property_iter:
            ret = match.groupdict()
            filename = ret.get(u'filename').rstrip(u'\r\n')
            if ' -> ' in filename:
                filename, linkfile = filename.split(' -> ', 1)
            else:
                linkfile = None
            properties = {
                'permission': ret.get(u'permission'),
                'owner': ret.get(u'owner'),
                'group': ret.get(u'group'),
                'size': ret.get(u'filesize'),
                'datetime': datetime.strptime(ret.get(u'datetime'), timeformat),
                'linknum': ret.get(u'linknum'),
                'filename': filename,
                'linkfile': linkfile,
            }
            files.update({filename: properties})
        return files

    def file_property(self, filepath, timeformat='%Y-%m-%d %H:%M'):
        cmd = u'ls -al "{}"\n'.format(filepath)
        try:
            ret, _, raw_data = self.expect_for_write(cmd, self.file_property_nose_re, timeout=5)
        except SerialTimeoutException:
            self.logger.warning("ls No response")
            raise InvalidOutputException
        else:
            if not ret:
                if u'No such file or directory' in raw_data:
                    raise NotFoundException
                self.logger.info("File Property: %r", raw_data)
                raise InvalidOutputException
        property_list = self.file_property_nose_re.findall(raw_data)
        if len(property_list) > 1:
            raise NoSupportException

        property_group = self.file_property_nose_re.search(raw_data)
        ret = property_group.groupdict()

        permission = ret.get(u'permission')
        linknum = ret.get(u'linknum')
        group = ret.get(u'group')
        owner = ret.get(u'owner')
        filesize = ret.get(u'filesize')
        modifytime = ret.get(u'datetime')
        filename = ret.get(u'filename')

        modifytime = datetime.strptime(modifytime, timeformat)
        if ' -> ' in filename:
            filename, linkfile = filename.split(' -> ', 1)
        else:
            linkfile = None
        return {'permission': permission, 'owner': owner, 'group': group,
                'size': filesize, 'datetime': modifytime, 'linknum': linknum,
                'filename': filename, 'linkfile': linkfile,}

    def file_exist(self, filepath):
        if self.file_property(filepath):
            return True
        else:
            return False

    def file_remove(self, filepath, timeout=60):
        cmd = u'rm -rf "{0}"'.format(filepath)
        try:
            ret, exitcode, raw_data = self.exitcode_expect_for_write(cmd, timeout=timeout)
        except SerialTimeoutException:
            self.logger.warning("rm No response")
            raise InvalidOutputException
        else:
            if not ret:
                raise InvalidOutputException
        if exitcode == u'0':
            return
        self.logger.error("rm -rf exit with %s. Raw Data: %r", exitcode, raw_data)
        raise ExitNonZeroException

    def file_find(self, filename):
        pass

    def file_chmod(self, filename):
        pass

    def file_link(self, target, filename, params=None):
        pass

    def file_alias(self, cmd, target):
        pass

    def folder_create(self, folderpath):
        pass

    def busybox_exist(self):
        pass

    def interface_list_get(self):
        cmd = u'ifconfig'
        try:
            ret, _, raw_data = self.exitcode_expect_for_write(cmd, timeout=5)
        except SerialTimeoutException:
            self.logger.warning("ifconfig No response")
            raise InvalidOutputException
        else:
            if not ret:
                raise InvalidOutputException
        interfaces_list = []
        if not self.ifconfig_re.search(raw_data):
            self.logger.warning("Fail to find any network interface")
            self.logger.warning("raw_data: %r", raw_data)
        else:
            for interface in self.ifconfig_re.finditer(raw_data):
                interfaces_list.append({
                    u'interface': interface.group(u'interfacename'),
                    u'mac': interface.group(u'mac'),
                    u'driver': interface.group(u'driver'),
                    u'ip': interface.group(u'ip'),
                    u'bcast': interface.group(u'bcast'),
                    u'mask': interface.group(u'mask'),
                })
                self.logger.info("Find: %5s|%17s|%s",
                    interface.group(u'interfacename'), interface.group(u'mac'), interface.group(u'ip'))
        return interfaces_list

    def interface_mapping(self, source, target, source_content):
        assert source in (u'ip', 'interface', 'mac'), u"Invalid source, should be ip/interface/mac"
        assert target in (u'ip', 'interface', 'mac'), u"Invalid target, should be ip/interface/mac"
        interface_list = self.interface_list_get()
        for interface_dict in interface_list:
            if interface_dict[source] == source_content:
                target_content = interface_dict[target]
                self.logger.info("interface_mapping: Get %s - %s", target, target_content)
                return target_content
        self.logger.info("interface_mapping: Fail to find %s according %s", target, source)
        return False

    def interface_according_ip_get(self, ip):
        return self.interface_mapping(u'ip', u'interface', ip)

    def interface_according_mac_get(self, mac):
        return self.interface_mapping(u'mac', u'interface', mac)

    def ip_according_interface_get(self, interface):
        return self.interface_mapping(u'interface', u'ip', interface)

    def ip_according_mac_get(self, mac):
        return self.interface_mapping(u'mac', u'ip', mac)

    def mac_according_interface_get(self, interface):
        return self.interface_mapping(u'interface', u'mac', interface)

    def mac_according_ip_get(self, ip):
        return self.interface_mapping(u'ip', u'mac', ip)

    def get_process_list(self):
        pass

    def selinux_get(self):
        string_map = {
            u'Enforcing': True,
            u'Permissive': False,
            u'Disabled': False,
        }
        exit_code, res = self.command_output(u'getenforce', timeout=5)
        if exit_code != u'0':
            raise InvalidOutputException
        if res.strip() in string_map:
            return string_map[res.strip()]
        else:
            raise InvalidOutputException

    def selinux_set(self, to_disable=True):
        value = u'0' if to_disable else u'1'
        exit_code, res = self.command_output(u'setenforce ' + value, timeout=5)
        if exit_code != u'0':
            self.logger.warning("Set SELinux to %s Failed: %s", value, res.strip())
            raise InvalidOutputException

    def md5sum(self, filepath, timeout=5):
        exit_code, res = self.command_output(u'md5sum ' + filepath, timeout=timeout)
        if exit_code != u'0':
            self.logger.warning("Cal md5 of %s Failed: %s", filepath, res.strip())
            raise InvalidOutputException
        md5dict = {}
        for md5, filename in re.findall(r'(\w{32}) +(.*)', res):
            md5dict[filename] = md5
        return md5dict

    def meminfo(self):
        exit_code, res = self.command_output(u'cat /proc/meminfo', timeout=5)
        if exit_code != u'0':
            self.logger.warning("Fail to get meminfo: %s", res.strip())
            raise InvalidOutputException
        ret = {}
        for match in re.finditer(r'(?P<key>[A-Za-z\(\)\_]+):\s*(?P<value>\d+)\s*(?P<unit>kB)?', res):
            ret[match.groupdict()['key']] = int(match.groupdict()['value'])
        return ret
