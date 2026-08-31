# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:8c0e83800e2974a030fb9ac9f499d9b55c8d974b75c6395b807b25efebfc048a AS build
ARG VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NSI_AURA=${VERSION}
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.md ./
COPY aura aura
COPY static static
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:8c0e83800e2974a030fb9ac9f499d9b55c8d974b75c6395b807b25efebfc048a
COPY --from=build /app/dist/*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/*.whl && rm /tmp/*.whl
RUN addgroup -g 1000 aura && adduser -D -u 1000 -G aura aura
USER aura
WORKDIR /home/aura
EXPOSE 8080/tcp
ENV STATIC_DIRECTORY=/usr/local/share/aura/static
CMD ["nsi-aura"]
