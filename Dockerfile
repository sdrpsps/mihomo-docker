# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM alpine:3.23 AS compress
RUN apk add --no-cache upx
ARG TARGETARCH
COPY --from=upstream --chmod=0755 /mihomo-${TARGETARCH} /mihomo
RUN upx --best --lzma /mihomo && upx --test /mihomo

FROM alpine:3.23
RUN apk add --no-cache ca-certificates curl python3 py3-yaml '!python3-pyc' '!py3-yaml-pyc' && \
    addgroup -g 10001 mihomo && \
    adduser -D -H -u 10001 -G mihomo mihomo && \
    install -d -m 0700 -o mihomo -g mihomo /data
COPY --from=compress --chmod=0555 /mihomo /usr/local/bin/mihomo
COPY --from=upstream /dist/ /opt/zashboard/
COPY --from=upstream /licenses/ /usr/share/licenses/mihomo-zashboard/
COPY --from=upstream /versions /usr/share/mihomo-zashboard/versions
COPY --chmod=0555 manager.py /usr/local/bin/mihomo-manager
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/data SAFE_PATHS=/opt/zashboard
WORKDIR /data
USER 10001:10001
EXPOSE 7890 9090
HEALTHCHECK --interval=15s --timeout=4s --start-period=60s CMD ["/usr/local/bin/mihomo-manager", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/mihomo-manager"]
