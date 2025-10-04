FROM        python:3.13.7-alpine@sha256:9ba6d8cbebf0fb6546ae71f2a1c14f6ffd2fdab83af7fa5669734ef30ad48844

# renovate: datasource=repology depName=alpine_3_22/gcc versioning=loose
ARG         GCC_VERSION="14.2.0-r6"
# renovate: datasource=repology depName=alpine_3_22/libsndfile versioning=loose
ARG         LIBSNDFILE_VERSION="1.2.2-r2"
# renovate: datasource=repology depName=alpine_3_22/llvm20 versioning=loose
ARG         LLVM_VERSION="20.1.8-r0"
# renovate: datasource=repology depName=alpine_3_22/ffmpeg versioning=loose
ARG         FFMPEG_VERSION="6.1.2-r2"
# renovate: datasource=repology depName=alpine_3_22/bash versioning=loose
ARG         BASH_VERSION="5.2.37-r0"
# renovate: datasource=repology depName=alpine_3_22/git versioning=loose
ARG         GIT_VERSION="2.49.1-r0"
# renovate: datasource=repology depName=alpine_3_22/build-base versioning=loose
ARG         BUILD_BASE_VERSION="0.5-r3"
# renovate: datasource=repology depName=alpine_3_22/cmake versioning=loose
ARG         CMAKE_VERSION="3.31.7-r1"
# renovate: datasource=repology depName=alpine_3_22/libffi-dev versioning=loose
ARG         LIBFFI_VERSION="3.4.8-r0"
# renovate: datasource=repology depName=alpine_3_22/libretls-dev versioning=loose
ARG         LIBRETLS_VERSION="3.7.0-r2"

ARG         TARGETPLATFORM

WORKDIR     /app

ADD         requirements.txt .

RUN         --mount=type=cache,sharing=locked,target=/root/.cache,id=home-cache-$TARGETPLATFORM \
            apk add --no-cache \
              libgcc=${GCC_VERSION} \
              libsndfile=${LIBSNDFILE_VERSION} \
              llvm20=${LLVM_VERSION} \
              llvm20-static=${LLVM_VERSION} \
              llvm20-gtest=${LLVM_VERSION} \
              ffmpeg=${FFMPEG_VERSION} \
              bash=${BASH_VERSION} \
            && \
            apk add --no-cache --virtual .build-deps \
              git=${GIT_VERSION} \
              gcc=${GCC_VERSION} \
              build-base=${BUILD_BASE_VERSION} \
              cmake=${CMAKE_VERSION} \
              llvm20-dev=${LLVM_VERSION} \
              libffi-dev=${LIBFFI_VERSION} \
              libretls-dev=${LIBRETLS_VERSION} \
            && \
            pip install -r requirements.txt && \
            apk del .build-deps && \
            chown -R nobody:nogroup /app && \
            ln -s /usr/lib/libsndfile.so.1 /usr/lib/libsndfile.so

COPY        --chown=nobody:nogroup . .

USER        nobody

ENV         PYTHONUNBUFFERED="1"
ENV         NUMBA_CACHE_DIR="/tmp/numba"

ENTRYPOINT  [ "python", "dedup.py" ]
