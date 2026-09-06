#ifndef FORTGYM_PROVIDER_NETWORK_SHARED_H
#define FORTGYM_PROVIDER_NETWORK_SHARED_H

#include <linux/types.h>

#define FORTGYM_IDENTITY_HEX_BYTES 64
#define FORTGYM_IDENTITY_BUFFER_BYTES 65
#define FORTGYM_EVIDENCE_SHA_BUFFER_BYTES 65

enum fortgym_network_hook {
    FORTGYM_HOOK_CONNECT4 = 1,
    FORTGYM_HOOK_CONNECT6 = 2,
    FORTGYM_HOOK_SENDMSG4 = 3,
    FORTGYM_HOOK_SENDMSG6 = 4,
};

enum fortgym_network_decision {
    FORTGYM_DECISION_DENY = 0,
    FORTGYM_DECISION_ALLOW = 1,
};

/* One exact policy is installed before any cgroup program is attached. */
struct fortgym_provider_policy {
    __u32 allowed_ipv4_be;
    __u32 poison_ipv4_be;
    __u16 allowed_port_be;
    __u16 poison_port_be;
    __u8 guard_attested;
    __u8 reserved;
    char identity_sha256[FORTGYM_IDENTITY_BUFFER_BYTES];
    char evidence_path_sha256[FORTGYM_EVIDENCE_SHA_BUFFER_BYTES];
};

/* Kernel-originated fields only. The helper assigns contiguous JSON sequence. */
struct fortgym_provider_event {
    __u64 monotonic_ns;
    __u64 cgroup_id;
    __u32 pid;
    __u32 uid;
    __u32 destination_ipv4_be;
    __u8 destination_ipv6[16];
    __u16 destination_port_be;
    __u8 hook;
    __u8 family;
    __u8 protocol;
    __u8 decision;
    __s32 denied_errno;
    char identity_sha256[FORTGYM_IDENTITY_BUFFER_BYTES];
};

#endif
