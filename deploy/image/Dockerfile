# Agent Arena: one image for every API-serving peer and the test broker. Built by deploy/build.sh (not by compose).
# The command picks what runs: docker run agent-arena:latest arena.peers.link_peer
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY arena ./arena
COPY connectivity ./connectivity
# keys, ledgers and state live in /app/data (a volume); the process does not run as root
RUN useradd --create-home --uid 10001 arena && mkdir -p /app/data && chown arena:arena /app/data
USER arena
VOLUME ["/app/data"]
ENTRYPOINT ["python", "-m"]
CMD ["arena.peers.link_peer"]
