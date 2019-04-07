#!/usr/bin/python
#-*- coding: utf-8 -*-

import argparse
import os
import sys


DESCRIPTION = """\
  Motivation of this tool is to duplicate Virtual Machines in seconds. To
  reach that speed, the trick is to deploy all VM images in the filesystem with
  the native COW(--reflink) capability, eg. btrfs, xfs-4.16, ocfs2, etc.

  It is created, just because virt-clone does not yet leverage the
  native COW(--reflink) capability of the filesystem to duplicate qcow2.
  It only support RAW by now at the end of 2018. virt-clone might take
  noticeable time to duplicate qcow2 image files. Well, it is
  understandable virt-clone wants to keep the advantage of qcow2 backing
  file functionality for existent use cases.

  This tool will
  - reset hostname as the same name as the Virtual Machine
  - reset MAC to be unique
  - reset static IP to dhcp, if no '--change-ip' provided
  - calibrate the host record in /etc/hosts with VM_NAME and if with --set-ip

  Tips:
  - to let a image shared among Virtual Machines, you should
    avoid the Virtual Machine name to be the substring of the image name.

"""

EPILOG = """\
examples:
  virt-dup -h

  virt-dup VM_NAME
  It implies `virt-dup VM_NAME VM_NAME_dup`.
  Basically, it appends "_dup" as the name of the new virtual machine.

  virt-dup xx yy
  "yy" must not the substring of "xx".

  virt-dup xx yy1 yy2 yy3
  virt-dup xx yy{1..3}
  This will create three Virtual Machines, namely, yy1 yy2 yy3.

  virt-dup --set-ip 192.168.151.101 xx yy{1..16}
  It creates 16 virtual machines, which has its own unique ip from 101 to 116.

  Use the following example with care!

  virt-dup xx --change-ip xx:yy,192.168.150:192.168.151,IpSubStr1:IpSubStr2
  It applies: sed -i 's/\(IPADDR.*\)$xx/\1$yy/g' /etc/sysconfig/network/ifcfg*
 
"""

def cli_parser():
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description=DESCRIPTION, epilog=EPILOG)
    ap.add_argument('vm_name', metavar='VM_NAME', 
                    help='The original VM must exist in `virsh list --all`',
                    nargs='+')
    ap.add_argument('-v','--verbose', '-d', '--debug',
                    action='store_true')
    ap.add_argument('--set-ip', dest='set_ip',
                    metavar='IPADDR', nargs=1,
                    help="Add IPADDR to the first NIC" )
    ap.add_argument('--change-ip', dest='change_ip',
                    metavar='from:to[,from:to,...]', nargs=1,
                    help="leverage the substring of IP is handy. Use it well!" )
    return ap

def ensure_cli_env_is_root():
    if os.getuid() != 0:
        print ("ERR: please run as a root user. Refer to -h | --help")
        sys.exit()

def main():

    args = cli_parser().parse_args()

    ensure_cli_env_is_root()

    global VERBOSE
    VERBOSE = args.verbose

    global ORG_VM
    ORG_VM = args.VM_NAME
    print ("VM_NAME is '"+ORG_VM+"'")

if __name__ == '__main__':
    main()







