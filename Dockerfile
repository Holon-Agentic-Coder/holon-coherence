# Lightweight MITM proxy container running holon-coherence addon
FROM mitmproxy/mitmproxy:12.2.3

USER root
RUN pip install --no-cache-dir cryptography

# Create coherence directories
RUN mkdir -p /home/mitmproxy/.holon/cache /tmp/wire_logs /tmp/src

# Copy package source
COPY src/ /tmp/src/
ENV PYTHONPATH="/tmp/src"

USER mitmproxy
WORKDIR /home/mitmproxy

EXPOSE 8080 8081

ENTRYPOINT ["mitmdump", "-s", "/tmp/src/holon_coherence/mitm_addon.py", "--listen-port", "8080"]
