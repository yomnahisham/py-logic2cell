# Yosys 0.33, the version the option 2 handout's Table 1 was measured with (Ubuntu 24.04 package)
FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends yosys \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
