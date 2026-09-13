# Lightweight MITM proxy container running holon-coherence addon
FROM mitmproxy/mitmproxy:12.2.3

USER root

# Install holon-coherence package
WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src/ /app/src/
RUN pip install --no-cache-dir .

# Create coherence cache & log directories
RUN mkdir -p /home/mitmproxy/.holon/cache /tmp/wire_logs && \
    chown -R mitmproxy:mitmproxy /home/mitmproxy/.holon /tmp/wire_logs

ENV WIRE_LOG_DIR=/tmp/wire_logs

USER mitmproxy
WORKDIR /home/mitmproxy

EXPOSE 8080 8081

ENTRYPOINT ["holon-coherence"]
CMD ["start", "--port", "8080"]
