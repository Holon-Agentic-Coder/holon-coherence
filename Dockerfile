FROM mitmproxy/mitmproxy:12.2.3@sha256:00b77b5d8804c8ad18cb6caefbf9d5849e895e8986c5ce011f4ae30f4385962f

USER root

COPY --from=ghcr.io/astral-sh/uv:0.9.5@sha256:f459f6f73a8c4ef5d69f4e6fbbdb8af751d6fa40ec34b39a1ab469acd6e289b7 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md /app/
COPY src/ /app/src/
RUN uv export --frozen --no-dev --no-editable --no-hashes --no-header -o /tmp/requirements.txt && \
    uv pip install --system --no-cache -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt && \
    uv pip install --system --no-cache --no-deps .

RUN mkdir -p /home/mitmproxy/.holon/cache /tmp/wire_logs && \
    chown -R mitmproxy:mitmproxy /home/mitmproxy/.holon /tmp/wire_logs && \
    chmod 0755 /home/mitmproxy && \
    chmod 1777 /home/mitmproxy/.holon /tmp/wire_logs

ENV HOME=/home/mitmproxy
ENV WIRE_LOG_DIR=/tmp/wire_logs

USER mitmproxy
WORKDIR /home/mitmproxy

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import socket, sys; s = socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=3); s.close()" "${PORT:-8080}"

ENTRYPOINT ["holon-coherence"]
CMD ["start", "--port", "8080"]
