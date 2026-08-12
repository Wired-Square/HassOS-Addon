ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

#
# WireTAP release supplying the GVRET server. Bump to upgrade.
#
ARG WIRETAP_VERSION=v0.10.1

#
# python3 is 3.12 on the current Alpine base, satisfying wiretap-server's
# unguarded "import tomllib" (needs >= 3.11). pyroute2 and psycopg2 are taken
# from apk rather than pip because psycopg2-binary ships no musl wheels and
# would otherwise compile from source on the Pi at install time.
#
RUN apk add --no-cache \
    can-utils \
    iproute2 \
    eudev \
    python3 \
    py3-pyroute2 \
    py3-psycopg2

ADD https://raw.githubusercontent.com/Wired-Square/WireTAP/${WIRETAP_VERSION}/tools/wiretap-server/wiretap-server.py \
    /usr/sbin/wiretap-server.py

WORKDIR /data

COPY rootfs/ /

RUN chmod a+x /run.sh /usr/sbin/can-util /usr/sbin/gvret-util /usr/sbin/wiretap-server.py

CMD [ "/run.sh" ]

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
