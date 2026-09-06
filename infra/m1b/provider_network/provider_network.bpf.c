// SPDX-License-Identifier: GPL-2.0-only

#include <linux/bpf.h>
#include <linux/errno.h>
#include <linux/in.h>
#include <linux/in6.h>
#include <linux/socket.h>
#include <stdbool.h>

#include <bpf/bpf_endian.h>
#include <bpf/bpf_helpers.h>

#include "provider_network_shared.h"

#ifndef AF_INET
#define AF_INET 2
#endif

char LICENSE[] SEC("license") = "GPL";

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, struct fortgym_provider_policy);
} policy SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u64);
} lost_events SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 22);
} events SEC(".maps");

static __always_inline void note_lost_event(void)
{
    __u32 key = 0;
    __u64 *counter = bpf_map_lookup_elem(&lost_events, &key);

    if (counter != 0)
        __sync_fetch_and_add(counter, 1);
}

static __always_inline int observe_and_decide(struct bpf_sock_addr *ctx,
                                              __u8 hook)
{
    __u32 key = 0;
    struct fortgym_provider_policy *configured;
    struct fortgym_provider_event *event;
    bool allowed = false;

    configured = bpf_map_lookup_elem(&policy, &key);
    if (configured != 0 && hook == FORTGYM_HOOK_CONNECT4 &&
        ctx->user_family == AF_INET && ctx->protocol == IPPROTO_TCP &&
        ctx->user_ip4 == configured->allowed_ipv4_be &&
        (__u16)ctx->user_port == configured->allowed_port_be) {
        allowed = true;
    }

    event = bpf_ringbuf_reserve(&events, sizeof(*event), 0);
    if (event == 0) {
        note_lost_event();
        return allowed ? 1 : 0;
    }

    __builtin_memset(event, 0, sizeof(*event));
    event->monotonic_ns = bpf_ktime_get_ns();
    event->cgroup_id = bpf_get_current_cgroup_id();
    event->pid = (__u32)(bpf_get_current_pid_tgid() >> 32);
    event->uid = (__u32)bpf_get_current_uid_gid();
    if (hook == FORTGYM_HOOK_CONNECT4 || hook == FORTGYM_HOOK_SENDMSG4) {
        event->destination_ipv4_be = ctx->user_ip4;
    } else {
        __builtin_memcpy(event->destination_ipv6, ctx->user_ip6,
                         sizeof(event->destination_ipv6));
    }
    event->destination_port_be = (__u16)ctx->user_port;
    event->hook = hook;
    event->family = (__u8)ctx->user_family;
    event->protocol = (__u8)ctx->protocol;
    event->decision = allowed ? FORTGYM_DECISION_ALLOW : FORTGYM_DECISION_DENY;
    event->denied_errno = allowed ? 0 : EPERM;
    if (configured != 0) {
        __builtin_memcpy(event->identity_sha256, configured->identity_sha256,
                         sizeof(event->identity_sha256));
    }
    bpf_ringbuf_submit(event, 0);
    return allowed ? 1 : 0;
}

SEC("cgroup/connect4")
int fortgym_connect4(struct bpf_sock_addr *ctx)
{
    return observe_and_decide(ctx, FORTGYM_HOOK_CONNECT4);
}

SEC("cgroup/connect6")
int fortgym_connect6(struct bpf_sock_addr *ctx)
{
    return observe_and_decide(ctx, FORTGYM_HOOK_CONNECT6);
}

SEC("cgroup/sendmsg4")
int fortgym_sendmsg4(struct bpf_sock_addr *ctx)
{
    return observe_and_decide(ctx, FORTGYM_HOOK_SENDMSG4);
}

SEC("cgroup/sendmsg6")
int fortgym_sendmsg6(struct bpf_sock_addr *ctx)
{
    return observe_and_decide(ctx, FORTGYM_HOOK_SENDMSG6);
}
