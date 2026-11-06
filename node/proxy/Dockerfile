FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends tinyproxy-bin \
    && rm -rf /var/lib/apt/lists/*
COPY tinyproxy.conf allowed-hosts /etc/tinyproxy/
USER 21001:21001
EXPOSE 8888
ENTRYPOINT ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
