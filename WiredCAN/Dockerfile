ARG BUILD_FROM=ghcr.io/hassio-addons/base:13.1.1
FROM ${BUILD_FROM}
ENV LANG C.UTF-8

COPY rootfs /

RUN apk add --no-cache \
    wget=1.21.3-r2
    
WORKDIR /data

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
