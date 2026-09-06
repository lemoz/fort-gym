SHELL := /bin/sh

CC ?= cc
CLANG ?= clang
LLVM_STRIP ?= llvm-strip
PKG_CONFIG ?= pkg-config
SHA256SUM ?= sha256sum
SOURCE_DATE_EPOCH ?= 1723766400
BUILD_DIR ?= build
MULTIARCH ?= $(shell $(CC) -dumpmachine)

SAFE_BUILD_DIRS := build build-repro-a build-repro-b
ifneq ($(words $(BUILD_DIR)),1)
$(error BUILD_DIR must be one exact safe build basename)
endif
ifeq ($(filter $(SAFE_BUILD_DIRS),$(BUILD_DIR)),)
$(error BUILD_DIR must be one of: $(SAFE_BUILD_DIRS))
endif

ROOT := $(abspath .)
BPF_SOURCE := provider_network.bpf.c
HELPER_SOURCE := provider_network_helper.c
SHARED_HEADER := provider_network_shared.h
BPF_OBJECT := $(BUILD_DIR)/provider_network.bpf.o
HELPER_BINARY := $(BUILD_DIR)/fortgym-provider-network-helper

REPRO_FLAGS := -ffile-prefix-map=$(ROOT)=. -fdebug-prefix-map=$(ROOT)=. \
	-fmacro-prefix-map=$(ROOT)=. -fno-ident
BPF_CFLAGS := -target bpf -D__TARGET_ARCH_x86 -O2 -g -Wall -Wextra -Werror \
	$(REPRO_FLAGS) -I. -I/usr/include/$(MULTIARCH)
HELPER_CFLAGS := -O2 -g0 -std=c17 -Wall -Wextra -Werror -Wformat=2 \
	-Wconversion -Wshadow -Wstrict-prototypes -fstack-protector-strong \
	-D_FORTIFY_SOURCE=3 -fPIE $(REPRO_FLAGS) \
	$(shell $(PKG_CONFIG) --cflags libbpf libcrypto 2>/dev/null)
HELPER_LDFLAGS := -Wl,-z,relro,-z,now,-z,noexecstack -pie
HELPER_LIBS := $(shell $(PKG_CONFIG) --libs libbpf libcrypto 2>/dev/null)

.PHONY: all clean hashes repro-check static-contract toolchain-report

all: $(BPF_OBJECT) $(HELPER_BINARY) hashes

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BPF_OBJECT): $(BPF_SOURCE) $(SHARED_HEADER) | $(BUILD_DIR)
	SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH) $(CLANG) $(BPF_CFLAGS) -c $< -o $@
	$(LLVM_STRIP) -g $@

$(HELPER_BINARY): $(HELPER_SOURCE) $(SHARED_HEADER) | $(BUILD_DIR)
	SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH) $(CC) $(HELPER_CFLAGS) $< \
		$(HELPER_LDFLAGS) $(HELPER_LIBS) -o $@
	$(LLVM_STRIP) --strip-all $@

hashes: $(BPF_OBJECT) $(HELPER_BINARY)
	LC_ALL=C $(SHA256SUM) $(BPF_OBJECT) $(HELPER_BINARY) > $(BUILD_DIR)/SHA256SUMS

static-contract:
	LC_ALL=C grep -F 'SEC("cgroup/connect4")' $(BPF_SOURCE)
	LC_ALL=C grep -F 'SEC("cgroup/connect6")' $(BPF_SOURCE)
	LC_ALL=C grep -F 'SEC("cgroup/sendmsg4")' $(BPF_SOURCE)
	LC_ALL=C grep -F 'SEC("cgroup/sendmsg6")' $(BPF_SOURCE)
	LC_ALL=C grep -F 'execve(argv[11], &argv[11], environ)' $(HELPER_SOURCE)
	! grep -E '(^|[^A-Za-z])(system|popen)[[:space:]]*\(' $(HELPER_SOURCE)

toolchain-report:
	@uname -srm
	@$(CLANG) --version | sed -n '1p'
	@$(CC) --version | sed -n '1p'
	@$(LLVM_STRIP) --version | sed -n '1p'
	@$(PKG_CONFIG) --modversion libbpf libcrypto

repro-check: static-contract
	$(MAKE) BUILD_DIR=build-repro-a clean all
	$(MAKE) BUILD_DIR=build-repro-b clean all
	cmp build-repro-a/provider_network.bpf.o build-repro-b/provider_network.bpf.o
	cmp build-repro-a/fortgym-provider-network-helper \
		build-repro-b/fortgym-provider-network-helper
	LC_ALL=C $(SHA256SUM) build-repro-a/provider_network.bpf.o \
		build-repro-a/fortgym-provider-network-helper

clean:
	rm -rf -- $(BUILD_DIR)
