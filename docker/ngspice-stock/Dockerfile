# Stock ngspice 47, without the BSIM4 stress-mobility fix, for the "Simulator" row of Table 5
# (option 1 handout, section 5.1): the same validation with the stock build. Same source and
# configure options as the course image (given container/Dockerfile), minus the patch.
#   docker build -t dd2-ngspice-stock docker/ngspice-stock
# Never use it for anything but that comparison (AGENTS.md: use the container's fixed ngspice).
FROM ubuntu:24.04

ARG NGSPICE_VERSION=47

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl autoconf automake libtool bison flex \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sL https://codeload.github.com/imr/ngspice/tar.gz/refs/tags/ngspice-${NGSPICE_VERSION} | tar xz -C /tmp \
    && cd /tmp/ngspice-ngspice-${NGSPICE_VERSION} \
    && ./autogen.sh && mkdir build && cd build \
    && ../configure --with-x=no --with-readline=no --disable-debug \
    && make -j"$(nproc)" && make install \
    && rm -rf /tmp/ngspice-ngspice-${NGSPICE_VERSION}

WORKDIR /work
