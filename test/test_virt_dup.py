#!/usr/bin/env python3
#-*- coding: utf-8 -*-
'pytest'
import unittest
import sys
import os
import inspect
#import traceback
import contextlib
import importlib
from io import StringIO

# https://stackoverflow.com/questions/279237/import-a-module-from-a-relative-path
#
# cmd_folder = os.path.realpath(os.path.abspath(os.path.split(
#                               inspect.getfile(inspect.currentframe() ))[0]))
CMD_PATH = os.path.realpath(os.path.abspath(os.path.join(
    os.path.split(inspect.getfile(inspect.currentframe()))[0], "../")))
if CMD_PATH not in sys.path:
    sys.path.insert(0, CMD_PATH)

VIRTDUP = importlib.import_module("virt_dup")




#############################################
# temporarily replacing sys.stdout and sys.stderr
@contextlib.contextmanager
def capture_sys_output():
    'docstring'
    capture_out, capture_err = StringIO(), StringIO()
    current_out, current_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = capture_out, capture_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = current_out, current_err


class CliTestCase(unittest.TestCase):
    'docstring'
    @classmethod
    def setUpClass(cls):
        'docstring'
        cls.cli = VIRTDUP.cli_parser()

    def test_failure_usecase_empty_args(self):
        'docstring'
        with self.assertRaises(SystemExit) as cmgr:
            with capture_sys_output() as (_stdout, stderr):
                self.cli.parse_args([])
        txt = stderr.getvalue().strip()
        self.assertRegex(txt, 'usage:')
        self.assertRegex(txt, 'error:')
        self.assertEqual(cmgr.exception.code, 2)


    def test_failure_usecase_just_verbose_and_missing_vm_name(self):
        'docstring'
        with self.assertRaises(SystemExit) as cmgr:
            with capture_sys_output() as (_stdout, stderr):
                self.cli.parse_args(['-v'])
        txt = stderr.getvalue().strip()
        self.assertRegex(txt, 'usage:')
        self.assertRegex(txt, 'error:')
        self.assertEqual(cmgr.exception.code, 2)


    def test_usecase_help_args(self):
        'docstring'
        with self.assertRaises(SystemExit) as cmgr:
            with capture_sys_output() as (stdout, _stderr):
                self.cli.parse_args(['-h'])
        txt = stdout.getvalue().strip()
        self.assertRegex(txt, 'positional arguments:')
        self.assertRegex(txt, 'optional arguments:')
        self.assertRegex(txt, 'examples:')
        self.assertEqual(cmgr.exception.code, 0)

    def test_usecase_dup_vm(self):
        'docstring'
        with self.assertRaises(SystemExit) as cmgr:
            with capture_sys_output() as (stdout, _stderr):
                args = self.cli.parse_args(['ut-vm'])
                VIRTDUP.process_args(args)
        txt = stdout.getvalue().strip()
        self.assertRegex(txt, 'have fun:')
        self.assertRegex(txt, 'virsh start ut-vm_dup')
        self.assertEqual(cmgr.exception.code, 0)

    def test_usecase_dup_vm_with_verbose_info(self):
        'docstring'
        with self.assertRaises(SystemExit) as cmgr:
            with capture_sys_output() as (stdout, _stderr):
                args = self.cli.parse_args(['ut-vm', '-v'])
                VIRTDUP.process_args(args)
        txt = stdout.getvalue().strip()
        self.assertRegex(txt, 'DEBUG:')
        self.assertRegex(txt, 'have fun:')
        self.assertRegex(txt, 'virsh start ut-vm_dup')
        self.assertEqual(cmgr.exception.code, 0)

    def test_usecase_dup_vm_to_new(self):
        'docstring'
        with self.assertRaises(SystemExit) as cmgr:
            with capture_sys_output() as (stdout, _stderr):
                args = self.cli.parse_args(['ut-vm', 'ut-vm1'])
                VIRTDUP.process_args(args)
        txt = stdout.getvalue().strip()
        self.assertRegex(txt, 'have fun:')
        self.assertRegex(txt, 'virsh start ut-vm1')
        self.assertEqual(cmgr.exception.code, 0)

    def test_usecase_dup_vm_to_multiple(self):
        'docstring'
        with self.assertRaises(SystemExit) as cmgr:
            with capture_sys_output() as (stdout, _stderr):
                args = self.cli.parse_args(['ut-vm', 'ut-vm1', 'ut-vm2'])
                VIRTDUP.process_args(args)
        txt = stdout.getvalue().strip()
        self.assertRegex(txt, 'have fun:')
        self.assertRegex(txt, 'virsh start ut-vm1')
        self.assertRegex(txt, 'virsh start ut-vm2')
        self.assertEqual(cmgr.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
