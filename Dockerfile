# LAMA CARAVAN controller — admin UI (:7990) + proxy router in one container.
#
# This image is the fleet's ENTRY DOOR, not its muscle: it serves the board,
# the config editor and the agent proxies. Models run on GPU hosts you attach
# with caravan-scout (github.com/thepr0metheus/caravan-scout), as on a native
# install: the controller runs no cells itself.
#
#   docker compose up -d          # see docker-compose.yml
#
# The app is stdlib-only Python — no pip install layer at all.
FROM python:3.12-slim

# Baked commit for the version chip (the image ships without .git):
#   docker build --build-arg CARAVAN_GIT_HEAD=$(git rev-parse --short HEAD) .
ARG CARAVAN_GIT_HEAD=""
ENV CARAVAN_CONTAINER=1 \
    CARAVAN_DATA_DIR=/data \
    CARAVAN_GIT_HEAD=${CARAVAN_GIT_HEAD} \
    PYTHONUNBUFFERED=1

# Zone data: TZ names the controller's time zone (docker-compose.yml). Without
# the data the C library takes any zone name for UTC without a word, and the
# start-up check refuses to run (caravan/common/container_preflight.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 caravan \
    && mkdir -p /data && chown caravan:caravan /data

WORKDIR /app
COPY --chown=caravan:caravan app.py agent-proxies.py ./
COPY --chown=caravan:caravan caravan/ caravan/
COPY --chown=caravan:caravan static/ static/
# The cell servers the controller hands to the scouts (/api/cell-assets).
COPY --chown=caravan:caravan cells/ cells/

USER caravan
# All state lives here — bind it or use a named volume (docker-compose.yml does).
VOLUME /data
# Admin UI. Proxy route ports are dynamic — run with network_mode: host.
EXPOSE 7990

# /api/auth/me is public even with auth enabled — cheap liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request,sys;port=os.environ.get('LLAMACPP_ADMIN_PORT','7990');sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/api/auth/me',timeout=4).status==200 else 1)"]

CMD ["python", "app.py"]
