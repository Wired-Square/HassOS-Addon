#! /usr/bin/with-contenv bash

/usr/sbin/can-util configure

until false; do
  sleep 14400
done
