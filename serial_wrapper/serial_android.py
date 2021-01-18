# -*- coding: utf-8 -*-
import re
import shlex
import time
from xml.etree import ElementTree as ET

from .serial_wrapper import SerialTimeoutException
from .serial_linux import SerialLinux
from .serial_linux import DEFAULTCODING
from .serial_linux import LinuxBaseException
from .serial_linux import InvalidOutputException
from .serial_linux import NotFoundException

class AndroidBaseException(LinuxBaseException):
    pass

class AndroidNotFoundException(AndroidBaseException, NotFoundException):
    pass

class AndroidInvalidOutputException(AndroidBaseException, InvalidOutputException):
    pass

class AndroidErrorException(AndroidBaseException):
    def __init__(self, msg):
        self.msg = msg

class AndroidFailureException(AndroidBaseException):
    def __init__(self, msg):
        self.msg = msg

class Intent(object):
    def __new__(cls, main=None, *args, **kwargs):
        '''
        Define INTENT paramters
        main is URI or PACKAGE or COMPONENT
        *args for long paramters such as grant-read-uri-permission/...
        **kwargs for short paramters such as a/c/e/esn/ez/...
        '''
        cmdlist = []
        for key in args:
            cmdlist.append(u'--{}'.format(key))
        for key, value in kwargs.items():
            if key == u'f':
                cmdlist.append(u'--f')
            elif len(key) == 1:
                cmdlist.append(u'-{}'.format(key))
            else:
                cmdlist.append(u'--{}'.format(key))
            if isinstance(value, list):
                cmdlist.extend(value)
            else:
                cmdlist.append(value)
        if main:
            cmdlist.append(main)
        return u' '.join(cmdlist)

class SerialAndroid(SerialLinux):

    pm_failure_re = re.compile(r'Failure \[(.*?)\]')
    pm_setting_re = re.compile(r'(Package|Component) [\w\.]*? new state: (disabled|enabled)')
    error_re = re.compile(r'Error: (.*)')
    warn_re = re.compile(r'Warning: (.*)')

    def __init__(self, serial_port, coding=DEFAULTCODING, serial_config=None, console_monitor=True, logger=None):
        super(SerialAndroid, self).__init__(serial_port, coding, serial_config, console_monitor, logger)

    def su_enter(self):
        '''
        Enter root mode, use su
        Note: Only verify Android Linux
        '''
        try:
            if self.is_root():
                return
        except InvalidOutputException:
            self.logger.warning("Get Root Status Fail")
            time.sleep(1)
        try:
            _, res_l, _ = self.expects_for_write(u'su\n', [u'root', u'su: not found', u' # '], timeout=5)
        except SerialTimeoutException:
            raise AndroidInvalidOutputException
        if res_l[0] in (u'root', u' # '):
            self.logger.info("Enter su")
            return
        if res_l[0] == u'su: not found':
            self.logger.error("There is no su in PATH")
            raise AndroidNotFoundException

    def su_exit(self):
        '''
        Exit root mode, use exit
        Note: Only verify Android Linux
        '''
        if not self.is_root():
            return
        try:
            ret, _, _ = self.expects_for_write(u'exit\n', [u'shell', u' $ '])
        except SerialTimeoutException:
            self.logger.warning("exit no response")
            raise AndroidInvalidOutputException
        else:
            if not ret:
                raise AndroidInvalidOutputException
        return

    def wait_boot_complete(self, timeout=60):
        start = time.time()
        while time.time() - start <= timeout:
            try:
                if self.getprop('dev.bootcomplete') == '1':
                    self.logger.info("Android Boot Complete")
                    return
            except AndroidInvalidOutputException:
                time.sleep(0.5)
        self.logger.warning("Android Boot up timeout")
        raise AndroidInvalidOutputException

    def _apm_common(self, cmd, name, main, timeout=10):
        try:
            ret, exit_code, raw_data = self.exitcode_expect_for_write(cmd, timeout=timeout)
        except SerialTimeoutException:
            self.logger.warning("am/pm no response")
            raise AndroidInvalidOutputException
        else:
            if ret:
                if u'Success' in raw_data:
                    self.logger.info("%s %s success", main, name)
                    return raw_data
                if self.pm_setting_re.search(raw_data):
                    # For enable/disable
                    self.logger.info("%s %s success", main, name)
                    return raw_data
                if u'Warning: ' in raw_data:
                    reason = self.warn_re.search(raw_data).group(1)
                    self.logger.error("%s %s warning: %s", main, name, reason)
                if u'Error: ' in raw_data:
                    reason = self.error_re.search(raw_data).group(1)
                    self.logger.error("%s %s error: %s", main, name, reason)
                    raise AndroidErrorException(reason)
                if u'Failure [' in raw_data:
                    reason = self.pm_failure_re.search(raw_data).group(1)
                    self.logger.error("%s %s failure: %s", main, name, reason)
                    raise AndroidFailureException(reason)
                if u'Failed' in raw_data:
                    self.logger.error("%s %s failed", main, name)
                    raise AndroidErrorException(u'Failed')
                if exit_code == u'0':
                    self.logger.info("No error/failure found, treat it as success")
                    return raw_data
        self.logger.critical("%s %s unknown status", main, name)
        self.logger.error("%s %s: %r", main, name, raw_data)
        raise AndroidInvalidOutputException

    def pm_path(self, package):
        '''
        Input: package [Application package name](str)
        Output: path
        '''
        cmd = u'pm path {0}'.format(package)
        raw_data = self._apm_common(cmd, u'path', u'pm')
        package_path = re.findall(r'package:([\S]+)', raw_data)
        if package_path:
            package_path = package_path[0]
            self.logger.info("path: %s", package_path)
            return package_path
        else:
            self.logger.error("pm path execute pass, but fail to get result")
            self.logger.error("pm path raw_data: %r", raw_data)
            raise AndroidInvalidOutputException

    def pm_install(self, apkfile, forward=False, replace=False, test=False,
                   sdcard=False, downgrade=False, permission=False):
        '''
        Do pm install
        Input: apkfile [apk file path](str)
               forward: [-l: forward lock application](bool)
               replace [-r: replace existing application](bool)
               test [-t: allow test packages](bool)
               sdcard [-s: install application on sdcard](bool)
               downgrade [-d: allow version code downgrade](bool)
               permission [-g: grant all runtime permissions](bool)
               timeout (int/float)
               device [SN(for USB device) / IP:Port(for network device)](str) / None(for self._device)]
        Output: None
        Note: Some Android System need press OK for verify application
              Sugguest close this option in Android System first before use pm install
              (put global package_verifier_include_adb 0)
              Or you need ignore this function return and wait timeout
        '''
        cmdlist = [u'pm', u'install']
        if forward: cmdlist.append(u'-l')
        if replace: cmdlist.append(u'-r')
        if test: cmdlist.append(u'-t')
        if sdcard: cmdlist.append(u'-s')
        if downgrade: cmdlist.append(u'-d')
        if permission: cmdlist.append(u'-g')
        cmdlist.append(apkfile)
        cmd = u' '.join(cmdlist)
        self._apm_common(cmd, u'install', u'pm')

    def pm_uninstall(self, package, keepdata=False):
        '''
        Do pm uninstall
        Input: package [Application package name](str)
               keepdata: [-k: keep data and cache](bool)
        Output: None
        '''
        cmdlist = [u'pm', u'uninstall']
        if keepdata:
            cmdlist.append('-k')
        cmdlist.append(package)
        cmd = u' '.join(cmdlist)
        self._apm_common(cmd, u'uninstall', u'pm')

    def pm_list_packages(self):
        '''
        Do pm list packages
        Input: None
        Output: set(packages)
        Note: will transform command to cmd package list packages (# TODO)
        '''
        cmd = u'pm list packages'
        raw_data = self._apm_common(cmd, u'list packages', u'pm')
        return set(re.findall(r'package:([\w\.]*)', raw_data))

    def pm_clear(self, package):
        '''
        Do pm clear
        Input: package [Application package name](str)
        Output: None
        '''
        cmdlist = [u'pm', u'clear', package]
        cmd = u' '.join(cmdlist)
        self._apm_common(cmd, u'clear', u'pm')

    def pm_enable(self, package):
        '''
        Do pm enable
        Input: package [Application package name](str)
        Output: None
        '''
        cmdlist = [u'pm', u'enable', package]
        cmd = u' '.join(cmdlist)
        self._apm_common(cmd, u'enable', u'pm')

    def pm_disable(self, package):
        '''
        Do pm disable
        Input: package [Application package name](str)
        Output: None
        '''
        cmdlist = [u'pm', u'disable', package]
        cmd = u' '.join(cmdlist)
        self._apm_common(cmd, u'disable', u'pm')

    def am_start(self, intent, **options):
        '''
        Do am start
        Input: intent (Intent)
               D [enable debugging](bool)
               N [enable native debugging](bool)
               W [wait for launch to complete](bool)
               start_profile [start profileer and send results to file](str)
               sampling [use sample profiling with INTERVAL microseconds](int)
               P [like sampling, but profiling stops when app goes idle](str)
               R [repeat the activity launch times](int)
               S [force stop the target app before starting the activity](bool)
               track_allocation [enable tracking of object allocations](bool)
               user [Specify which user to run as](str)
               stack [Specify into which stack should the activity be put](str)
        '''
        cmdlist = [u'am', u'start']
        if options.get(u'D'): cmdlist.append(u'-D')
        if options.get(u'N'): cmdlist.append(u'-N')
        if options.get(u'W'): cmdlist.append(u'-W')
        if options.get(u'start_profile'): cmdlist.extend([u'--start-profiler', options.get(u'start_profile')])
        if options.get(u'sampling'): cmdlist.extend([u'--sampling', options.get(u'sampling')])
        if options.get(u'P'): cmdlist.extend([u'-P', str(options.get(u'P'))])
        if options.get(u'R'): cmdlist.extend([u'-R', str(options.get(u'R'))])
        if options.get(u'S'): cmdlist.append(u'-S')
        if options.get(u'track_allocation'): cmdlist.append(u'--track-allocation')
        if options.get(u'user'): cmdlist.extend([u'--user', str(options.get(u'user'))])
        if options.get(u'stack'): cmdlist.extend([u'--stack', str(options.get(u'stack'))])
        cmdlist.append(intent)
        cmd = u' '.join(cmdlist)
        self._apm_common(cmd, u'start', u'am')

    def am_force_stop(self, package):
        '''
        Do am forse-stop
        Input: package [Application package name](str)
        Output: None
        '''
        cmd = u'am force-stop {}'.format(package)
        self._apm_common(cmd, u'force-stop', u'am')

    def am_kill(self, package):
        '''
        Do am kill
        Input: package [Application package name](str)
        Output: None
        '''
        cmd = u'am kill {}'.format(package)
        self._apm_common(cmd, u'kill', u'am')

    def am_kill_all(self):
        '''
        Do am kill
        Input: None
        Output: None
        '''
        cmd = u'am kill-all'
        self._apm_common(cmd, u'kill-all', u'am')

    def am_broadcast(self, intent, **options):
        '''
        Do am start
        Input: intent (Intent)
        Output: None
        '''
        cmdlist = [u'am', u'broadcast']
        if options.get(u'user'): cmdlist.extend([u'--user', str(options.get(u'user'))])
        cmdlist.append(intent)
        cmd = u' '.join(cmdlist)
        self._apm_common(cmd, u'broadcast', u'am')

    def am_instrument(self, component, **options):
        '''
        Do am instrument
        Input: component (str)
               r [print raw results (otherwise decode REPORT_KEY_STREAMRESULT)](bool)
               e [<NAME> <VALUE>: set argument <NAME> to <VALUE>.
                  ((name1, value1),(name2, value2, value3))](set)
               p [write profiling data to] (str)
               w [wait for instrumentation to finish before returning] (bool)
               user [Specify user instrumentation runs in] (str)
               no_window_animation [turn off window animations while running.] (bool)
               abi [Launch the instrumented process with the selected ABI.] (str)
        Output: None
        '''
        cmdlist = [u'am', u'instrument']
        if options.get(u'r'): cmdlist.append(u'-r')
        if options.get(u'e'):
            for one_set in options.get(u'e'):
                cmdlist.append(u'-e')
                cmdlist.extend(one_set)
        if options.get(u'p'): cmdlist.extend([u'-p', str(options.get(u'p'))])
        if options.get(u'w'): cmdlist.append(u'-w')
        if options.get(u'user'): cmdlist.extend([u'--user', str(options.get(u'user'))])
        if options.get(u'no_window_animation'): cmdlist.append(u'--no-window-animation')
        if options.get(u'abi'): cmdlist.extend([u'--abi', str(options.get(u'abi'))])
        cmdlist.append(component)
        cmd = u' '.join((u'"{}"'.format(c) if u' ' in c else c for c in cmdlist)) # Handle space in command
        raw_data = self._apm_common(cmd, u'instrument', u'am')
        # TODO: Analyze report
        if u'FAILURES!!' in raw_data:
            return {u'ret': False}
        elif re.compile(r'OK +\(\d+ +test\)').search(raw_data):
            return {u'ret': True}
        self.logger.warning("Invalid am instrument result: %r", raw_data)
        raise AndroidInvalidOutputException

    def logcat(self, filename=None, params=None, bg=False):
        '''
        Do logcat
        Input: filename [If filename define, will output to file. Or output to serial directly](str)
               params [logcat's params, see logcat --help, but don't use -f](str)
               bg [Run logcat at background](bool)
        Output: None
        '''
        cmdlist = [u'logcat']
        if params: cmdlist.extend(shlex.split(params))
        if filename: cmdlist.extend([u'-f', filename])
        if bg: cmdlist.append('&')
        cmdlist.append(u'\n')
        cmd = u' '.join(cmdlist)
        self.write(cmd)

    def bugreport(self, filename=None, timeout=180):
        '''
        Do bugreport
        Input: filename [If filename define, will output to file. Or output to serial directly](str)
        Output: return console output if no filename define
        '''
        cmdlist = [u'bugreport']
        if filename: cmdlist.extend([u'>', filename])
        cmd = u' '.join(cmdlist)
        try:
            ret, _, raw_data = self.exitcode_expect_for_write(cmd, timeout=timeout)
        except SerialTimeoutException:
            self.logger.warning("bugreport no response")
            raise AndroidInvalidOutputException
        else:
            if ret:
                if filename:
                    return raw_data
        self.logger.critical("bugreport unknown status")
        self.logger.error("bugreport: %r", raw_data)
        raise AndroidInvalidOutputException

    def getprops(self):
        '''
        Do getprop
        Output: return props dict or raise AndroidInvalidOutputException
        '''
        prop_re = re.compile(r'\[([^]]+)\]: \[([^]]+)\]')
        cmd = u'getprop'
        try:
            ret, exit_code, raw_data = self.exitcode_expect_for_write(cmd, repeat=True, repeat_gap=3, timeout=10)
        except SerialTimeoutException:
            self.logger.warning("getprop no response")
            raise AndroidInvalidOutputException
        else:
            if ret:
                if exit_code == u'0':
                    prop_p = prop_re.findall(raw_data)
                    if prop_p:
                        return dict({v[0]: v[1] for v in prop_p})
                    else:
                        self.logger.error("getprop: fail to find any prop")
                        self.logger.error("getprop: %r", raw_data)
                else:
                    self.logger.error("getprop: fail to find getprop")
            else:
                self.logger.critical("getprop unknown status")
                self.logger.error("getprop: %r", raw_data)
        raise AndroidInvalidOutputException

    def setprop(self, key, value):
        '''
        Do setprop
        Input: key [prop item](str)
               value [prop value](str)
        Note: Please handle str escape in serial by yourself
        '''
        cmdlist = [u'setprop', key, value, u'\n']
        cmd = u' '.join(cmdlist)
        self.write(cmd)

    def getprop(self, item):
        '''
        Do getprop
        Input: item [item in props](str)
        Output: return item value if found or raise AndroidInvalidOutputException
        '''
        cmd = u'echo "#[$(getprop {})]#"'.format(item)
        try:
            ret, exit_code, raw_data = self.exitcode_expect_for_write(cmd, repeat=True, repeat_gap=1, timeout=10)
        except SerialTimeoutException:
            self.logger.warning("getprop no response")
            raise AndroidInvalidOutputException
        else:
            if ret:
                if exit_code == u'0':
                    prop_p = re.findall(r'#\[([^]]*)\]#', raw_data)
                    if prop_p and prop_p[-1]:
                        return prop_p[-1]
                    else:
                        self.logger.error("getprop: fail to find %s by regex", item)
                        self.logger.error("getprop: %r", raw_data)
                else:
                    self.logger.error("getprop: fail to find %s by grep", item)
            else:
                self.logger.critical("getprop unknown status")
                self.logger.error("getprop: %r", raw_data)
        finally:
            self.write(chr(3))
        raise AndroidInvalidOutputException

    def getprop_android_sdk_version(self):
        return self.getprop('ro.build.version.sdk')

    def getprop_buildincremental(self):
        return self.getprop('ro.build.version.incremental')

    def get_wakelocks(self):
        '''Get system wake lock status'''
        wakelock_re = re.compile(r'Wakelock Status:##([\w\.]+)##')
        cmd = (u'for wakelock in $(cat /sys/power/wake_lock); do '
               u'    echo "Wakelock Status:##${wakelock}##"; '
               u'done; '
               u'unset wakelock ')
        try:
            _, _, raw_data = self.exitcode_expect_for_write(cmd, timeout=10)
        except SerialTimeoutException:
            self.logger.warning("cat wake_lock no response")
            raise AndroidInvalidOutputException
        wakelocks = wakelock_re.findall(raw_data)
        return wakelocks

    def dumpsys(self, service=None):
        def dumpsys_power(dumpsys_power_str):
            def key_value_handler(strings):
                def value_conv(value):
                    if value in (u'true', u'false'):
                        return value == u'true'
                    if value.isdigit():
                        return int(value)
                    if value.startswith(u'0x'):
                        return int(value, 16)
                    if value == u'(none)':
                        return '0'
                    try:
                        return float(value)
                    except ValueError:
                        pass
                    if value in (u'NaN', u'null', u'nan'):
                        return None
                    return value
                def is_list(value):
                    return value.startswith(u'[') and value.endswith(u']')
                def value_clean(value):
                    if is_list(value):
                        # So far, only digital only list
                        res = []
                        for val in value[1:-2].split(u','):
                            res.append(value_conv(val.strip()))
                        return res
                    if u' (' in value and value.endswith(')'):
                        # Ignore data in ()
                        return value_conv(value[:value.find(u' (')].strip())
                    return value_conv(value)
                settings = {}
                for line in strings.split(u'\n'):
                    if u'=' not in line:
                        continue
                    key, value = line.split(u'=', 1)
                    settings.update({key.strip(): value_clean(value.strip())})
                return settings
            def looper_state_handler(strings):
                res = {}
                message_re = re.compile(
                    r'when=(?P<when>[\+\-\w]+) what=(?P<what>\d+) target=(?P<target>[\w\.\$]+) '
                )
                messages = []
                for message_match in message_re.finditer(strings):
                    messages.append(message_match.groupdict())
                res.update({u'messages': messages})
                if u'pulling=' in strings:
                    res.update({u'pulling': u'pulling=true' in strings})
                if u'quitting=' in strings:
                    res.update({u'quitting': u'quitting=true' in strings})
                return res
            def wake_lock_handler(strings):
                wl_re = re.compile((r'(?P<wake_lock_level>[A-Z_\?]+) *'
                                    r'\'(?P<tag>[^\']+)\' *'
                                    r'(?P<lockflag_acq>ACQUIRE_CAUSES_WAKEUP)? *'
                                    r'(?P<lockflag_rel>ON_AFTER_RELEASE)? *'
                                    r'(?P<disable>DISABLED)? *'
                                    r'(?:ACQ=(?P<acq>[\+\-\w]+))? *'
                                    r'(?P<long>LONG)? *'
                                    r'\(uid=(?P<uid>\d+) *'
                                    r'(?:pid=(?P<pid>\d+))? *'
                                    r'(?:ws=(?P<ws>[^\)]+))? *'))
                wake_locks = []
                for match in wl_re.finditer(strings):
                    wake_lock = {}
                    match_dict = match.groupdict()
                    wake_lock[u'wake_lock_level'] = match_dict.get(u'wake_lock_level')
                    additional_flag = []
                    if match_dict.get(u'lockflag_acq'):
                        additional_flag.append(u'ACQUIRE_CAUSES_WAKEUP')
                    if match_dict.get(u'lockflag_rel'):
                        additional_flag.append(u'ON_AFTER_RELEASE')
                    wake_lock[u'flags'] = additional_flag
                    wake_lock[u'is_disabled'] = True if match_dict.get(u'disable') else False
                    wake_lock[u'acq'] = match_dict.get(u'acq')
                    wake_lock[u'is_long'] = True if match_dict.get(u'long') else False
                    wake_lock[u'uid'] = match_dict.get(u'uid')
                    wake_lock[u'pid'] = match_dict.get(u'pid', '0')
                    if match_dict.get(u'ws'):
                        ws_str_list = match_dict.get(u'ws')[11:-1].split(',')
                        ws_list = []
                        for ws in ws_str_list:
                            uid = None
                            name = None
                            if u' ' in ws.strip():
                                uid, name = ws.strip().split(u' ')
                            else:
                                uid = ws.strip()
                            ws_list.append({'uid': uid, 'name': name})
                        wake_lock[u'ws'] = ws_list
                    else:
                        wake_lock[u'ws'] = None
                    wake_lock[u'tag'] = match_dict.get(u'tag')
                    if 'wake:' in wake_lock[u'tag']:
                        wake_lock[u'tag_type'] = u'wake'
                    if '*job*' in wake_lock[u'tag']:
                        wake_lock[u'tag_type'] = u'job'
                    package_match = re.search(r'[\/\:]([\w\.\_]*)/', wake_lock[u'tag'])
                    if package_match:
                        wake_lock[u'package_name'] = package_match.group(1)
                        service_name = wake_lock[u'tag'][wake_lock[u'tag'].rfind('/')+1:]
                        if service_name.startswith('.'):
                            wake_lock[u'service_name'] = wake_lock[u'package_name'] + service_name
                        else:
                            wake_lock[u'service_name'] = service_name
                    wake_locks.append(wake_lock)
                return wake_locks
            def suspend_blocker_handler(strings):
                sb_re = re.compile(r' *([\w\.]*): ref count=(\d+)')
                suspend_blockers = {}
                for match in sb_re.finditer(strings):
                    key = match.group(1)
                    value = int(match.group(2))
                    suspend_blockers[key] = value
                return suspend_blockers
            def display_power_handler(strings):
                res = {}
                dp_re = re.compile(r'state=(\d+|UNKNOWN|OFF|ON|DOZE|DOZE_SUSPEND|VR)')
                if dp_re.search(strings):
                    res = {u'state':dp_re.search(strings).group(1)}
                return res
            analyze_part = {
                u'Power Manager State:': key_value_handler, # -> value_clean
                u'Settings and Configuration:': key_value_handler,# -> value_clean
                u'Looper state:': looper_state_handler,
                u'Wake Locks:': wake_lock_handler,
                u'Suspend Blockers:': suspend_blocker_handler,
                u'Display Power:': display_power_handler,
                # TODO: add rest
            }
            final_res = {}
            for head_keyword, handler in analyze_part.items():
                find_index = dumpsys_power_str.find(head_keyword)
                if find_index == -1:
                    continue
                find_end_1 = dumpsys_power_str.find(u'\n\r\n', find_index)
                find_end_2 = dumpsys_power_str.find(u'\n\n', find_index)
                if find_end_1 == -1 and find_end_2 == -1:
                    find_end = -1
                elif find_end_1 != -1 and find_end_2 == -1:
                    find_end = find_end_1
                elif find_end_1 == -1 and find_end_2 != -1:
                    find_end = find_end_2
                else:
                    find_end = min(find_end_1, find_end_2)
                if find_end == -1:
                    component_str = dumpsys_power_str[find_index:]
                else:
                    component_str = dumpsys_power_str[find_index:find_end+1]
                final_res[head_keyword.replace(u':', u'')] = handler(component_str)
            return final_res
        if service:
            cmd = u'dumpsys {}'.format(service)
        else:
            cmd = u'dumpsys'
        try:
            _, _, raw_data = self.exitcode_expect_for_write(cmd, timeout=60)
        except SerialTimeoutException:
            self.logger.warning("cat dumpsys no response")
            raise AndroidInvalidOutputException
        service_map = {
            'power': dumpsys_power
        }
        if service in service_map:
            return service_map[service](raw_data)
        return raw_data

    def input(self, source, args):
        '''Run Android input Command'''
        cmd = u'input {} {}'.format(source, ' '.join(args))
        self.logger.debug("Input Cmd: %s", cmd)
        try:
            _, res = self.command_output(cmd, timeout=5)
        except SerialTimeoutException as err:
            self.logger.warning("Input Command Timeout: %s", err)
            raise AndroidInvalidOutputException
        if u'Error:' in res.lower():
            self.logger.warning("Input Command Error: %s", res)
            raise AndroidInvalidOutputException

    def input_keyevent(self, keycode, is_long_press=False):
        '''Run Android input keyevent Command
        Input: keycode (str) see https://developer.android.com/reference/android/view/KeyEvent#constants_1
                       can be int or string (string without KEYCODE_)
        '''
        args = [str(keycode)]
        if is_long_press:
            args.append(u'--longpress')
        self.input(u'keyevent', args)

    def input_text(self, text):
        self.input(u'text', [u'"{}"'.format(text.replace(u'"', u'\\"'))])

    def input_tap(self, x, y):
        self.input(u'tap', [str(x), str(y)])

    def input_swipe(self, x1, y1, x2, y2, duration=None):
        args = [str(x1), str(y1), str(x2), str(y2)]
        if duration:
            args.append(duration)
        self.input(u'swipe', args)

    def input_draganddrop(self, x1, y1, x2, y2, duration=None):
        args = [str(x1), str(y1), str(x2), str(y2)]
        if duration:
            args.append(duration)
        self.input(u'draganddrop', args)

    def uiautomator_dump(self, filepath=u'/sdcard/window_dump.xml', timeout=30):
        '''Use uiautomator dump function
        Input: filepath (default /sdcard/window_dump.xml)
        Output: dump xml string'''
        cmd = u'uiautomator dump "{}"'.format(filepath)
        _, res = self.command_output(cmd, timeout=timeout)
        if u'ERROR:' in res:
            self.logger.warning("UIAutomator Dump Error: %s", res.strip())
            raise AndroidInvalidOutputException
        if u'UI hierchary dumped to' not in res:
            self.logger.warning("UIAutomator Dump Failed: %s", res.strip())
            raise AndroidInvalidOutputException
        cmd = u'cat "{}"'.format(filepath)
        res = u''
        for _ in range(3):
            exit_code, res = self.command_output(cmd, timeout=timeout)
            if exit_code != u'0':
                self.logger.warning("Cat uiautomator dump file %s Failed: %s", filepath, res.strip())
                raise AndroidInvalidOutputException
            try:
                ET.fromstring(res)
            except ET.ParseError:
                self.logger.warning("Element Parser Fail, maybe console disturb")
                continue
            else:
                self.logger.debug("Get UI Objects XML String Success")
                return res
        else:
            self.logger.warning("Console always get invalid dump content: %r", res)
        raise AndroidInvalidOutputException

    def findui_after_action(self, attrib_type, content, equal_or_contain, action, max_action_num=20):
        '''Iter check UI after action
        Input: attrib_type (str, see key of fuction elem2dict)
               content (str, used to match attrib type from UI)
               equal_or_contain (bool, True for content must equal, False for content can be included)
               action (function, such as partial(func, args))
               max_action_num (int, max action execute times)
        Output: elements (list, single item in list is a dict, see fuction elem2dict)
        '''
        def elem2dict(elem):
            return {
                u'index': int(elem.attrib.get(u'index')),
                u'text': elem.attrib.get(u'text'),
                u'resource-id': elem.attrib.get(u'resource-id'),
                u'class': elem.attrib.get(u'class'),
                u'package': elem.attrib.get(u'package'),
                u'content-desc': elem.attrib.get(u'content-desc'),
                u'bounds': re.findall(r'\d+', elem.attrib.get(u'bounds')),
                u'checkable': elem.attrib.get(u'checkable') == u'true',
                u'checked': elem.attrib.get(u'checked') == u'true',
                u'clickable': elem.attrib.get(u'clickable') == u'true',
                u'enabled': elem.attrib.get(u'enabled') == u'true',
                u'focusable': elem.attrib.get(u'focusable') == u'true',
                u'focused': elem.attrib.get(u'focused') == u'true',
                u'scrollable': elem.attrib.get(u'scrollable') == u'true',
                u'long-clickable': elem.attrib.get(u'long-clickable') == u'true',
                u'password': elem.attrib.get(u'password') == u'true',
                u'selected': elem.attrib.get(u'selected') == u'true',
            }
        content_ = u'{}'.format(content)
        self.logger.debug("Target attrib: %s", attrib_type)
        self.logger.debug("Target content: %s", content_)
        self.logger.debug("Target equal_or_contain: %s", equal_or_contain)
        self.logger.debug("Target content: %r", action)
        self.logger.debug("Target max_action_num: %s", max_action_num)
        filepath = u'/sdcard/window_dump.xml'
        last_uiautomator_xml = None
        elements = []
        action_num = 0
        dump_fail_num = 0
        dump_fail_max = 5
        dump_same_num = 0
        dump_same_max = max_action_num if max_action_num else 5
        while True:
            try:
                uiautomator_xml = self.uiautomator_dump(filepath)
            except AndroidInvalidOutputException:
                dump_fail_num += 1
                if dump_fail_num >= dump_fail_max:
                    self.logger.warning("UI Always Fail to dump")
                    raise AndroidInvalidOutputException
                continue
            if uiautomator_xml == last_uiautomator_xml:
                self.logger.warning("UI Object Same as last round")
                dump_same_num += 1
                if dump_same_num >= dump_same_max:
                    self.logger.warning("UI Always Keep Same")
                    raise AndroidInvalidOutputException
                continue
            dump_same_num = 0
            last_uiautomator_xml = uiautomator_xml
            et = ET.fromstring(last_uiautomator_xml)
            try:
                for elem in et.iter(tag=u'node'):
                    if equal_or_contain and elem.attrib[attrib_type] == content_:
                        elements.append(elem2dict(elem))
                    elif content_ in elem.attrib[attrib_type]:
                        elements.append(elem2dict(elem))
            except KeyError:
                self.logger.warning("Invalid Android UIAutomator Dump")
                self.logger.warning("Dump Content: %r", last_uiautomator_xml)
                raise AndroidInvalidOutputException
            if elements:
                return elements
            self.logger.debug("Fail to find target UI")
            if max_action_num and action_num >= max_action_num:
                self.logger.warning("Get Max Action Num")
                raise AndroidInvalidOutputException
            action()
            action_num += 1

# TODO: cmd escape
