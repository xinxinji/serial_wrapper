# -*- coding: utf-8 -*-
import unittest
import time
import sys
import os
import re
import tempfile

sys.path.insert(1,os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
from serial_wrapper.serial_wrapper import SerialThread, SerialTimeoutException

def time_sleep(ttt):
    time.sleep(ttt)

class TimeSleepObj(object):
    def time_sleep(self, ttt):
        time.sleep(ttt)

SERIAL_PORT = 'COM4'
CODING = 'UTF-8'

class SerialLoggerTest(unittest.TestCase):

    serial_log = os.path.join(tempfile.gettempdir(), 'serial.log')

    def setUp(self):
        self.serial = SerialThread(SERIAL_PORT, coding=CODING, serial_config=None, console_monitor=True, logger=None)

    def tearDown(self):
        self.serial.close()
        del self.serial
        try:
            os.remove(self.serial_log)
        except:
            pass

    def test_createlogger(self):
        sw1 = self.serial.create_logger(self.serial_log)
        self.serial.write('id\n')
        time.sleep(1)
        self.serial.close_logger(sw1)
        with open(self.serial_log, 'rb') as serial_f:
            file_content = serial_f.read().decode('UTF-8')
            self.assertIn(u'groups', file_content)
            one_line = file_content.split(u'\n')[-2]
            self.assertTrue(re.match(r'\d{4}\-\d{2}\-\d{2} \d{2}\:\d{2}\:\d{2}\.\d{3} ', one_line))
        self.serial.write(chr(3))

    def test_createlogger_notimestamp(self):
        sw1 = self.serial.create_logger(self.serial_log, timestamp=False)
        self.serial.write('id\n')
        time.sleep(1)
        self.serial.close_logger(sw1)
        with open(self.serial_log, 'rb') as serial_f:
            file_content = serial_f.read().decode('UTF-8')
            self.assertIn(u'groups', file_content)
            one_line = file_content.split('\n')[-2]
            self.assertFalse(re.match(r'\d{4}\-\d{2}\-\d{2} \d{2}\:\d{2}\:\d{2}\.\d{3}', one_line))
        self.serial.write(chr(3))

    def test_monitor(self):
        swo = self.serial.create_serial_monitor()
        self.serial.write('logcat\n')
        res_manual = raw_input("Please input monitor show(Y/N):")
        self.assertIn(res_manual, ('Y', 'y'))
        self.serial.write(chr(3))
        self.serial.close_serial_monitor(swo)

class SerialRWTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.serial = SerialThread(SERIAL_PORT, coding=CODING, serial_config=None, console_monitor=True, logger=None)

    @classmethod
    def tearDownClass(cls):
        cls.serial.close()
        del cls.serial

    def test_wait_for_strings(self):
        self.serial.write('id\n')
        ret, reason, raw_str = self.serial.wait_for_strings([u'groups'], timeout=2)
        self.assertTrue(ret)
        self.assertEqual(reason, [u'groups'])
        self.assertIn(u'groups', raw_str)

    def test_wait_for_string_timeout(self):
        with self.assertRaises(SerialTimeoutException):
            self.serial.wait_for_string(u'NNNN!!!!', timeout=1)

    def test_wait_for_strings_all(self):
        self.serial.write('aabbcc\n')
        ret, key_list, _ = self.serial.wait_for_strings([u'not', u'found'], all_=True, timeout=2)
        self.assertTrue(ret)
        self.assertEqual(len(key_list), 2)
        self.assertIn(u'not', key_list)
        self.assertIn(u'found', key_list)

    def test_wait_for_strings_allfalse(self):
        self.serial.write('id\n')
        ret, key_list, _ = self.serial.wait_for_strings([u'NNNNNNN', u'groups'], all_=False, timeout=2)
        self.assertTrue(ret)
        self.assertEqual(len(key_list), 1)
        self.assertEqual(key_list[0], u'groups')

    def test_iob_fuc1(self):
        with self.assertRaises(SerialTimeoutException):
            self.serial.input_output_blocking((time.sleep, True, 1), (['abc'], True), 2, 1)

    def test_iob_fuc2(self):
        with self.assertRaises(SerialTimeoutException):
            self.serial.input_output_blocking((time_sleep, True, 1), (['abc'], True), 2, 1)

if __name__ == "__main__":
    unittest.main()
