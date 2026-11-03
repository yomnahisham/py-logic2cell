# OpenSTA, for the "Liberty syntax" and "Design level" rows of Table 5 (option 1 handout, section 5.1):
# load our Liberty, and time the SPM mapped onto a copy of the HD Liberty.
#   docker build -t dd2-opensta docker/opensta
# Pinned to the commit Table 5 was run with (sta -version: 3.1.0); /opensta.commit records it in the image.
FROM ubuntu:24.04

ARG OPENSTA_COMMIT=f2f431abf02a409f3e46aa8d95557353ef6f6a3a

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential ca-certificates git cmake autoconf automake libtool tcl-dev swig bison flex \
      libeigen3-dev zlib1g-dev libgtest-dev libfl-dev \
    && rm -rf /var/lib/apt/lists/*

# CUDD, which OpenSTA needs for its BDDs
RUN git clone --depth 1 https://github.com/ivmai/cudd.git /tmp/cudd && cd /tmp/cudd \
    && autoreconf -fi && ./configure --prefix=/usr/local && make -j"$(nproc)" && make install \
    && rm -rf /tmp/cudd

RUN git clone https://github.com/The-OpenROAD-Project/OpenSTA.git /tmp/OpenSTA && cd /tmp/OpenSTA \
    && git checkout ${OPENSTA_COMMIT} && git rev-parse HEAD > /opensta.commit \
    && mkdir build && cd build && cmake .. -DCUDD_DIR=/usr/local && make -j"$(nproc)" && make install \
    && rm -rf /tmp/OpenSTA

WORKDIR /work
