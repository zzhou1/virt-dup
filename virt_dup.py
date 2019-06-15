#!/usr/bin/env python3
#-*- coding: utf-8 -*-
'virt-dup'

import argparse
import os
import tempfile
import sys
import random
import uuid
import subprocess
import re
import logging
from subprocess import check_output

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

  virt-dup VMx VMy
  "VMy" must not the substring of "VMx".

  virt-dup VMx VM1 VM2 VM3
  virt-dup VMx VM{1..3}
  This will create three Virtual Machines, namely, VM1 VM2 VM3.

  virt-dup --set-ip 192.168.151.101 VMx VM{1..16}
  It creates 16 virtual machines, which has its own unique ip from 101 to 116.

  Use the following example with care!

  virt-dup VMx --change-ip VMx:VMy,192.168.150:192.168.151,IpSubStr1:IpSubStr2
  It applies: 
      sed -i 's/\\(IPADDR.*\\)$VMx/\\1$VMy/g' /etc/sysconfig/network/ifcfg*

"""



def run_cmd(cmd, shell=True):
    '''
    Run a cmd, return (rc, stdout, stderr)
    '''

    logger = logging.getLogger()

    cli = subprocess.Popen(cmd,
                           shell=shell,
                           universal_newlines=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,
                           text=True)
    out, err = cli.communicate()
    if re.search(r'command.not.found', out+err, re.M):
        logger.warning(" command-not-found='%s'", cmd)

    logger.debug('cmd="%s"', cmd)
    logger.debug("return_code=%s", cli.returncode)

    if out:
        sss = out.splitlines()
        logger.debug("stdout=%s", sss[0])
        del sss[0]
        for line in sss:
            if not line:
                break
            logger.debug("       %s", line)

    if err:
        sss = err.splitlines()
        logger.debug("stderr=%s", sss[0])
        del sss[0]
        for line in sss:
            if not line:
                break
            logger.debug("       %s", line)

    return cli.returncode, out, err


def generate_new_domxml(org_vm_name, org_domxml, new_vm_name):
    'Manipulate name, uuid, mac, source files'

    logger = logging.getLogger()

    # the match with the prefix of vm name
    re_org_img = re.compile(r"(.*<source file=')(\S*/)(%s)(\S+)('.*/>)$"%
                            org_vm_name, re.M)
    #re_all_img = re.compile(r"(.*<source file=')(\S*/)(\S+)('/>$)", re.M)
    re_domain_name = re.compile(r'<name>.*</name>')
    re_uuid = re.compile(r'<uuid>.*</uuid>')
    re_mac = re.compile(r'<mac address=.*/>', re.M)

    #re_new_img0 = re.compile(r".*<source file='(\S*/%s\S+)'/>$"%
    #                         new_vm_name, re.M)
    logger.debug("vm '%s' is under processing for '%s'",
                 org_vm_name, new_vm_name)

    # 1. to change Domain Name
    new_domxml = re_domain_name.sub(r'<name>%s</name>'%new_vm_name, org_domxml)

    # 2. to change Domain UUID
    new_domxml = re_uuid.sub(r'<uuid>%s</uuid>'%str(uuid.uuid4()), new_domxml)

    # 3. to change MAC address
    for mac in re_mac.findall(new_domxml):
        macaddr_random = '52:54:00:'+':'.join(['%02x' % x for x in map(
            lambda x: random.randint(0, 255), range(3))])
        new_domxml = re.sub(mac, "<mac address='%s'/>"%
                            macaddr_random, new_domxml)

    # 4. to change all backing storage image files
    #    to replace all prefix to new VM name
    #    the match with the prefix of vm name
    new_domxml = re_org_img.sub(r'\1\2%s\4\5'%new_vm_name, new_domxml)

    logger.debug(re_domain_name.findall(new_domxml))
    logger.debug(re_uuid.findall(new_domxml))
    for mac in re_mac.findall(new_domxml):
        logger.debug("['%s']", mac)
    #logger.debug(re_new_img0.findall(new_domxml))
    logger.debug(new_domxml)
    return new_domxml


def cli_parser():
    'docstring'
    ap1 = argparse.ArgumentParser(formatter_class=
                                  argparse.RawDescriptionHelpFormatter,
                                  description=DESCRIPTION, epilog=EPILOG)
    ap1.add_argument('vm_name', metavar='VM_NAME', type=str,
                     help='The original VM must exist in `virsh list --all`',
                     nargs='+')
    ap1.add_argument('-v', '--verbose', '-d', '--debug',
                     action='store_true')
    ap1.add_argument('--set-ip', dest='set_ip',
                     metavar='IPADDR', nargs=1,
                     help="Add IPADDR to the first NIC")
    ap1.add_argument('--change-ip', dest='change_ip',
                     metavar='from:to[,from:to,...]', nargs=1,
                     help="leverage the substring of IP is handy. Use it well!")
    return ap1


def ensure_cli_env_is_root():
    'docstring'
    if os.getuid() != 0:
        logging.critical("please run as root, and refer to -h | --help")
        sys.exit(-1)


def version_cmp(ver1, ver2):
    'kernel version comparison'
    def normalize(ver):
        return [int(x) for x in re.sub(r'(\.0+)*$', '', ver).split('.')]
    return normalize(ver1) > normalize(ver2)


def cp_reflink_img(org_img_file, new_img_file):
    'duplicate the image files with --reflink capability'
    logger = logging.getLogger()
    logger.debug("cp_reflink_img(): org = %s", org_img_file)
    logger.debug("cp_reflink_img(): new = %s", new_img_file)

    out = check_output(['dirname', org_img_file]).strip()
    logger.debug('cp_reflink_img(): dirname = %s', out)
    out = check_output(['df', '--output=fstype', out],
                       universal_newlines=True).split('\n')
    logger.debug(out)
    assert len(out) == 3
    logger.debug('cp_reflink_img(): fstype = %s', out[1])

    knl_ver = open('/proc/version', 'r').read().split()[2].split('-')[0]
    logger.debug('cp_reflink_img(): knl_version = %s', knl_ver)

    if (out[1] == 'xfs' and version_cmp(knl_ver, '4.16') < 0 and
            out[1] not in ['ocfs2', 'btrfs']):
        logger.info('no reflink support fs, copying might take time...')

    cmd = 'cp --reflink=auto -f {} {}'.format(org_img_file, new_img_file)
    logger.info(cmd)
    check_output(cmd.split())
    check_output(['fsync', new_img_file])


def reset_hostname_in_block_device(dev):
    'docstring'
    logger = logging.getLogger()
    logger.debug('reset_hostname_in_block_device( %r )', dev)

    assert check_output(['partprobe', dev]) == b''
    name_fstype = check_output('lsblk -lno NAME,FSTYPE {}'
                               .format(dev).split(),
                               universal_newlines=True).splitlines()
    for line in name_fstype:
        if (len(line.split()) > 1 and
                line.split()[1] in ['xfs', 'btrfs', 'ocfs2', 'ext4']):
            logger.debug(line)


#def manipulate_rootfs_in_raw_img(img_file):
#    'docstring'
#    return


def manipulate_rootfs_in_qcow2(img_file):
    'docstring'
    logger = logging.getLogger()

    # find_unused_nbd_dev_node()
    assert check_output('modprobe nbd max_part=8'.split()) == b''

    # lsblk -I43 only includes nbd devices, -d only disks, no partitions
    for line in open('/proc/devices', 'r'):
        if 'nbd' in line:
            dev_major_nbd = line.split()[0]
            break
    assert dev_major_nbd.isdigit()
    lsblk_o = check_output('lsblk -I{} -nd -o NAME'
                           .format(dev_major_nbd)
                           .split()).decode('utf-8')
    for i in range(100):
        if 'nbd{}'.format(i) not in lsblk_o:
            break

    # setup the nbd device
    cmd = 'qemu-nbd --connect=/dev/nbd{} {}'.format(i, img_file)
    logger.debug(cmd)
    check_output(cmd.split())

    reset_hostname_in_block_device('/dev/nbd' + str(i))

    cmd = 'qemu-nbd --disconnect /dev/nbd' + str(i)
    logger.debug(cmd)
    check_output(cmd.split())


def config_logger(args):
    'docstring'
    tool_name = 'virt-dup'
    var_log_path = "/var/log/{0}/{0}.log".format(tool_name)

    format_txt = '%(asctime)s %(levelname)-5s: %(message)s'
    logging.basicConfig(format=format_txt,
                        filename=var_log_path,
                        filemode='a',
                        level=logging.INFO)

    logger = logging.getLogger()

    s_log = logging.StreamHandler(sys.stdout)
    s_log.setFormatter(logging.Formatter(format_txt))
    logger.addHandler(s_log)

    if args.verbose:
        logger.setLevel(logging.DEBUG)


def libvirt_define_new_vm_domains(org_vm_name, org_domxml, new_vm_name):
    'docstring'
    logger = logging.getLogger()

    ret, _o, _e = run_cmd('virsh domstate ' + new_vm_name)
    if ret == 0:

        # bring dom to 'shut off' state, if not
        if 'shut off' not in _o:
            logger.info("vm '%s' is active. Call virsh to destroy it",
                        new_vm_name)
            ret, _o, _e = run_cmd('virsh destroy ' + new_vm_name)
            if ret:
                logger.critical("failed to destroy '%s'", new_vm_name)
                return 1

        # now is safe to 'undefine' the dom
        logger.info("vm '%s' already exists. Call virsh to undefine it",
                    new_vm_name)
        ret, _o, _e = run_cmd('virsh undefine ' + new_vm_name)
        if ret:
            logger.critical("failed to undefine '%s'", new_vm_name)
            return 1


    new_domxml = generate_new_domxml(org_vm_name, org_domxml, new_vm_name)
    with tempfile.NamedTemporaryFile(prefix="virt-dup.domxml.",
                                     suffix='.' + new_vm_name + '.xml',
                                     mode='w+t') as new_xml:
        new_xml.write(new_domxml)
        new_xml.flush()
        cmd = 'virsh define '+new_xml.name
        logger.info(cmd)
        logger.debug(check_output(cmd.split()))

    return 0


def processing_vm_and_img(args, org_vm_name, org_domxml):
    'docstring'
    logger = logging.getLogger()

    # search all image files with org_vm_name as the prefix
    re_org_img = re.compile(r"(.*<source file=')(\S*/)(%s)(\S+)('.*/>)$"%
                            org_vm_name, re.M)
    for new_vm_name in args.vm_name:

        if libvirt_define_new_vm_domains(org_vm_name, org_domxml, new_vm_name):
            continue

        for head, path, prefix, name, misc in re_org_img.findall(org_domxml):
            xml_tag_src_img = head+path+prefix+name+misc
            new_img_path = re_org_img.sub(r'\2%s\4'%new_vm_name,
                                          xml_tag_src_img)
            logger.debug("'%s' to be duplicated", new_img_path)
            cp_reflink_img(path+prefix+name, new_img_path)

            ret = check_output(['file', '-b', new_img_path]).decode('utf-8')
            logger.debug('file type {}'.format(ret).strip())
            if 'QCOW' in ret:
                manipulate_rootfs_in_qcow2(args, new_img_path, new_vm_name)
            #else:
            #    manipulate_rootfs_in_raw_img(new_img_path)


def  main():
    'docstring'

    args = cli_parser().parse_args()

    config_logger(args)
    logger = logging.getLogger()

    ensure_cli_env_is_root()

    # check VM names
    for name in args.vm_name:
        if ' ' in name:
            logging.critical(' the space char is prohibited, "%s"', name)
            sys.exit(-1)

    # get org_domxml
    org_vm_name = args.vm_name[0]
    del args.vm_name[0]
    if not args.vm_name:
        args.vm_name = ['%s_dup'%org_vm_name]

    ret, _o, _e = run_cmd("virsh domstate %s"%(org_vm_name))
    if ret:
        logging.critical("the virtual machine '%s' doesn't exist", org_vm_name)
        sys.exit(-1)

    org_domxml = check_output(('virsh dumpxml ' + org_vm_name).split(),
                              universal_newlines=True).strip()

    # info user all image files shared among VM
    for _s, path, image_name, _e in re.findall(
            r"(.*<source file=')(\S*/)(\S+)('/>)$", org_domxml, re.M):
        if re.match(org_vm_name, image_name):
            continue
        logger.info("'%s' is shared among VMs", path+image_name)

    processing_vm_and_img(args, org_vm_name, org_domxml)


#
#
#
if __name__ == '__main__':
    main()
