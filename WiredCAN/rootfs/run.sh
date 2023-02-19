#! /usr/bin/with-contenv bash

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

BITRATE=""
RESTART_MS=""
TX_QUEUE_LEN=""
CONF="/data/options.json"


function get_conf () {
  #
  # Populate configuration variables from the JSON config file
  #

  json=$(cat ${CONF})

  BITRATE=$(echo $json | jq -r '.bitrate')
  RESTART_MS=$(echo $json | jq -r '."restart-ms"')
  TX_QUEUE_LEN=$(echo $json | jq -r '.tx_queue_length')
}


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

  hard_drives=$(hd_enum)

  echo "Attempting to patch the kernel config"

  for hard_drive in $hard_drives
  do
    echo "HDD: $hard_drive"
    hd_size ${hard_drive}
    partition=$(first_partition /dev/${hard_drive})
    if [ -z "$partition" ]
    then
      mkdir /mnt/${hard_drive}
      mount ${partition} /mnt/${hard_drive}
      # Did it work?
      echo "Mount says $?"
    fi
  done
}

patch_kernel_config    # We should really check if we are privileged somehow...

/usr/sbin/can-util configure

#mkdir -p /config/custom_components

#git clone git@github.com:garthberry/homeassistant-canswitch.git /config/custom_components/canswitch



# Keep the docker container alive. This will eventually not be necessary.
#
while true
do
  sleep 14400
done
