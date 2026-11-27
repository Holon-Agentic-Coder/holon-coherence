FROM mitmproxy/mitmproxy:12.2.3

USER root

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src/ /app/src/
RUN pip install --no-cache-dir .

RUN mkdir -p /home/mitmproxy/.holon/cache /tmp/wire_logs && \
    chown -R mitmproxy:mitmproxy /home/mitmproxy/.holon /tmp/wire_logs && \
    chmod 0755 /home/mitmproxy && \
    chmod 1777 /home/mitmproxy/.holon /tmp/wire_logs

ENV HOME=/home/mitmproxy
ENV WIRE_LOG_DIR=/tmp/wire_logs

USER mitmproxy
WORKDIR /home/mitmproxy

EXPOSE 8080 8081

ENTRYPOINT ["holon-coherence"]
CMD ["start", "--port", "8080"]
