# -*- coding: utf-8 -*-
import unittest
import time
import sys
import os
import re
import tempfile

sys.path.insert(1,os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
from serial_wrapper.serial_android import SerialAndroid
from serial_wrapper.serial_android import Intent
from serial_wrapper.serial_android import AndroidFailureException
from serial_wrapper.serial_android import AndroidInvalidOutputException

SERIAL_PORT = 'COM4'
CODING = 'UTF-8'

PATH_APK = u'com.android.shell'
PATH_APK_PATH = u'/system/priv-app/Shell/Shell.apk'

class AndroidSYLoggerTest(unittest.TestCase):

    serial_log = os.path.join(tempfile.gettempdir(), 'serial.log')

    @classmethod
    def setUpClass(cls):
        cls.serial = SerialAndroid(SERIAL_PORT, coding=CODING, serial_config=None, console_monitor=True, logger=None)
        cls.monitor = cls.serial.create_serial_monitor()

    @classmethod
    def tearDownClass(cls):
        cls.serial.close_serial_monitor(cls.monitor)
        cls.serial.close()
        del cls.serial
        try:
            os.remove(cls.serial_log)
        except:
            pass

    def setUp(self):
        self.serial.write(u'\n')

    def tearDown(self):
        self.serial.write(chr(3))
        time.sleep(1)

    def test_su(self):
        self.serial.su_exit()
        self.assertFalse(self.serial.is_root())
        self.serial.su_exit()
        self.assertFalse(self.serial.is_root())
        self.serial.su_enter()
        self.assertTrue(self.serial.is_root())
        self.serial.su_enter()
        self.assertTrue(self.serial.is_root())
        self.serial.su_exit()
        self.assertFalse(self.serial.is_root())

    def test_pm(self):
        shell_path = self.serial.pm_path(PATH_APK)
        self.assertEqual(shell_path, PATH_APK_PATH)
        with self.assertRaises(AndroidInvalidOutputException):
            self.serial.pm_path(u'InvalidPackage')
        with self.assertRaises(AndroidFailureException):
            self.serial.pm_install(PATH_APK_PATH)
        pkgs = self.serial.pm_list_packages()
        self.assertIn(PATH_APK, pkgs)

    def test_logcat(self):
        self.serial.logcat(u'/data/local/tmp/logcat.log')
        time.sleep(2)
        self.serial.write(chr(3))

    def test_bugreport(self):
        res = self.serial.bugreport()
        self.assertIn(u'DUMPSYS' in res)

    def test_prop(self):
        sdk = self.serial.getprop_android_sdk_version()
        self.assertTrue(sdk.isdigit())

if __name__ == "__main__":
    unittest.main()
