FROM        python:3.14.6-alpine@sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92

# renovate: datasource=repology depName=alpine_3_24/gcc versioning=loose
ARG         GCC_VERSION="15.2.0-r5"
# renovate: datasource=repology depName=alpine_3_24/libsndfile versioning=loose
ARG         LIBSNDFILE_VERSION="1.2.2-r2"
# renovate: datasource=repology depName=alpine_3_24/llvm20 versioning=loose
ARG         LLVM_VERSION="20.1.8-r1"
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

STOPSIGNAL  SIGINT

ENTRYPOINT  [ "python", "dedup.py" ]
