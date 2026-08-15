FROM        python:3.14.7-alpine@sha256:05b2b8b732ecd268fee8727a369f936f022d1321b59befd13c30ede22769dcdc

# renovate: datasource=repology depName=alpine_3_24/gcc versioning=loose
ARG         GCC_VERSION="15.2.0-r5"
# renovate: datasource=repology depName=alpine_3_24/libsndfile versioning=loose
ARG         LIBSNDFILE_VERSION="1.2.2-r2"
# renovate: datasource=repology depName=alpine_3_24/llvm22 versioning=loose
ARG         LLVM_VERSION="22.1.3-r0"
# renovate: datasource=repology depName=alpine_3_24/gstreamer versioning=loose
ARG         GSTREAMER_VERSION="1.28.3-r0"
# renovate: datasource=repology depName=alpine_3_24/git versioning=loose
ARG         GIT_VERSION="2.54.0-r0"
# renovate: datasource=repology depName=alpine_3_24/build-base versioning=loose
ARG         BUILD_BASE_VERSION="0.5-r4"
# renovate: datasource=repology depName=alpine_3_24/cairo-dev versioning=loose
ARG         CAIRO_VERSION="1.18.4-r1"
# renovate: datasource=repology depName=alpine_3_24/cmake versioning=loose
ARG         CMAKE_VERSION="4.2.3-r0"
# renovate: datasource=repology depName=alpine_3_24/libffi-dev versioning=loose
ARG         LIBFFI_VERSION="3.5.2-r1"
# renovate: datasource=repology depName=alpine_3_24/libretls-dev versioning=loose
ARG         LIBRETLS_VERSION="3.8.1-r0"

ARG         TARGETPLATFORM
ARG         CXX="g++"

WORKDIR     /app

ADD         requirements.txt .

RUN         --mount=type=cache,sharing=locked,target=/root/.cache,id=home-cache-$TARGETPLATFORM \
            apk add --no-cache \
              libgcc=${GCC_VERSION} \
              libsndfile=${LIBSNDFILE_VERSION} \
              llvm22=${LLVM_VERSION} \
              llvm22-static=${LLVM_VERSION} \
              llvm22-gtest=${LLVM_VERSION} \
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
              llvm22-dev=${LLVM_VERSION} \
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

STOPSIGNAL  SIGINT

ENTRYPOINT  [ "python", "dedup.py" ]
