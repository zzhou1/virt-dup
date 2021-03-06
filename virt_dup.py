#!/usr/bin/env python3
#-*- coding: utf-8 -*-
'virt-dup'

import argparse
import os
import glob
import tempfile
import sys
import random
import uuid
import subprocess
import re
import logging
import ipaddress
from subprocess import check_output

DESCRIPTION = """\
  This tool is to duplicate Virtual Machines in seconds rather than minutes.
  The trick is to deploy all VM images in the filesystem with the native
  COW(--reflink) capability, eg. btrfs, xfs-4.16, ocfs2, etc. Noted that
  virt-clone leverages the native COW(--reflink) capability of the filesystem
  to duplicate RAW, but not for qcow2 by now at the end of 2018. This tool

  - reset hostname as same as the Virtual Machine name
  - reset MAC addresses
  - reset static IP to dhcp, if not specify '--change-ip'
  - calibrate /etc/hosts with VM_NAME, --set-ip-cidr, and --change-ip
  - is compatible with openSUSE MicroOS

  Tips:
  - to let a image shared among Virtual Machines, you should
    avoid the Virtual Machine name to be the substring of the image name.

"""

EPILOG = """\
examples:
  virt-dup VM_NAME  # it implies `virt-dup VM_NAME VM_NAME_dup`
  virt-dup VMx VM1 VM2 VM3

  To create 3 virtual machines, which has its own unique ip from 101 to 103
  virt-dup VMx VM{1..3} --set-ip-cidr 2001:db8:dead:beef::101
  virt-dup VMx VM{1..3} --set-ip-cidr 192.168.151.101/16

  Use the following example with care!
  virt-dup VMx VMy --change-ip str1,str2 192.168.150,192.168.151

  To rename the virtual machine only
  virt-dup VMx VMy --change-ip no

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
    re_domain_name = re.compile(r'<name>.*</name>')
    re_uuid = re.compile(r'<uuid>.*</uuid>')
    re_mac = re.compile(r'<mac address=.*/>', re.M)

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
    # NOTE: https://stackoverflow.com/questions/5984633/python-re-sub-group-number-after-number
    new_domxml = re_org_img.sub(r'\1\g<2>%s\4\5'%new_vm_name, new_domxml)

    logger.debug(re_domain_name.findall(new_domxml))
    logger.debug(re_uuid.findall(new_domxml))
    for mac in re_mac.findall(new_domxml):
        logger.debug("['%s']", mac)
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
    ap1.add_argument('--set-ip-cidr', dest='set_ip_cidr',
                     metavar='CIDR', nargs=1,
                     help="add IP_CIDR to the first NIC")
    ap1.add_argument('--change-ip', dest='change_ip',
                     metavar='from,to', nargs='+',
                     help="string replace of IP is handy. 'no' means don't touch IP addr")
    return ap1


def ensure_cli_env_is_root():
    'docstring'
    if os.getuid() != 0:
        logging.critical("please run as root, and refer to -h | --help")
        sys.exit(-1)


def knl_version_cmp(ver1, ver2):
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
    logger.debug('cp_reflink_img(): dirname = %s', out.decode('utf-8'))
    out = check_output(['df', '--output=fstype', out],
                       universal_newlines=True).split('\n')
    logger.debug(out)
    assert len(out) == 3
    logger.debug('cp_reflink_img(): fstype = %s', out[1])

    with open('/proc/version', 'r') as fd_proc_version:
        knl_ver = fd_proc_version.read().split()[2].split('-')[0]
    logger.debug('cp_reflink_img(): knl_version = %s', knl_ver)

    if (out[1] == 'xfs' and knl_version_cmp(knl_ver, '4.16') < 0 and
            out[1] not in ['ocfs2', 'btrfs']):
        logger.info('no reflink support fs, copying might take time...')

    cmd = 'cp --reflink=auto -f {} {}'.format(org_img_file, new_img_file)
    logger.info(cmd)
    check_output(cmd.split())
    check_output(['fsync', new_img_file])


class DevMntpoint(tempfile.TemporaryDirectory):
    ''' upon destruction
        - mpoint will umount
        - the temporary directory under /tmp will be deleted afterwards
    '''

    def __init__(self, suffix=None, prefix=None, dev=None):
        self.logger = logging.getLogger()
        if not os.path.exists('/dev/'+dev):
            self.logger.error("DevMntpoint 'dev=' args must be valid under '/dev'")
        self.dev = dev
        super().__init__(suffix, prefix)
    def __enter__(self):
        super().__enter__()
        cmd = 'mount /dev/' + self.dev + ' ' + self.name
        self.logger.debug(cmd)
        check_output(cmd.split())
        return self.name
    def __exit__(self, exc_type, exc_val, exc_tb):
        cmd = 'umount /dev/' + self.dev
        self.logger.debug(cmd)
        check_output(cmd.split())
        super().__exit__(exc_type, exc_val, exc_tb)


class OverlayMntpoint(tempfile.TemporaryDirectory):
    ''' upon destruction
        - mpoint will umount
        - the temporary directory under /tmp will be deleted afterwards
    '''

    def __init__(self, suffix=None, prefix=None, mount_opt=None):
        self.mount_opt = mount_opt
        self.logger = logging.getLogger()
        super().__init__(suffix, prefix)

    def __enter__(self):
        super().__enter__()
        cmd = 'mount -t overlay overlay -o{} {}'.format(self.mount_opt, self.name)
        self.logger.debug(cmd)
        check_output(cmd.split())
        return self.name

    def __exit__(self, exc_type, exc_val, exc_tb):
        cmd = 'umount ' + self.name
        self.logger.debug(cmd)
        check_output(cmd.split())
        super().__exit__(exc_type, exc_val, exc_tb)


#def manipulate_rootfs_in_raw_img(img_file):
#    'docstring'
#    return


class SpareNbdImgfile():
    '''
                self.img_file
                self.spare_nbd
    '''

    def __init__(self, img_file=None):
        self.logger = logging.getLogger()
        if not os.path.exists(img_file):
            self.logger.error("NbdImg 'img_file=' args not exist")
        self.img_file = img_file

        # find_unused_nbd_dev_node()
        assert check_output('modprobe nbd max_part=8'.split()) == b''

        # lsblk -I43 only includes nbd devices, -d only disks, no partitions
        with open('/proc/devices', 'r') as fd_proc_dev:
            for line in fd_proc_dev:
                if 'nbd' in line:
                    dev_major_nbd = line.split()[0]
                    break
        assert dev_major_nbd.isdigit()
        lsblk_o = check_output('lsblk -I{} -nd -o NAME'
                               .format(dev_major_nbd)
                               .split()).decode('utf-8')

        for i in range(100):
            if 'nbd{}'.format(i) not in lsblk_o:
                #self.spare_nbd_id = i
                self.spare_nbd = '/dev/nbd'+str(i)
                self.logger.debug('spare_nbd = %s', self.spare_nbd)
                break

    def __enter__(self):
        cmd = 'qemu-nbd --connect={} {}'.format(self.spare_nbd, self.img_file)
        self.logger.debug(cmd)
        assert check_output(cmd.split()) == b''
        return self.spare_nbd

    def __exit__(self, exc_type, exc_val, exc_tb):
        cmd = 'qemu-nbd --disconnect ' + self.spare_nbd
        self.logger.debug(cmd)
        ret = check_output(cmd.split()).decode('utf-8').strip()
        self.logger.debug(ret)
        assert 'disconnected' in ret

        # flush kernel device data
        run_cmd('partprobe ' + self.spare_nbd)

        # double confirm kernel data get cleaned up indeed
        ret, _o, _e = run_cmd('lsblk ' + self.spare_nbd)
        assert ret == 32

    def __repr__(self):
        return self.spare_nbd


def reset_hostname(sysroot_etc, new_vm_name):
    'docstring'
    logger = logging.getLogger()
    logger.debug('reset_hostname(%s)', sysroot_etc)

    old_hostname = None
    path = str(sysroot_etc)+'/hostname'
    if os.path.exists(path):
        with open(path) as file:
            ret = file.read().strip()
            old_hostname = ret

    with open(sysroot_etc+'/hostname', 'w') as file:
        file.write(new_vm_name)
        file.flush()
        logger.debug('reset '+new_vm_name+':'+file.name)
        logger.info("reset /etc/hostname to '%s' from '%s'", new_vm_name, old_hostname)

    if os.path.exists(sysroot_etc+'/hosts') and len(old_hostname) > 0:
        with open(sysroot_etc+'/hosts', 'r') as file:
            old_hosts = file.read()
            logger.debug('old_hosts= %s', old_hosts)

        if old_hostname in old_hosts:
            with open(sysroot_etc+'/hosts', 'w') as file:
                new_hosts = old_hosts.replace(old_hostname, new_vm_name)
                file.write(new_hosts)
                file.flush()

                logger.debug('reset '+new_vm_name+':'+file.name)
                for i in new_hosts.splitlines():
                    if new_vm_name in i:
                        logger.info("reset  %s:/etc/hosts", new_vm_name)
                        break


def set_ip_cidr(sysroot_etc, new_vm_name, new_ip_cidr):
    'docstring'
    logger = logging.getLogger()
    logger.debug('set_ip_cidr(%s, %s)', sysroot_etc, new_ip_cidr)

    ### ipaddr in ifcfg-*
    for i in glob.glob(sysroot_etc+'/sysconfig/network/ifcfg-*'):
        if 'ifcfg-lo' in i:
            continue

        with open(i, 'r') as file:
            ifcfg = file.read()

        # set new_ip_cidr to the first match IPADDR_x, or append
        pattern = re.compile(r"^(\s*IPADDR_\d+\s*=\s*)(.*)$", re.M)
        ret = pattern.search(ifcfg)
        if ret is not None:
            new_ifcfg = "{}'{}'".format(ret.group(1), new_ip_cidr)
            ifcfg = pattern.sub(new_ifcfg, ifcfg, 1)
            logger.info("set   %s:%s: %s, from %s",
                        new_vm_name,
                        re.sub(r'.*/sysconfig/', '/etc/sysconfig/', i),
                        new_ifcfg,
                        ret.group(2))
        else:  # need append IPADDR_1
            new_ifcfg = 'IPADDR_1=' + "'" + new_ip_cidr + "'"
            ifcfg = ifcfg + new_ifcfg
            logger.info("set   %s:%s: %s (appended)",
                        new_vm_name,
                        re.sub(r'.*/sysconfig/', '/etc/sysconfig/', i),
                        new_ifcfg)

        logger.debug(ifcfg)
        with open(i, 'w') as file:
            file.write(ifcfg)
            file.flush()
        break

    ### /etc/hosts
    with open(sysroot_etc+'/hosts', 'r') as file:
        old_hosts = file.read()

    new_ip = str(ipaddress.ip_interface(new_ip_cidr).ip)
    pattern = re.compile(r'^\s*([\w:\.]+)(\s+\b%s[\b\.].*)$'%new_vm_name, re.M)
    ret = re.search(pattern, old_hosts)
    if ret is not None:
        new_hosts = re.sub(pattern, r'%s\2'%new_ip, old_hosts)
        logger.debug('new_hosts\n%s', new_hosts)
        logger.info("set   %s:/etc/hosts: %s%s", new_vm_name, new_ip, ret.group(2))
        with open(sysroot_etc+'/hosts', 'w') as file:
            file.write(new_hosts)
            file.flush()


def reset_ip_static_to_dhcp(sysroot_etc, new_vm_name):
    'docstring'
    logger = logging.getLogger()
    logger.debug('reset_ip_static_to_dhcp(%s)', sysroot_etc)

    for i in glob.glob(sysroot_etc+'/sysconfig/network/ifcfg-*'):
        if 'ifcfg-lo' in i:
            continue

        ifcfg_changed = False
        with open(i, 'r') as file:
            ifcfg = file.read()

        pattern = re.compile(r'^\s*BOOTPROTO\s*=.*static.*$', re.M)
        ret = pattern.search(ifcfg)
        if ret is not None:
            ifcfg_changed = True
            ifcfg = pattern.sub("BOOTPROTO='dhcp'", ifcfg)
            logger.info("reset %s:%s: BOOTPROTO='dhcp', from 'static'",
                        new_vm_name,
                        re.sub(r'.*/sysconfig/', '/etc/sysconfig/', i))

        pattern = re.compile(r"^(\s*IPADDR[_\d]*\s*=)([\s\"']*[\w\.:/]+[\"']*)$", re.M)
        for ret, ip_cidr in pattern.findall(ifcfg, re.M):
            ifcfg_changed = True
            logger.info("reset %s:%s: %s'', from %s",
                        new_vm_name,
                        re.sub(r'.*/sysconfig/', '/etc/sysconfig/', i),
                        ret, ip_cidr)
        ifcfg = pattern.sub(r"\1''", ifcfg)

        if ifcfg_changed:
            logger.debug(ifcfg)
            with open(i, 'w') as file:
                file.write(ifcfg)
                file.flush()

def change_ip(sysroot_etc, new_vm_name, arg_change_ip):
    'docstring'
    logger = logging.getLogger()

    for opt_change_ip in arg_change_ip:
        old_ip = opt_change_ip.split(',')[0]
        new_ip = opt_change_ip.split(',')[1]

        logger.debug('change_ip( %s, %s, %s,%s )',
                     sysroot_etc, new_vm_name, old_ip, new_ip )

        ### ipaddr in ifcfg-*
        for i in glob.glob(sysroot_etc+'/sysconfig/network/ifcfg-*'):
            if 'ifcfg-lo' in i:
                continue

            with open(i, 'r') as file:
                ifcfg = file.read()

            rcode = ifcfg.find(old_ip)
            ret = ifcfg.replace(old_ip, new_ip)
            if rcode > -1:
                logger.info("change %s:%s: %s",
                            new_vm_name,
                            re.sub(r'.*/sysconfig/', '/etc/sysconfig/', i),
                            new_ip)

                logger.debug(ret)
                with open(i, 'w') as file:
                    file.write(ret)
                    file.flush()

        ### /etc/hosts
        with open(sysroot_etc+'/hosts', 'r') as file:
            old_hosts = file.read()

        rcode = old_hosts.find(old_ip)
        ret = old_hosts.replace(old_ip, new_ip)
        logger.debug(ret)
        if rcode > -1:
            logger.info("change %s:/etc/hosts: %s", new_vm_name, new_ip)
            with open(sysroot_etc+'/hosts', 'w') as file:
                file.write(ret)
                file.flush()




def manipulate_etc(args, sysroot_etc, new_vm_name):
    'docstring'
    logger = logging.getLogger()
    logger.debug('manipulate_etc( %s )', sysroot_etc)
    if sysroot_etc is None:
        logger.error('sysroot_etc must not None')
        return

    reset_hostname(sysroot_etc, new_vm_name)

    if args.change_ip is None:
        reset_ip_static_to_dhcp(sysroot_etc, new_vm_name)
    elif args.change_ip[0] != 'no':
        change_ip(sysroot_etc, new_vm_name, args.change_ip)
        return

    if args.set_ip_cidr is not None:
        set_ip_cidr(sysroot_etc, new_vm_name, args.set_ip_cidr[0])


def is_rootfs(path_sysroot):
    'docstring'

    return (os.path.exists('{}/etc'.format(path_sysroot)) and
            os.path.exists('{}/boot'.format(path_sysroot)) and
            os.path.exists('{}/var'.format(path_sysroot)))


def manipulate_rootfs_in_qcow2(args, img_file, new_vm_name):
    'docstring'
    logger = logging.getLogger()

    with SpareNbdImgfile(img_file) as spare_nbd:

        microos_rootfs_dev = None
        assert check_output(['partprobe', spare_nbd]) == b''

        # partition_and_fstype
        for line in check_output('lsblk -lno NAME,FSTYPE {}'
                                 .format(spare_nbd).split(),
                                 universal_newlines=True).splitlines():
            if not (len(line.split()) > 1 and
                    line.split()[1] in ['xfs', 'btrfs', 'ocfs2', 'ext4']):
                continue

            logger.debug(line)
            with DevMntpoint(suffix='.'+new_vm_name,
                             prefix="virt_dup_mnt_",
                             dev=line.split()[0]) as mpoint:

                logger.debug('mpoint = %s', mpoint)

                # rootfs - xfs, ext4
                if not line.split()[1] == 'btrfs':
                    if is_rootfs(mpoint):
                        manipulate_etc(args, mpoint+'/etc', new_vm_name)
                        return
                    continue

                cmd = 'btrfs property get -ts {}'.format(mpoint)
                logger.debug(cmd)
                ret = check_output(cmd.split()).strip().decode('utf-8')
                logger.debug(ret)

                # rootfs - btrfs normal - non- microos_rootfs
                if (ret == 'ro=false' and is_rootfs(mpoint) and
                        microos_rootfs_dev is None):
                    manipulate_etc(args, mpoint+'/etc', new_vm_name)
                    return

                # rootfs - microos_rootfs partition
                if ret == 'ro=true' and is_rootfs(mpoint):
                    microos_rootfs_dev = line.split()[0]
                    continue

                # rootfs - microos_var:lib/overlay/x/etc/...
                if not os.path.exists('{}/lib/overlay'.format(mpoint)):
                    continue

                with DevMntpoint(suffix='.'+new_vm_name,
                                 prefix="virt_dup_mnt_",
                                 dev=microos_rootfs_dev) as microos_rootfs:

                    logger.debug('microos_rootfs = %s', microos_rootfs)
                    logger.debug('microos_var = %s', mpoint)

                    if not os.path.exists(microos_rootfs+'/etc/fstab'):
                        logger.error('microos_rootfs must have /etc/fstab')
                        return

                    # overlay mount option
                    with open(microos_rootfs+'/etc/fstab', 'r') as file:
                        ret = file.read()
                        udir = re.search(r'.*(upperdir=[^,]+),', ret).group(1)
                        ldir = re.search(r'.*(lowerdir=[^,]+),', ret).group(1)
                        wdir = re.search(r'.*(workdir=[^,]+),', ret).group(1)
                        logger.debug('%s', udir)
                        logger.debug('%s', ldir)
                        logger.debug('%s', wdir)
                        ret = '{},{},{}'.format(ldir, udir, wdir)
                        ret = ret.replace('/sysroot/etc', microos_rootfs+'/etc')
                        ret = ret.replace('/sysroot/var', mpoint)

                    # construct overlayfs for microos_var_etc
                    with OverlayMntpoint(prefix='virt_dup_microos_etc_',
                                         suffix='.'+new_vm_name,
                                         mount_opt=ret) as mpoint:
                        manipulate_etc(args, mpoint, new_vm_name)
                        return


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

    ret, stdout, _e = run_cmd('virsh domstate ' + new_vm_name)
    if ret == 0:

        # bring dom to 'shut off' state, if not
        if 'shut off' not in stdout:
            logger.info("vm '%s' is active. Call virsh to destroy it",
                        new_vm_name)
            ret, _o, _e = run_cmd('virsh destroy ' + new_vm_name)
            if ret:
                logger.critical("failed to destroy '%s'", new_vm_name)
                return False

        # now is safe to 'undefine' the dom
        logger.info("vm '%s' already exists. Call virsh to undefine it",
                    new_vm_name)
        ret, _o, _e = run_cmd('virsh undefine ' + new_vm_name)
        if ret:
            logger.critical("failed to undefine '%s'", new_vm_name)
            return False

    new_domxml = generate_new_domxml(org_vm_name, org_domxml, new_vm_name)

    # the temporary file under /tmp is deleted as soon as it is closed
    with tempfile.NamedTemporaryFile(prefix="virt_dup_domxml_",
                                     suffix='.' + new_vm_name + '.xml',
                                     mode='w+t') as new_xml:
        new_xml.write(new_domxml)
        new_xml.flush()
        cmd = 'virsh define '+new_xml.name
        logger.info(cmd)
        ret = check_output(cmd.split()).decode('utf-8').strip()
        logger.debug(ret)
        assert 'defined' in ret

    return True


def processing_vm_and_img(args, org_vm_name, org_domxml):
    'docstring'
    logger = logging.getLogger()

    # search all image files with org_vm_name as the prefix
    re_org_img = re.compile(r"(.*<source file=')(\S*/)(%s)(\S+)('.*/>)$"%
                            org_vm_name, re.M)
    for new_vm_name in args.vm_name:

        if not libvirt_define_new_vm_domains(org_vm_name, org_domxml, new_vm_name):
            continue

        for head, path, prefix, name, misc in re_org_img.findall(org_domxml):
            xml_tag_src_img = head+path+prefix+name+misc
            new_img_path = path+new_vm_name+name
            logger.debug("'%s' to be duplicated", new_img_path)
            cp_reflink_img(path+prefix+name, new_img_path)

            ret = check_output(['file', '-b', new_img_path]).decode('utf-8')
            logger.debug('file type {}'.format(ret).strip())
            if 'QCOW' in ret:
                manipulate_rootfs_in_qcow2(args, new_img_path, new_vm_name)
            #else:
            #    manipulate_rootfs_in_raw_img(args, new_img_path)

        if args.set_ip_cidr is not None:
            ipif_b = int(ipaddress.ip_interface(args.set_ip_cidr[0])) + 1
            new_ip_cidr = str(ipaddress.ip_address(ipif_b))

            ret = re.search(r'/\d+', args.set_ip_cidr[0])
            if ret is not None:
                args.set_ip_cidr[0] = new_ip_cidr + ret.group(0)
            else:
                args.set_ip_cidr[0] = new_ip_cidr


def  process_args(args):
    'docstring'

    config_logger(args)
    logger = logging.getLogger()

    ensure_cli_env_is_root()

    # check VM names
    for name in args.vm_name:
        if ' ' in name:
            logger.critical(' the space char is prohibited, "%s"', name)
            sys.exit(-1)

    # --set-ip-cidr and --change-ip can't co-exist
    if args.set_ip_cidr is not None and args.change_ip is not None:
        logger.critical("--set-ip-cidr and --change-ip can't co-exist")
        sys.exit(-1)

    # --set-ip-cidr validation
    if args.set_ip_cidr is not None:
        try:
            ipaddress.ip_interface(args.set_ip_cidr[0])
        except ValueError:
            logger.critical('ip address/netmask is invalid: %s',
                            args.set_ip_cidr[0])
            sys.exit(-1)

    if args.change_ip is not None:
        str1 = args.change_ip[0].lower()
        args.change_ip[0]=str1
        if str1 != 'no' and ',' not in str1:
            logger.critical("'--change-ip %s' misses ','.", str1)
            sys.exit(-1)

    # get org_domxml
    org_vm_name = args.vm_name[0]
    del args.vm_name[0]
    if not args.vm_name:
        args.vm_name = ['%s_dup'%org_vm_name]

    ret, _o, _e = run_cmd("virsh domstate %s"%(org_vm_name))
    if ret:
        logger.critical("the virtual machine '%s' doesn't exist", org_vm_name)
        sys.exit(-1)

    org_domxml = check_output(('virsh dumpxml ' + org_vm_name).split(),
                              universal_newlines=True).strip()

    # info user all image files shared among VM
    for _s, path, image_name, _e in re.findall(
            r"(.*<source file=')(\S*/)(\S+)('.*/>)$", org_domxml, re.M):
        if re.match(org_vm_name, image_name):
            continue
        logger.info("'%s' is shared among VMs", path+image_name)

    processing_vm_and_img(args, org_vm_name, org_domxml)


    ret = ''
    for name in args.vm_name:
        ret = ret + "\n                               virsh start " + name
    logger.info("now have fun:%s", ret)

    sys.exit(0)


#
#
#
if __name__ == '__main__':
    process_args(cli_parser().parse_args())
