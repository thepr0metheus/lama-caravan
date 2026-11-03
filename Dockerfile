# LAMA CARAVAN controller: the board and the entry for keys, built from this tree, with the scout it hands out.
#
# This image is the fleet's entry door, not its muscle: the controller runs no cells. Models run on machines with
# a scout, the controller's own machine included, and ＋ Add scout on the board gives the one command that installs it.
#
#   docker compose up -d --build          # see docker-compose.yml
FROM rust:1.99.1-slim-bookworm AS build

# The commit, for the board's word on what runs and for telling a scout that a newer one came. The image has no .git:
#   docker build --build-arg CARAVAN_GIT_HEAD=$(git rev-parse --short HEAD) .
# Without it the board says it does not know, and the scout it hands out says it was built from source.
ARG CARAVAN_GIT_HEAD=""

RUN apt-get update \
    && apt-get install -y --no-install-recommends musl-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/rust
COPY rust/ ./
# The scout links statically, so that it runs on any Linux machine on x86_64, whatever C library it has.
RUN rustup target add x86_64-unknown-linux-musl
ENV CC_x86_64_unknown_linux_musl=musl-gcc
RUN export CARAVAN_BUILD_COMMIT="${CARAVAN_GIT_HEAD:-source}" \
    && cargo build --locked --release -p admin -p proxy \
    && cargo build --locked --release --target x86_64-unknown-linux-musl -p scout

# What a machine takes: the program and its scripts in one file, and a second file that says what the first one is.
RUN mkdir /bundle \
    && tar -czf /bundle/scout-bundle.tar.gz -C /src/rust/crates/scout scripts -C /src/rust/target/x86_64-unknown-linux-musl/release caravan-scout \
    && printf '{"commit": "%s", "sha256": "%s", "bytes": %s}' "${CARAVAN_GIT_HEAD:-source}" \
        "$(sha256sum /bundle/scout-bundle.tar.gz | cut -d' ' -f1)" "$(wc -c < /bundle/scout-bundle.tar.gz)" > /bundle/scout-bundle.json


FROM debian:bookworm-slim

ARG CARAVAN_GIT_HEAD=""

# The zone's data, for TZ; the roots a provider's certificate is checked against. The upgrade first: the base image is
# rebuilt less often than Debian's fixes come out. GET /api/packages shows what came.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 caravan \
    && mkdir -p /data && chown caravan:caravan /data

ENV CARAVAN_CONTAINER=1 \
    CARAVAN_DATA_DIR=/data \
    CARAVAN_ROOT=/app/release \
    CARAVAN_GIT_HEAD=${CARAVAN_GIT_HEAD}

# A release is one folder: the programs, the board's files, the cell servers it hands to the scouts, the scout itself.
WORKDIR /app/release
COPY --from=build /src/rust/target/release/caravan-admin ./
COPY --from=build /src/rust/target/release/caravan-proxy bin/
COPY --from=build /bundle/ ./
COPY static/ static/
COPY cells/ cells/
COPY VERSION ./

USER caravan
# All state lives here: settings, accounts, journals, downloaded models. Bind it or use a named volume (docker-compose.yml does).
VOLUME /data
# The board, and the entry for keys. An entry moved to another port on the board needs that port published.
EXPOSE 7990 23999

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["/app/release/caravan-admin", "--health"]

CMD ["/app/release/caravan-admin"]
