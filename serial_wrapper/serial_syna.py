# -*- coding: utf-8 -*-
import re
import time

from .serial_wrapper import SerialTimeoutException
from .serial_android import SerialAndroid
from .serial_android import AndroidBaseException
from .serial_linux import DEFAULTCODING

# /proc/cpm/status regex pattern
CPM_PATTERNS = {
    u'MOD': re.compile(
        r'\d+\s+(?P<name>[A-Za-z]+)'
        r'\s+(?P<status>ON|OFF|-)\s*\(\s*(?P<on>\d+)/\s*(?P<total>\d+)\)'
        r'\s+(?P<startup>OFF|-)'
        r'\s*\n'
        ),
    u'CORE': re.compile(
        r'\d+\s+(?P<name>[A-Za-z]+)'
        r'\s+(?P<status>[A-Z])'
        r'\s+(?P<cfg>Y|N)'
        r'\s*\n'
        ),
    u'CLK SRC': re.compile(
        r'\d+\s+(?P<name>\w+)'
        r'\s+(?P<freq>\d+)MHz'
        r'\s*\n'
        ),
    u'CLK': re.compile(
        r'\d+\s+(?P<name>\w+)'
        r'\s+(?P<freq>\d+)MHz'
        r'\s+(?P<en>ON|OFF)'
        r'\s+(?P<ref>\d+)'
        r'\s*\n'
        ),
    u'PERIPHERAL': re.compile(
        r'\d+\s+(?P<name>\w+)'
        r'\s+(?P<en>ON|OFF)'
        r'\s*\n'
        ),
    u'OTHERS': re.compile(
        r'leakage:\s*(?P<leakage>\d+)mA'
        r'\s+temp:\s*(?P<temp>\d+)'
        r'\s+Vcore:\s*(?P<voltage>\d+)mV'
        r'\s+status:\s*(?P<status>H|M|L)'
        r'\s*\n'
        ),
}



class SynaBaseException(AndroidBaseException):
    pass

class SynaInvalidOutputException(SynaBaseException):
    pass

class SerialSyna(SerialAndroid):

    def __init__(self, serial_port, coding=DEFAULTCODING, serial_config=None, console_monitor=True, logger=None):
        super(SerialSyna, self).__init__(serial_port, coding, serial_config, console_monitor, logger)

    def serial_prepare(self, timeout=10):
        '''Prepare serial in root state for later work
        Function will detect OS first
            for Linux, it will try login first
            for android, call su_enter
        '''
        start_time = time.time()
        output_hd = self.create_logger()
        # twice enter to prevent linux serial into wrong account state
        self.write(chr(3))
        time.sleep(0.5)
        self.write(u'\n')
        time.sleep(0.1)
        self.write(u'\n')
        os = None
        while time.time() - start_time < timeout:
            if u'login:' in output_hd.readall():
                self.logger.info("DUT is Synaptics Linux")
                os = 'linux'
                break
            elif u' # ' in output_hd.readall():
                self.logger.info("DUT is Android root")
                os = 'android'
                return
            elif u' $ ' in output_hd.readall():
                self.logger.info("DUT is Android none-root")
                os = 'android'
                break
            elif u'# ' in output_hd.readall():
                self.logger.info("DUT is Synaptics Linux root")
                os = 'linux'
                return
        else:
            output = output_hd.readall()
            if output:
                self.logger.error("Timeout(%ss) to prepare serial, unknown response", timeout)
                self.logger.error("output: %r", )
            else:
                self.logger.error("Serial no response? DUT no power or serial config wrong?")
            raise SynaInvalidOutputException
        if os == 'linux':
            try:
                self.expect_for_write("root\n", "#", True, timeout=time.time()+timeout-start_time)
            except SerialTimeoutException:
                self.logger.error("DUT enter 'root', but not get console work")
                raise SynaInvalidOutputException
        elif os == 'android':
            self.su_enter()
        else:
            self.logger.error("Unknown DUT OS")
            raise SynaInvalidOutputException

    def test_disp(self, args, timeout=5):
        cmd = u'test_disp {}'.format(u' '.join(args))
        _, res = self.command_output(cmd, timeout=timeout)
        return res

    def test_disp_getvidfmt(self):
        '''Get HDMI Tx Color Format / Bit Depth
        Output: {
            'color': '444/422/420/rgb',
            'bitdepth': '8'/'10'/'12'
        }'''
        args = [u'getvidfmt']
        res = self.test_disp(args)
        vidfmt = {}
        if u'OUTPUT_COLOR_FMT_' not in res:
            self.logger.warning("Invalid Response: %r", res)
            raise SynaInvalidOutputException
        if u'OUTPUT_BIT_DEPTH_' not in res:
            self.logger.warning("Invalid Response: %r", res)
            raise SynaInvalidOutputException
        if u'OUTPUT_COLOR_FMT_YCBCR444' in res:
            vidfmt[u'color'] = u'444'
        elif u'OUTPUT_COLOR_FMT_YCBCR422' in res:
            vidfmt[u'color'] = u'422'
        elif u'OUTPUT_COLOR_FMT_YCBCR420' in res:
            vidfmt[u'color'] = u'420'
        elif u'OUTPUT_COLOR_FMT_RGB888' in res:
            vidfmt[u'color'] = u'rgb'
        else:
            self.logger.warning("Invalid Color Format: %r", res)
            raise SynaInvalidOutputException
        match = re.search(r'OUTPUT_BIT_DEPTH_(\d+)BIT', res)
        if not match:
            self.logger.warning("Invalid Bit Depth: %r", res)
        vidfmt[u'bitdepth'] = match.group(1)
        return vidfmt

    def test_disp_getres(self):
        '''Get HDMI Tx Resolution / FPS
        Output: {
            'resolution': '1920x1080',
            'is_progress' : True/False
            'fps': '60'/'59'
        }'''
        resolution_mapping = {
            u'525': u'720x480',
            u'625': u'720x576',
            u'720': u'1280x720',
            u'1080': u'1920x1080',
            u'4Kx2K': u'3840x2160',
        }
        fps_map = {
            u'60': u'60',
            u'5994': u'59',
            u'50': u'50',
            u'30': u'30',
            u'2997': u'29',
            u'25': u'25',
            u'24': u'24',
            u'2398': u'23',
        }
        res_dict = {}
        args = [u'getres']
        res = self.test_disp(args)
        match = re.search(r'##ResID: \d+,.*? RES_(\w+) *= *(\d+)', res)
        if not match:
            self.logger.warning("test_disp getres fail: %r", res)
        res = match.group(1)
        for res_key, res_value in resolution_mapping.items():
            if res_key in res:
                res_dict[u'resolution'] = res_value
                break
        else:
            self.logger.warning("Invalid Resolution Found: %r", res)
            raise SynaInvalidOutputException
        res_dict[u'is_progress'] = u'I' not in res
        for res_key, res_value in fps_map.items():
            if res_key in res:
                res_dict[u'fps'] = res_value
                break
        else:
            self.logger.warning("Invalid FPS Found: %r", res)
            raise SynaInvalidOutputException
        return res_dict

    def test_disp_hdcp_state(self):
        '''Get HDMI HDCP State
        Output: hdcp_state - True/False (boolean)
                hdcp_version - 1/2 (str)
                hdcp_states (str list)
        '''
        hdcp14_enable = u'HDCP_STATE_AUTH_DONE'
        hdcp2x_enable = u'HDCP2X_TX_AUTH_DONE'
        hdcp14_re = re.compile(r'HDCP 1.4 state = (\w+)')
        hdcp2xmain_re = re.compile(r'Main state = (\w+)')
        hdcp2xsub_re = re.compile(r'Sub state = (\w+)')
        hdcp2xauth_re = re.compile(r'Auth state = (\w+)')
        hdcpfail_re = re.compile(r'(HDCP is in un authenticated State)')
        hdcp_states = set()
        hdcp_state = False
        hdcp_version = u'0'
        args = [u'hdcp', u'state']
        res = self.test_disp(args)
        for pattern in (hdcp14_re, hdcp2xmain_re, hdcp2xsub_re, hdcp2xauth_re, hdcpfail_re):
            if not pattern.search(res):
                continue
            hdcp_states.add(pattern.search(res).group(1))
        if u'HDCP 2.2 state =' in res:
            hdcp_version = u'2'
            if hdcp2x_enable in hdcp_states:
                hdcp_state = True
        if u'HDCP 1.4 state =' in res:
            hdcp_version = u'1'
            if hdcp14_enable in hdcp_states:
                hdcp_state = True
        return hdcp_state, hdcp_version, hdcp_states

    def ampclient_alpha_31_get(self):
        '''Get HDMI/SPDIF Passthrough Mode from AOUT
        Output: {
            'HDMI': {'UserSet': 'RAW', 'WorkFmt': 'PCM_MULTI'},
            'SPDIF': {'UserSet': 'RAW', 'WorkFmt': 'PCM_STERO'},
        }
        '''
        cmd = u'ampclient_alpha 31 -g'
        _, res = self.command_output(cmd, timeout=5)
        path_re = re.compile(r'(?P<path>HDMI|SPDIF).*?UserSet\[ *(?P<UserSet>[^]]+)\].*?WorkFmt\[ *(?P<WorkFmt>[^]]+)\]')
        ret = {}
        for match in path_re.finditer(res):
            audio_path = match.groupdict().get(u'path')
            user_set = match.groupdict().get(u'UserSet')
            work_fmt = match.groupdict().get(u'WorkFmt')
            ret.update({audio_path: {u'UserSet': user_set, u'WorkFmt': work_fmt}})
        return ret

    def ampclient_alpha_15_fmt(self, port):
        '''Get HDMI/SPDIF Format by API AMP_SND_GetHDMIFormat/AMP_SND_GetSpdifFormat
        Input: port (str HDMI/SPDIF)
        Output: String (such as AMP_SND_HDMI_FORMAT_INVALID) / None (for API call fail)
        Detail return string refer:
            /synaptics-sdk/ampsdk/amp/inc/amp_sound_types.h
                AMP_SND_SPDIF_FORMAT
                AMP_SND_HDMI_FORMAT
        '''
        port2id = {
            'HDMI': '10',
            'SPDIF': '11',
        }
        if port not in port2id:
            self.logger.error('Invalid Port, only support %s', '/'.join(port2id.keys()))
            raise ValueError('Invalid Port')
        cmd = u'ampclient_alpha 15 -t ' + port2id[port]
        _, res = self.command_output(cmd, timeout=5)
        format_re = re.compile(r'Format: (.*?) \(\d+\)')
        match = format_re.search(res)
        if not match:
            return None
        return match.group(1)

    def cpm_status(self):
        '''Get cpm status by cat /proc/cpm/status
        Output: {
            Modules1: Data1s
            Modules2: Data2s
        }
        Modules will be MOD/CORE/CLK SRC/CLK/PERIPHERAL/OTHERS
            MOD/CORE/CLK SRC/CLK/PERIPHERAL's Data format as below
                {
                    name1: values1
                    name2: values2
                }
                values will be dict, key list as below
                    en/cfg/startup(bool)
                    freq/ref/on/total(int)
                    status(string)
            OTHERS's Data format as dict, key as below
                leakage/temp/voltage(int)
                status(string)
        '''
        def filter_data(ret):
            int_data_keys = (
                u'total',
                u'on',
                u'freq',
                u'ref',
                )
            bool_data_map = {
                u'startup': (u'-', u'OFF'), # First for True
                u'cfg': (u'Y', u'N'),
                u'en': (u'ON', u'OFF'),
            }
            others_int_keys = (
                u'leakage',
                u'temp',
                u'voltage',
            )
            for module, values in ret.items():
                if module == u'OTHERS':
                    for int_data in others_int_keys:
                        if int_data in values:
                            values[int_data] = int(values[int_data])
                    continue
                for value in values.values():
                    for int_data in int_data_keys:
                        if int_data in value:
                            value[int_data] = int(value[int_data])
                    for bool_data, check_list in bool_data_map.items():
                        if bool_data in value:
                            assert value[bool_data] in check_list
                            value[bool_data] = value[bool_data] == check_list[0]

        cmd = u'cat /proc/cpm/status'
        _, res = self.command_output(cmd, timeout=5)

        ret = {}
        for module, pattern in CPM_PATTERNS.items():
            values = {}
            for match in pattern.finditer(res):
                matches = match.groupdict()
                name = matches.pop(u'name', None)
                if name:
                    values.update({name: matches})
                else:
                    values.update(matches)
            if values:
                ret.update({module: values})
        filter_data(ret)
        return ret
