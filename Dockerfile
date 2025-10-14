# syntax=docker/dockerfile:1
#
# Build stage
FROM python:3.13-slim-trixie AS build
ENV PIP_ROOT_USER_ACTION=ignore
WORKDIR /app
RUN set -ex; apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip --no-cache-dir
RUN pip install build --no-cache-dir
COPY pyproject.toml LICENSE.txt README.md .
COPY aura aura
RUN python -m build --wheel --outdir dist

# Final stage
FROM python:3.13-slim-trixie
ENV PIP_ROOT_USER_ACTION=ignore
RUN set -ex; apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip --no-cache-dir
COPY --from=build /app/dist/*.whl /tmp/
RUN pip install /tmp/*.whl --no-cache-dir
RUN useradd aura
USER aura
WORKDIR /home/aura
COPY static static
COPY images images
EXPOSE 8080/tcp
CMD ["nsi-aura"]
