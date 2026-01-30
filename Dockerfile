FROM        python:3.14.2-alpine@sha256:31da4cb527055e4e3d7e9e006dffe9329f84ebea79eaca0a1f1c27ce61e40ca5

# renovate: datasource=repology depName=alpine_3_23/gcc versioning=loose
ARG         GCC_VERSION="15.2.0-r2"
# renovate: datasource=repology depName=alpine_3_23/libsndfile versioning=loose
ARG         LIBSNDFILE_VERSION="1.2.2-r2"
# renovate: datasource=repology depName=alpine_3_23/llvm20 versioning=loose
ARG         LLVM_VERSION="20.1.8-r0"
# renovate: datasource=repology depName=alpine_3_23/gstreamer versioning=loose
ARG         GSTREAMER_VERSION="1.26.9-r0"
# renovate: datasource=repology depName=alpine_3_23/git versioning=loose
ARG         GIT_VERSION="2.52.0-r0"
# renovate: datasource=repology depName=alpine_3_23/build-base versioning=loose
ARG         BUILD_BASE_VERSION="0.5-r3"
# renovate: datasource=repology depName=alpine_3_23/cairo-dev versioning=loose
ARG         CAIRO_VERSION="1.18.4-r0"
# renovate: datasource=repology depName=alpine_3_23/cmake versioning=loose
ARG         CMAKE_VERSION="4.1.3-r0"
# renovate: datasource=repology depName=alpine_3_23/libffi-dev versioning=loose
ARG         LIBFFI_VERSION="3.5.2-r0"
# renovate: datasource=repology depName=alpine_3_23/libretls-dev versioning=loose
ARG         LIBRETLS_VERSION="3.8.1-r0"

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
              gstreamer=${GSTREAMER_VERSION} \
              gst-plugins-base=${GSTREAMER_VERSION} \
              gst-plugins-good=${GSTREAMER_VERSION} \
            && \
            apk add --no-cache --virtual .build-deps \
              git=${GIT_VERSION} \
              gcc=${GCC_VERSION} \
              build-base=${BUILD_BASE_VERSION} \
              cairo-dev=${CAIRO_VERSION} \
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

ENV         PYTHONUNBUFFERED=1
ENV         NUMBA_CACHE_DIR=/tmp/numba

ENTRYPOINT  [ "python", "dedup.py" ]
