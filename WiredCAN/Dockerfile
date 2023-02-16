ARG BUILD_FROM
FROM ${BUILD_FROM}
ENV LANG C.UTF-8

COPY rootfs /

RUN apk add --no-cache \
    can-utils=2021.08.0-r0

WORKDIR /data

RUN chmod a+x /run.sh

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
