#! /usr/bin/with-contenv bashio

#
# Home Assistant Add-on run script
#
# (c) 2023 Wired Square Pty Ltd
#
# MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software
# and associated documentation files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial
# portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

# TODO: Seems like a better datastructure would be in order. Investigate bashio::config
CAN_CONTROLLER=$(bashio::config 'can_controller')
CAN0=$(bashio::config 'can0')
CAN0_OSCIALLATOR=$(bashio::config 'can0_oscillator')
CAN0_INT=$(bashio::config 'can0_interrupt')
CAN1=$(bashio::config 'can1')
CAN1_OSCIALLATOR=$(bashio::config 'can1_oscillator')
CAN1_INT=$(bashio::config 'can1_interrupt')
CONF="/data/options.json"
KERNEL_CONFIG="/mnt/config.txt"


function hd_enum {
  #
  # Enumerate the attached hard drives and return a space seperated list
  #

  hard_drives=""

  for device_path in /sys/block/*
  do
    device=$(basename $device_path)

    if [[ $device =~ ^(sd|mmcblk)[a-z0-9]+$ ]]
    then
      if [ -n "$hard_drives" ]
      then
        hard_drives="$hard_drives "
      fi

      echo -n "$(basename "$device") "
  fi
done
}


function hd_size {
  #
  # Return the size of the specified hard drive
  #
 
  hard_drives=$1

  for hard_drive in $hard_drives
  do
    size_mb=$(cat /sys/block/${hard_drive}/size | awk '{size=int($1*512/1024/1024); printf "%d,%03d MB\n", size/1000, size%1000}')

    echo "Hard drive found: ${hard_drive} which is ${size_mb}"
  done
}


function first_partition {
  #
  # Return the first partition of the specified hard drive
  #

  hard_drive=$1

  output=$(fdisk -l "$hard_drive" 2>/dev/null)
  part=$(echo "$output" | awk '/^\/dev/{print $1; exit}')

  echo $part
}


function patch_kernel_config {
  #
  # Path the kernel configuration to enable CAN interfaces
  #

  config=$1
  overlay="${config%%,*}"

  echo "Attempting to patch the kernel config - $config"

  if grep -q "^$config" ${KERNEL_CONFIG}
  then
    echo "Kernel is already patched. Nothing to do"
  elif grep -q "^$overlay" ${KERNEL_CONFIG}
  then
    echo "Modifying the file to include $1"
    sed -i "/^$overlay/c\\$config" ${KERNEL_CONFIG}
  else
    echo "Adding $1 to file"
    echo "${config}" >> ${KERNEL_CONFIG}
  fi
}


function enable_can_controller {
  #
  # Path the kernel configuration to enable CAN interfaces
  #

  echo "Determining the CAN controller"

  case $CAN_CONTROLLER in
    mcp2515)
      if grep -q "Hardware\s*:\s*BCM" "/proc/cpuinfo"; then

        #
        # MCP2515 devices on Raspberry Pi come up in the wrong order. A quick hack to make this work
        # as expected is to initialise CAN1 first. There may be a better way.
        #

        echo "Attempting to patch for Microchip MCP2515 on a Raspberry Pi"

        if $CAN1
        then
          kernel_config="dtoverlay=mcp2515-can1,oscillator=$CAN1_OSCIALLATOR,interrupt=$CAN1_INT"
          echo "Patching CAN1 with $kernel_config"
          patch_kernel_config "$kernel_config"
        fi

        if $CAN0
        then
          kernel_config="dtoverlay=mcp2515-can0,oscillator=$CAN0_OSCIALLATOR,interrupt=$CAN0_INT"
          echo "Patching CAN0 with $kernel_config"
          patch_kernel_config "$kernel_config"
        fi

      else

        echo "Not running on a Raspberry Pi. I have no idea what to do."

      fi
      ;;
    *)
      echo "Unknown CAN controller $CAN_CONTROLLER"
      ;;
  esac
}


function mount_boot_partition {
  #
  # Find the boot partition and mount it
  #

  # TODO: Refactor this function to be less crap
  hard_drives="$(hd_enum)"

  echo "Attempting to find the boot parttion"
  for hard_drive in $hard_drives
  do
    hd_size ${hard_drive}
    partition=$(first_partition /dev/${hard_drive})
    ret=$?

    if [[ "$ret" -eq 0 ]]
    then
      echo "Partition: $partition"
    else
      echo "Unable to find partition. Are you running in protected mode?"
    fi


    if [ -n "$partition" ]
    then
      mount ${partition} /mnt
      ret=$?
      echo "Mount says $ret"
    fi
  done

  return $ret
}


function umount_boot_partition {
  #
  # Unmount the boot partiton
  #

  umount /mnt

  return $?
}


set +e

if $(bashio::addon.protected)
then

  echo "Running in protected mode. Not attempting to patch the kernel."
  echo "This might be fine."

else

  echo "Protected mode is disabled. Attempting to patch the kernel."
  echo "Once patched, protection mode is no longer required and"
  echo "you should turn it back on."

  if mount_boot_partition
  then
    echo "Mounted boot partition"
  else
    echo "Mounting boot partition failed"
  fi

  enable_can_controller

  if umount_boot_partition
  then
    echo "Boot partition unmounted"
  else
    echo "Boot partition unmount failed."
  fi

fi


/usr/sbin/can-util configure

mkdir -p /config/custom_components

#git clone git@github.com:garthberry/homeassistant-canswitch.git /config/custom_components/canswitch



# Keep the docker container alive. This will eventually not be necessary.
#
while true
do
  sleep 14400
done
