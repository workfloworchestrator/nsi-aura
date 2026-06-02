# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:1f87b756502d24b70a85be412305373ede43765538a1534232bb300fb3aadf7f AS build
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.md ./
COPY aura aura
COPY static static
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:1f87b756502d24b70a85be412305373ede43765538a1534232bb300fb3aadf7f
COPY --from=build /app/dist/*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/*.whl && rm /tmp/*.whl
RUN addgroup -g 1000 aura && adduser -D -u 1000 -G aura aura
USER aura
WORKDIR /home/aura
EXPOSE 8080/tcp
ENV STATIC_DIRECTORY=/usr/local/share/aura/static
CMD ["nsi-aura"]
