ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG DF_ARCHIVE_SHA256
ARG DFHACK_ARCHIVE_SHA256

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        binutils \
        bzip2 \
        ca-certificates \
        jq \
        libcaca0 \
        libglu1-mesa \
        libgtk2.0-0 \
        libncurses5 \
        libncursesw5 \
        libpulse0 \
        libsdl-image1.2 \
        libsdl-ttf2.0-0 \
        libsdl1.2debian \
        libslang2 \
        libxcursor1 \
        libxi6 \
        libxrandr2 \
        libxrender1 \
        procps \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY infra/m1a/_inputs/df_47_05_linux.tar.bz2 /tmp/df_47_05_linux.tar.bz2
COPY infra/m1a/_inputs/dfhack-0.47.05-r8-Linux-64bit-gcc-7.tar.bz2 /tmp/dfhack.tar.bz2

RUN test -n "${DF_ARCHIVE_SHA256}" \
    && test -n "${DFHACK_ARCHIVE_SHA256}" \
    && echo "${DF_ARCHIVE_SHA256}  /tmp/df_47_05_linux.tar.bz2" | sha256sum -c - \
    && echo "${DFHACK_ARCHIVE_SHA256}  /tmp/dfhack.tar.bz2" | sha256sum -c - \
    && mkdir -p /opt/dwarf-fortress \
    && tar -xjf /tmp/df_47_05_linux.tar.bz2 -C /tmp \
    && cp -a /tmp/df_linux/. /opt/dwarf-fortress/ \
    && tar -xjf /tmp/dfhack.tar.bz2 -C /opt/dwarf-fortress \
    && rm -rf /tmp/df_linux /tmp/df_47_05_linux.tar.bz2 /tmp/dfhack.tar.bz2

COPY infra/m1a/_inputs/seed_region3_fresh /opt/seed_saves/seed_region3_fresh
COPY hook /opt/fort-gym-m1a/hook
COPY infra/m1a/entrypoint.sh /usr/local/bin/fortgym-m1a-entrypoint

RUN groupadd --gid 1000 dfh \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash dfh \
    && mkdir -p /run/fortgym /opt/dwarf-fortress/data/save \
    && chmod 0755 /usr/local/bin/fortgym-m1a-entrypoint \
    && chown -R dfh:dfh /opt/dwarf-fortress /opt/seed_saves /run/fortgym \
    && sed -i \
        -e 's/\[PRINT_MODE:[^]]*\]/[PRINT_MODE:TEXT]/' \
        -e 's/\[SOUND:[^]]*\]/[SOUND:NO]/' \
        -e 's/\[INTRO:[^]]*\]/[INTRO:NO]/' \
        -e 's/\[FPS_CAP:[^]]*\]/[FPS_CAP:100]/' \
        /opt/dwarf-fortress/data/init/init.txt

LABEL org.opencontainers.image.title="Fort-Gym M1a DF runtime" \
      org.opencontainers.image.version="df-0.47.05_dfhack-0.47.05-r8" \
      org.opencontainers.image.description="Private ephemeral feasibility image; no publication authorization"

USER dfh
WORKDIR /opt/dwarf-fortress
ENTRYPOINT ["/usr/local/bin/fortgym-m1a-entrypoint"]
