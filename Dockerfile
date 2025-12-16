FROM        python:3.14.2-alpine@sha256:2a77c2640cc80f5506babd027c883abc55f04d44173fd52eeacea9d3b978e811

# renovate: datasource=repology depName=alpine_3_23/gcc versioning=loose
ARG         GCC_VERSION="15.2.0-r2"
# renovate: datasource=repology depName=alpine_3_23/libsndfile versioning=loose
ARG         LIBSNDFILE_VERSION="1.2.2-r2"
# renovate: datasource=repology depName=alpine_3_23/llvm20 versioning=loose
ARG         LLVM_VERSION="20.1.8-r0"
# renovate: datasource=repology depName=alpine_3_23/gstreamer versioning=loose
ARG         GSTREAMER_VERSION="1.26.3-r0"
# renovate: datasource=repology depName=alpine_3_23/git versioning=loose
ARG         GIT_VERSION="2.49.1-r0"
# renovate: datasource=repology depName=alpine_3_23/build-base versioning=loose
ARG         BUILD_BASE_VERSION="0.5-r3"
# renovate: datasource=repology depName=alpine_3_23/cairo-dev versioning=loose
ARG         CAIRO_VERSION="1.18.4-r0"
# renovate: datasource=repology depName=alpine_3_23/cmake versioning=loose
ARG         CMAKE_VERSION="3.31.7-r1"
# renovate: datasource=repology depName=alpine_3_23/libffi-dev versioning=loose
ARG         LIBFFI_VERSION="3.4.8-r0"
# renovate: datasource=repology depName=alpine_3_23/libretls-dev versioning=loose
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
