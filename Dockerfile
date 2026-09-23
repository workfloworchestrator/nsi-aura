# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:2d6c7ad6f47a6c30da00d8dab6662964bce7decc339a84ba73ae6af62f9497b3 AS build
ARG VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NSI_AURA=${VERSION}
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.md ./
COPY aura aura
COPY static static
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:2d6c7ad6f47a6c30da00d8dab6662964bce7decc339a84ba73ae6af62f9497b3
COPY --from=build /app/dist/*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/*.whl && rm /tmp/*.whl
RUN addgroup -g 1000 aura && adduser -D -u 1000 -G aura aura
USER aura
WORKDIR /home/aura
EXPOSE 8080/tcp
ENV STATIC_DIRECTORY=/usr/local/share/aura/static
CMD ["nsi-aura"]
