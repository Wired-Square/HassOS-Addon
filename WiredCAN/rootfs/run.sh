#! /usr/bin/with-contenv bash

/usr/sbin/can-util configure

# Keep the docker container alive. This will eventually not be necessary.
#

until false; do
  sleep 14400
done
