#!/usr/bin/python

# python2 and python3 compatible is expected

import unittest
import sys
import os
import inspect
import traceback

# https://stackoverflow.com/questions/279237/import-a-module-from-a-relative-path
#
#cmd_folder = os.path.realpath(os.path.abspath(os.path.split(inspect.getfile(inspect.currentframe() ))[0]))
cmd_folder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile(inspect.currentframe() ))[0],"../")))
if cmd_folder not in sys.path:
    sys.path.insert(0, cmd_folder)

import importlib
virtdup = importlib.import_module("virt-dup")



#############################################
# Py2/3 compatible tricks

import contextlib
try:
    # Python 2
    from cStringIO import StringIO
except ImportError:
    # Python 3
    from io import StringIO

if sys.version_info < (3, 2):
    setattr(unittest.TestCase, "assertRegex",
        unittest.TestCase.assertRegexpMatches)



#############################################
# temporarily replacing sys.stdout and sys.stderr
@contextlib.contextmanager
def capture_sys_output():
    capture_out, capture_err = StringIO(), StringIO()
    current_out, current_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = capture_out, capture_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = current_out, current_err


class CliTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli= virtdup.cli_parser()

    # failure scenarios
    def test_usecase_empty_args(self):
        with self.assertRaises(SystemExit) as cm:
            with capture_sys_output() as (stdout, stderr):
                self.cli.parse_args([])
        self.assertEqual(cm.exception.code, 2)

    def test_usecase_just_verbose_and_missing_vm_name(self):
        with self.assertRaises(SystemExit) as cm:
            with capture_sys_output() as (stdout, stderr):
                self.cli.parse_args(['-v'])
        self.assertEqual(cm.exception.code, 2)
        # 
        # https://docs.python.org/2/library/unittest.html#assert-methods
        # https://docs.python.org/3/library/unittest.html#assert-methods
        # https://www.debuggex.com/cheatsheet/regex/python 
        #       Note: . Any character except newline
        # Python2: matching any character including newlines
        #       [\s\S], [\w\W], or [\d\D]
        #
        str=stderr.getvalue().strip()
        self.assertRegex(str, 'usage:')
        self.assertRegex(str, 'error:')

    # user stories
    def test_usecase_help_args(self):
        with self.assertRaises(SystemExit) as cm:
            with capture_sys_output() as (stdout, stderr):
                self.cli.parse_args(['-h'])
        self.assertEqual(cm.exception.code, 0)
        str=stdout.getvalue().strip()
        self.assertRegex(str, 'positional arguments:')
        self.assertRegex(str, 'optional arguments:')
        self.assertRegex(str, 'examples:')
        
    def test_usecase_dup_vm(self):
        with self.assertRaises(SystemExit) as cm:
            with capture_sys_output() as (stdout, stderr):
                self.cli.parse_args(['vm'])
        self.assertEqual(cm.exception.code, 0)
        str=stdout.getvalue().strip()
        self.assertRegex(str, 'have fun:')

    def test_usecase_dup_vm_to_new(self):
        with self.assertRaises(SystemExit) as cm:
            with capture_sys_output() as (stdout, stderr):
                self.cli.parse_args(['vm', 'vm1'])
        self.assertEqual(cm.exception.code, 0)
        str=stdout.getvalue().strip()
        self.assertRegex(str, 'have fun:')

    def test_usecase_dup_vm_with_verbose_info(self):
        with self.assertRaises(SystemExit) as cm:
            with capture_sys_output() as (stdout, stderr):
                self.cli.parse_args(['-v', 'vm1'])
        self.assertEqual(cm.exception.code, 0)
        str=stdout.getvalue().strip()
        self.assertRegex(str, 'have fun:')


if __name__ == '__main__':
    unittest.main()



