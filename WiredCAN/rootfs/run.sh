#! /usr/bin/with-contenv bash

/usr/sbin/can-util configure

mkdir -p /config/custom_components

git clone git@github.com:garthberry/homeassistant-canswitch.git /config/custom_components/canswitch

# Keep the docker container alive. This will eventually not be necessary.
#

until false; do
  sleep 14400
done
