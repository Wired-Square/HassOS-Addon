ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

#
# WireTAP release supplying the GVRET server. Bump to upgrade.
#
ARG WIRETAP_VERSION=v0.10.1

#
# wiretap-server imports tomllib unguarded, so it needs python3 >= 3.11. Only
# pyroute2 is required beyond that, for reading the bus bitrate; psycopg2 is
# not, because we forward to a gateway rather than writing to Postgres.
#
RUN apk add --no-cache \
    can-utils \
    iproute2 \
    eudev \
    python3 \
    py3-pyroute2

ADD https://raw.githubusercontent.com/Wired-Square/WireTAP/${WIRETAP_VERSION}/tools/wiretap-server/wiretap-server.py \
    /usr/sbin/wiretap-server.py

WORKDIR /data

COPY rootfs/ /

#
# Globbed rather than listed, so a new service or tool cannot be left
# non-executable. s6 would respawn a non-executable run script forever.
#
RUN chmod a+x \
    /etc/cont-init.d/* \
    /etc/services.d/*/run \
    /etc/services.d/*/finish \
    /usr/sbin/can-util \
    /usr/sbin/gvret-util \
    /usr/sbin/framelink-util \
    /usr/sbin/framelink-server.py \
    /usr/sbin/wiretap-server.py

#
# No CMD: the base image's s6-overlay entrypoint runs /etc/cont-init.d to
# provision the interfaces, then supervises the servers in /etc/services.d.
#

#
#
# Build arguments
#
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="addon" \
  io.hass.arch="${BUILD_ARCH}"
