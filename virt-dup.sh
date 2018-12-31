#!/bin/bash
#
# Copyright (C) 2018-2019 Roger Zhou <zzhou@suse.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
#

log (){ [ "${IS_DEBUG}_x" = "YES_x" ] || return; echo "$1"; }
die () { echo "$1"; exit; }
is_cmd_installed () { which $1 >/dev/null 2>&1||die "error: $1 not exist"; }

run_cmd ()
{
   CMD_STDOUT=""
   [ -z "$1" ] && die "error: no argument for run_cmd()"
   log "run_cmd: $1"
   BINCMD=$(echo "$1"|cut -d' ' -f1)
   which $BINCMD >/dev/null 2>&1||die "error: $BINCMD not exist";
   if ! CMD_STDOUT="$($1 2>&1)"; then
      log "$CMD_STDOUT"
      echo "error: fatal. Please try --debug."
      die "error: failed $1"
   fi
   [ -z "$CMD_STDOUT" ] || log "$CMD_STDOUT"
   return 0
}

try_cmd ()
{
   [ -z "$1" ] && die "error: no argument for try_cmd()"
   log "try_cmd: $1"
   BINCMD=$(echo "$1"|cut -d' ' -f1)
   which $BINCMD >/dev/null 2>&1||die "error: $BINCMD not exist";
   CMD_STDOUT="$($1 2>&1)"
   TMP=$?
   [ -z "$CMD_STDOUT" ] || log "$CMD_STDOUT"
   return $TMP
}

function usage ()
{
    echo "Usage: $(basename $0) --original vmname [options]"
    echo -e "
This tool let you have fun to duplicate a Virtual Machine with qcow2 
and raw images in seconds, under those filesystems with the native
COW(--reflink) capability eg. btrfs, xfs-4.16, ocfs2. 

It is created, just because virt-clone does not yet leverage the native
COW capability of filesystems to duplicate qcow2. It only support RAW by
now at the end of 2018. virt-clone might need a long time to duplicate
qcow2 files, especially if they have backing files. With this, be
caution, this tool doesn't support qcow2 with baking files.

This tool will reset MAC and hostname of the Virtual Machine.

Options:
-h, --help
-v, --verbose, -d, --debug
-o, --original ORIGINAL_GUEST_NAME
-n, --name NEW_GUEST_NAME
"
    exit
}

####################################################################
# Bash options parsing
#
POSITIONAL=()
while [[ $# -gt 0 ]]
do
key="$1"

case $key in
    -o|--original)
    ORG_VM="$2"
    shift # past argument
    shift # past value
    ;;
    -n|--name)
    NEW_VM="$2"
    shift # past argument
    shift # past value
    ;;
    -f|--file)
    NEW_IMAGE_FILE_PATH="$2"
    shift # past argument
    shift # past value
    ;;
    -r|--reflink)
    IS_REFLINK=YES
    shift # past argument
    ;;
    -h|--help)
    usage
    shift # past argument
    ;;
    -v|--verbose|-d|--debug)
    IS_DEBUG=YES
    shift # past argument
    ;;
    *)    # unknown option
    POSITIONAL+=("$1") # save it in an array for later
    shift # past argument
    ;;
esac
done
set -- "${POSITIONAL[@]}" # restore positional parameters


if [[ -n $1 ]]; then
    usage
fi


####################################################################
# This stage is to dump the original VM configuration via libvirt
#
if [ "$EUID" -ne 0 ]; then
    echo "Please run as a root user, or -h | --help"
    exit
fi

DOMAIN_DUP_RANDOM=$RANDOM
if [[ -n ${ORG_VM} ]]; then
    echo ${ORG_VM}|grep " "
    if ! [ $? ]; then
       echo "This script don't work with the VM name has any 'space' char, '${ORG_VM}'"
       exit
    fi

    is_cmd_installed "virsh"

    if ! TEXT=$(virsh domstate ${ORG_VM} 2>&1); then
	echo "error: the virtual machine $ORG_VM doesn't exist"
	exit
    fi

    if [ "${TEXT}_x" = "shut off_x" ]; then
       log "${ORG_VM} is off."
    else
       run_cmd "virsh suspend ${ORG_VM} 2>&1"
       echo "${ORG_VM} get suspended to duplicate GUEST XML"
       IS_SUSPENDED="YES"
    fi

    DUP_XML="/tmp/${ORG_VM}_dup_${DOMAIN_DUP_RANDOM}.xml"
    log `virsh dumpxml ${ORG_VM} > ${DUP_XML}`
else
    usage
fi

if [ "${IS_SUSPENDED}_x" = "YES_x" ]; then
    run_cmd "virsh resume ${ORG_VM} 2>&1"
    echo "${ORG_VM} get resumed"
fi

####################################################################
# This stage is to define the new VM configuration via libvirt
#
[[ -z ${NEW_VM} ]] && NEW_VM="${ORG_VM}_dup"

log "${DUP_XML} is under processing for ${NEW_VM} "
log "$(grep -e "/name" -e "/uuid" -e "<mac address=" -e "<source file=.*${ORG_VM}.*"  ${DUP_XML})"

# handle multiple image files
ORG_VM_IMG_FILES=$(sed -n -E "s#(.*<source file=')(.+${ORG_VM}.+)('/>)#\2#p" ${DUP_XML})

if [[ -z ${ORG_VM_IMG_FILES} ]]; then
   log "Stop, no result to search $ORG_VM in any image file name"
   exit
fi


if TEXT=$(virsh domstate ${NEW_VM} 2>&1); then
   log ""
   echo "${NEW_VM} already exists, and call virsh to destroy and undefine"

   if ! [ "${TEXT}_x" = "shut off_x" ]; then
      TEXT="$(virsh destroy ${NEW_VM} 2>&1)"
      STATUS=$?
      log "${TEXT}"
      if [ "${STATUS}_x" = "1_x" ]; then
         echo "error: failed to destroy ${NEW_VM}"
        exit
      fi
   fi

   TEXT="$(virsh undefine ${NEW_VM} 2>&1)"
   STATUS=$?
   log "${TEXT}"
   if [ "${STATUS}_x" = "1_x" ]; then
      echo "error: failed to undefine ${NEW_VM}"
      exit
   fi
fi

#
#  1. Change Domain Name
sed -i "s#<name>.*</name>#<name>${NEW_VM}</name>#" ${DUP_XML}

#
#  2. Change Domain UUID 
sed -i "s#<uuid>.*</uuid>#<uuid>`cat /proc/sys/kernel/random/uuid`</uuid>#" ${DUP_XML}

#  3. Change MAC address
#  FIXME: what about multiple MAC?
MACADDR="52:54:00:$(echo ${DOMAIN_DUP_RANDOM} | md5sum | sed 's/^\(..\)\(..\)\(..\).*$/\1:\2:\3/')"
sed -i "s#<mac address=.*/>#<mac address='${MACADDR}'/>#" ${DUP_XML}

#
#  4. Change domain image file
#  handle multiple image files
sed -i -E "s#(<source file=.+)${ORG_VM}(.+)#\1${NEW_VM}\2#" ${DUP_XML}

log "${DUP_XML} is processed as"
log "$(grep -e "/name" -e "/uuid" -e "<mac address=" -e "<source file=.*${NEW_VM}.*"  ${DUP_XML})"

if ! TEXT="$(virsh define ${DUP_XML} 2>&1)"; then
    log "${TEXT}"
    echo "error: failed to define ${NEW_VM}"
    exit
fi

log "$TEXT"
echo "${NEW_VM} VM is newly defined"

####################################################################
# duplicate the image files with --reflink capability
#
NEW_VM_IMG_FILES=""
for i in $ORG_VM_IMG_FILES;
do
   NEW_F=$(echo ${i} | sed -E "s#(.+)${ORG_VM}(.+)#\1${NEW_VM}\2#")
   NEW_VM_IMG_FILES="$NEW_VM_IMG_FILES $NEW_F"

   run_cmd "df --output=fstype `dirname ${i}`"
   TMP=""
   TEXT=$(echo "$CMD_STDOUT"|tail -n1)
   [ "$TEXT" = "btrfs" ] && TMP="YES"
   [ "$TEXT" = "ocfs2" ] && TMP="YES"
   [ "$TEXT" = "xfs" ] && [ $(uname -r | cut -d'.' -f2) -ge 16 ] \
       && TMP="YES"

   CMD="cp --reflink=auto -f ${i} ${NEW_F}"
   if ! [ "$TMP" = "YES" ]; then
       echo "INFO: no reflink support fs, copying might take time..."
   fi
   echo "$CMD"

   run_cmd "$CMD"
done

L=$(sed -n -E "s#(.*<source file=')(.*)('/>)#\2#p" ${DUP_XML}|grep -v ${NEW_VM})
for i in $L;
do
    echo "INFO: $i is shared among VMs"
done


####################################################################
# virt-sysprep
#

# FIXME: seems virt-sysprep is not appropriate for this tool. 
function reset_hostname_via_sysprep ()
{
    echo "reset hostname, net, etc. will need tens of seconds"
    CMD="virt-sysprep -d $NEW_VM --hostname $NEW_VM --enable net-hwaddr,machine-id --run 'echo $NEW_VM > /etc/hostname'"
    echo "$CMD"
    log "`$CMD 2>&1`"
}

function find_unused_lo_device_node ()
{
   NUMS=$(lsblk|cut -d' ' -f1|grep loop|sed 's/loop//')
   DEV=""
   for i in {0..100}
   do
      LOOP_DEV_EXIST="NO"
      for j in $NUMS; do
         [ "${i}_x" = "${j}_x" ] && LOOP_DEV_EXIST="YES" && break
      done
      [ "$LOOP_DEV_EXIST" = "NO" ] && DEV="/dev/loop$i" && return 0

      i=$((i+1))
   done

   [ -z $DEV ] && die "error: no spare loop device under /dev/"
}

function find_unused_nbd_device_node ()
{
   is_cmd_installed "qemu-nbd"
   is_cmd_installed "modprobe"

   modprobe nbd max_part=8
   NUMS=$(lsblk|grep nbd|grep disk|cut -d' ' -f1|sed 's/nbd//')
   DEV=""
   for i in {0..100}
   do
      NBD_DEV_EXIST="NO"
      for j in $NUMS; do
         [ "${i}_x" = "${j}_x" ] && NBD_DEV_EXIST="YES" && break
      done
      [ "$NBD_DEV_EXIST" = "NO" ] && DEV="/dev/nbd$i" && return 0

      i=$((i+1))
   done

   [ -z $DEV ] && die "error: no spare nbd device under /dev/"
}

# INPUT: ${DEV}
function reset_hostname_in_block_device ()
{

   # Also deal with the filesystem image without partitions
   #try_cmd "partx --show --output NR - $DEV" ;# to fresh kernel data
   run_cmd "partprobe ${DEV}" 		  ;#fresh the kernel data
   run_cmd "lsblk -o NAME,FSTYPE -P $DEV" ;#both holder dev & its slaves
   TEXT=$(echo "$CMD_STDOUT"|grep -e 'TYPE="xfs"' -e 'TYPE="btrfs"' \
   -e 'TYPE="ext'|cut -d'"' -f2)

   for i in $TEXT
   do
      run_cmd "mount /dev/$i $M_POINT"
      if [ -e $M_POINT/etc/hostname ]; then
         run_cmd "cat $M_POINT/etc/hostname"
         echo $NEW_VM > $M_POINT/etc/hostname 
         run_cmd "fsync $M_POINT/etc/hostname"
         run_cmd "cat $M_POINT/etc/hostname"
      fi
      run_cmd "umount $M_POINT"
   done

}

# INPUT: ${IMG_FILE}
function reset_hostname_of_raw_image ()
{
   IMG_FILE="$1"

   find_unused_lo_device_node
   log "$DEV"

   run_cmd "losetup $DEV $IMG_FILE"
   reset_hostname_in_block_device $DEV
   run_cmd "losetup -d $DEV"
}


# INPUT: ${IMG_FILE}
function reset_hostname_via_qemu_nbd ()
{
   IMG_FILE="$1"

   find_unused_nbd_device_node
   log "$DEV"

   run_cmd "qemu-nbd --connect=$DEV ${IMG_FILE}"
   reset_hostname_in_block_device $DEV
   run_cmd "qemu-nbd --disconnect $DEV"
}


# handle rootfs either in QCOW or RAW image
#
M_POINT="/tmp/mnt.$DOMAIN_DUP_RANDOM"
run_cmd "mkdir $M_POINT"
for i in $NEW_VM_IMG_FILES;
do
   run_cmd "file -b ${i}"
   if `echo $CMD_STDOUT|grep QCOW > /dev/null 2>&1`; then
      reset_hostname_via_qemu_nbd "$i"
   else
      reset_hostname_of_raw_image "$i"
   fi
done
run_cmd "rm -df $M_POINT"


####################################################################
echo "now have fun: virsh start $NEW_VM"
[ -z $IS_DEBUG ] || [ -e ${DUP_XML} ] && rm ${DUP_XML} 




