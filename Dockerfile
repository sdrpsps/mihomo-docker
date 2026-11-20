# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM alpine:3.23 AS upstream-tools
RUN apk add --no-cache ca-certificates curl jq unzip upx
WORKDIR /tmp/downloads
COPY fetch-upstream.sh /usr/local/bin/fetch-upstream.sh

FROM upstream-tools AS releases
RUN sh /usr/local/bin/fetch-upstream.sh resolve

FROM releases AS upstream
ARG TARGETARCH
RUN sh /usr/local/bin/fetch-upstream.sh pack "$TARGETARCH"

FROM alpine:3.23
RUN apk add --no-cache ca-certificates curl python3 py3-yaml '!python3-pyc' '!py3-yaml-pyc' && \
    addgroup -g 10001 mihomo && \
    adduser -D -H -u 10001 -G mihomo mihomo && \
    install -d -m 0700 -o mihomo -g mihomo /data
COPY --from=upstream /tmp/downloads/mihomo /usr/local/bin/mihomo
COPY --from=upstream /tmp/downloads/dist/ /opt/zashboard/
COPY --from=upstream /tmp/downloads/*.LICENSE /usr/share/licenses/mihomo-zashboard/
COPY --from=releases /tmp/downloads/versions /usr/share/mihomo-zashboard/versions
COPY --chmod=0555 manager.py /usr/local/bin/mihomo-manager
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/data SAFE_PATHS=/opt/zashboard
WORKDIR /data
USER 10001:10001
EXPOSE 7890 9090
HEALTHCHECK --interval=15s --timeout=4s --start-period=60s CMD ["/usr/local/bin/mihomo-manager", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/mihomo-manager"]
