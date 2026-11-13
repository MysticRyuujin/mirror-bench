# syntax=docker/dockerfile:1.9

# ---- Build stage ---------------------------------------------------------
# Keep the uv and python versions synced with pyproject.toml / CI env.
ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.11.7

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
ARG VERSION=dev

# Minimal build deps; nothing compiled lands in the final image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

# Build the wheel, then install it into a self-contained venv under /opt/venv.
# Runtime deps come from uv.lock, so the image runs the same versions that CI
# tests; resolving at build time would pull whatever is newest that day.
# No dev deps, no sources, no uv binary in the final image.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv \
 && uv export --frozen --no-dev --no-emit-project --format requirements.txt \
      --output-file /tmp/requirements.txt \
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache --require-hashes \
      -r /tmp/requirements.txt \
 && uv build --wheel \
 && wheel=$(find dist -maxdepth 1 -name '*.whl' -print -quit) \
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache --no-deps "${wheel}"

# ---- Runtime stage -------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ARG VERSION=dev

LABEL org.opencontainers.image.title="mirror-bench" \
      org.opencontainers.image.description="Cross-distribution Linux package mirror benchmarking." \
      org.opencontainers.image.url="https://github.com/MysticRyuujin/mirror-bench" \
      org.opencontainers.image.source="https://github.com/MysticRyuujin/mirror-bench" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}"

# Install CA bundle and create the non-root user in a single layer.
# We deliberately do not pin ca-certificates: the whole point of this package
# is to ship the latest Debian-security-vetted CA list at build time. Pinning
# a specific version would freeze trust material and defeat the upgrade path.
# The runtime never installs anything, so pip goes too: its vendored copies of
# urllib3, msgpack, and setuptools are what image scanners report.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall --yes --no-cache-dir pip \
 && groupadd --system --gid 65532 app \
 && useradd --system --uid 65532 --gid app \
        --home-dir /home/app --create-home --shell /usr/sbin/nologin app

COPY --from=builder --chown=65532:65532 /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 65532:65532
WORKDIR /home/app

ENTRYPOINT ["mirror-bench"]
CMD ["--help"]
