#!/usr/bin/python
#-*- coding: utf-8 -*-
'virt-dup'

# Py2/3 compatible tricks
try:
    # Python 2
    from cStringIO import StringIO
except ImportError:
    # Python 3
    from io import StringIO


import argparse
import os
import tempfile
import sys
import random
import uuid
import subprocess
from subprocess import check_output
import re
import logging

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



def run_cmd(cmd, shell=True):
    '''
    Run a cmd, return (rc, stdout, stderr)
    '''
    p = subprocess.Popen(cmd,
                         shell=shell,
                         universal_newlines=True,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    #out, err = p.communicate()
    so, se = p.communicate()
    out,err = ["%s"%so, "%s"%se]
    if re.search(r'command.not.found', out+err, re.M):
        logging.warn(" command-not-found='%s'", cmd)

    logging.debug('cmd="%s"', cmd)
    logging.debug("return_code=%s", p.returncode)

    if out:
        ss=out.splitlines()
        logging.debug("stdout=%s", ss[0])
        del ss[0]
        for line in ss:
            if not line: break
            logging.debug("       %s", line)

    if err:
        ss=err.splitlines()
        logging.debug("stderr="+"%s", ss[0])
        del ss[0]
        for line in ss:
            if not line: break
            logging.debug("       %s", line)

    return p.returncode, out, err






def new_xml(vm_xml, new_vm_name):
    'Manipulate name, uuid, mac, source files'
    # report what images won't be changed
    logging.debug(vm_xml)
    #logging.info(re.search(r'source file=', vm_xml.read(), re.M))



def cli_parser():
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description=DESCRIPTION, epilog=EPILOG)
    ap.add_argument('vm_name', metavar='VM_NAME', type=str,
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
        logging.critical("please run as a root user. Refer to -h | --help")
        sys.exit(-1)


def dup_img(org_img_file, new_img_file):
    'duplicate the image files with --reflink capability'
    logger = logging.getLogger('virt-dup')
    logger.debug("dup_img(): org = %s", org_img_file)
    logger.debug("dup_img(): new = %s", new_img_file)

    #check_output('df --output=fstype `dirname ${i}`')

    return

def main():

    tool_name = 'virt-dup'
    args = cli_parser().parse_args()

    logger = logging.getLogger(tool_name)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    f_log = logging.FileHandler('/var/log/%s.log'%tool_name)
    f_log.setFormatter(formatter)
    s_log = logging.StreamHandler(sys.stdout)
    s_log.setFormatter(formatter)
    #logger.addHandler(f_log)
    logger.setLevel(logging.INFO)


    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s %(message)s',
                        #filename='/var/log/%s.detailed.log'%tool_name,
                        filename='/var/log/%s.log'%tool_name,
                        filemode='a', level=logging.INFO)

    if args.verbose:
        logger.addHandler(s_log)
        logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)

    ensure_cli_env_is_root()

    # check VM names
    for VM in args.vm_name:
        if ' ' in VM:
            logging.critical(' space char, " ", is prohibited in VM_NAME, "%s"', VM)
            sys.exit(-1)

    org_vm_name = args.vm_name[0]
    del args.vm_name[0]
    if not args.vm_name:
        args.vm_name = ['%s_dup'%org_vm_name]
#    for new_vm_name in args.vm_name:
#        if new_vm_name in org_vm_name:
#            logging.critical('New VM name "%s" as the substring of the original VM name "%s" is prohibited',
#                             new_vm_name, org_vm_name)
#            sys.exit(-1)

    rc, _o, _e = run_cmd("virsh domstate %s"%(org_vm_name))
    if rc:
        logging.critical("the virtual machine '%s' doesn't exist", vm_name)
        sys.exit(-1)

#    vm_xml = tempfile.NamedTemporaryFile(prefix="domxml.",
#                                         suffix='.'+vm_name,
#                                         mode='w+t')
    with tempfile.TemporaryFile(prefix="domxml.",
                                suffix=org_vm_name, mode='w+t') as org_vm_xml:
        rc, o, _e = run_cmd("virsh dumpxml '%s'"% org_vm_name)

    for _s, path, name, _e in re.findall(r"(.*<source file=')(\S*/)(\S+)('/>)$", o, re.M):
        if re.match(org_vm_name, name): continue
        logger.info("'%s' is shared among VMs", path+name)

    re_org_img = re.compile(r"(.*<source file=')(\S*/)(%s)(\S+)('/>$)"%org_vm_name, re.M)
    re_all_img = re.compile(r"(.*<source file=')(\S*/)(\S+)('/>$)", re.M)
    re_domain_name = re.compile(r'<name>.*</name>')
    re_uuid = re.compile(r'<uuid>.*</uuid>')
    re_mac = re.compile(r'<mac address=.*/>', re.M)

    for new_vm_name in args.vm_name:

        re_new_img0 = re.compile(r".*<source file='(\S*/%s\S+)'/>$"%new_vm_name, re.M)
        logger.info("vm '%s' is under processing for '%s'", org_vm_name, new_vm_name)

        # 1. to change Domain Name
        new_xml = re_domain_name.sub(r'<name>%s</name>'%new_vm_name, o)

        # 2. to change Domain UUID
        new_xml = re_uuid.sub(r'<uuid>%s</uuid>'%str(uuid.uuid4()), new_xml)

        # 3. to change MAC address
        for m in re_mac.findall(new_xml):
            macaddr_random = '52:54:00:'+':'.join(['%02x' % x for x in map(lambda x: random.randint(0,255), range(3))])
            new_xml = re.sub(m, '<mac address=%s/>'% macaddr_random, new_xml)

        # 4. to change all backing storage image files
        #    to replace all prefix to new VM name
        new_xml = re_org_img.sub(r'\1\2%s\4\5'%new_vm_name, new_xml)

        # debugging: to validate result
        logger.debug('%s', re_domain_name.findall(new_xml))
        logger.debug('%s', re_uuid.findall(new_xml))
        for x in re_mac.findall(new_xml):
            logger.debug("['%s']", x)
        logger.debug(re_new_img0.findall(new_xml))
        logging.debug(new_xml)

        #for x in re.findall(r".*<source file='(\S*/%s\S+)'/>$"%org_vm_name, o, re.M):
        for head, path, prefix, name, misc in re_org_img.findall(o):
            t = head+path+prefix+name+misc
            x = path+prefix+name
            y = re_org_img.sub(r'\2%s\4'%new_vm_name, t)
            logger.info("'%s' to be duplicated", y)
            dup_img(x, y)











if __name__ == '__main__':
    main()







