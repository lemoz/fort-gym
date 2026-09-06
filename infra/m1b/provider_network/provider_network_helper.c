// SPDX-License-Identifier: Apache-2.0

#define _GNU_SOURCE

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <limits.h>
#include <linux/magic.h>
#include <netinet/in.h>
#include <openssl/evp.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <unistd.h>

#include <bpf/bpf.h>
#include <bpf/libbpf.h>

#include "provider_network_shared.h"

extern char **environ;

#define FORTGYM_CGROUP_ROOT "/sys/fs/cgroup/fortgym-provider-net"
#define FORTGYM_BPFFS_ROOT "/sys/fs/bpf/fortgym-provider-net"
#define FORTGYM_MAX_MEMBERS 1024
#define FORTGYM_MAX_EVENTS 4096
#define FORTGYM_MAX_GUARD_BYTES 2048
#define FORTGYM_BPF_LOG_BYTES 65536

#define CAPABILITY_SCHEMA "fortgym.provider-network-capabilities/v1"
#define PREPARE_SCHEMA "fortgym.provider-network-prepare/v1"
#define INSPECT_SCHEMA "fortgym.provider-network-inspect/v1"
#define SNAPSHOT_SCHEMA "fortgym.provider-network-capture/v1"
#define CLEANUP_SCHEMA "fortgym.provider-network-cleanup/v1"
#define GUARD_SCHEMA "fortgym.python-network-guard-attestation/v1"
#define NEGATIVE_DNS_IPV4 "198.51.100.53"
#define NEGATIVE_HTTPS_IPV4 "198.51.100.10"

static const char *const required_programs[] = {
    "fortgym_connect4",
    "fortgym_connect6",
    "fortgym_sendmsg4",
    "fortgym_sendmsg6",
};

static const char *const pinned_links[] = {
    "link-connect4",
    "link-connect6",
    "link-sendmsg4",
    "link-sendmsg6",
};

static const char *const pinned_maps[] = {
    "policy",
    "lost_events",
    "events",
};

struct captured_events {
    struct fortgym_provider_event items[FORTGYM_MAX_EVENTS];
    size_t count;
    uint64_t userspace_lost;
};

static char bpf_kernel_log[FORTGYM_BPF_LOG_BYTES];

static int fail_closed(const char *message)
{
    fprintf(stderr, "fortgym-provider-network-helper: %s\n", message);
    return 70;
}

static bool is_lower_hex_sha256(const char *value)
{
    size_t index;

    if (value == NULL || strlen(value) != FORTGYM_IDENTITY_HEX_BYTES)
        return false;
    for (index = 0; index < FORTGYM_IDENTITY_HEX_BYTES; ++index) {
        if (!((value[index] >= '0' && value[index] <= '9') ||
              (value[index] >= 'a' && value[index] <= 'f')))
            return false;
    }
    return true;
}

static bool is_safe_component(const char *value)
{
    size_t index;

    if (value == NULL || value[0] == '\0' || strlen(value) > 220)
        return false;
    for (index = 0; value[index] != '\0'; ++index) {
        const char character = value[index];
        if (!((character >= 'a' && character <= 'z') ||
              (character >= 'A' && character <= 'Z') ||
              (character >= '0' && character <= '9') || character == '.' ||
              character == '_' || character == '-'))
            return false;
    }
    return strcmp(value, ".") != 0 && strcmp(value, "..") != 0;
}

static bool is_direct_child(const char *path, const char *root)
{
    const size_t root_length = strlen(root);
    const char *component;

    if (path == NULL || strncmp(path, root, root_length) != 0 ||
        path[root_length] != '/')
        return false;
    component = path + root_length + 1;
    return strchr(component, '/') == NULL && is_safe_component(component);
}

static bool resource_component_matches_identity(const char *cgroup_path,
                                                const char *pin_root,
                                                const char *identity)
{
    const char *cgroup_component = strrchr(cgroup_path, '/');
    const char *pin_component = strrchr(pin_root, '/');
    size_t length;

    if (cgroup_component == NULL || pin_component == NULL)
        return false;
    ++cgroup_component;
    ++pin_component;
    length = strlen(cgroup_component);
    return strcmp(cgroup_component, pin_component) == 0 && length >= 18 &&
           cgroup_component[length - 17] == '-' &&
           strncmp(cgroup_component + length - 16, identity, 16) == 0;
}

static bool is_absolute_clean_path(const char *path)
{
    const size_t length = path == NULL ? 0 : strlen(path);

    if (path == NULL || path[0] != '/' || length == 0 || length >= PATH_MAX)
        return false;
    return strstr(path, "/../") == NULL && strstr(path, "/./") == NULL &&
           !(length >= 3 && strcmp(path + length - 3, "/..") == 0) &&
           !(length >= 2 && strcmp(path + length - 2, "/.") == 0);
}

static int require_privileged_helper(void)
{
    struct utsname identity;

    if (geteuid() != 0)
        return fail_closed("privileged helper capability is absent");
    if (uname(&identity) != 0 || strcmp(identity.sysname, "Linux") != 0 ||
        strcmp(identity.machine, "x86_64") != 0)
        return fail_closed("host is not isolated x86_64 Linux");
    return 0;
}

static int require_secure_root(const char *root, long expected_magic)
{
    struct stat metadata;
    struct statfs filesystem;
    char canonical[PATH_MAX];

    if (realpath(root, canonical) == NULL || strcmp(canonical, root) != 0 ||
        lstat(root, &metadata) != 0 || !S_ISDIR(metadata.st_mode) ||
        metadata.st_uid != 0 || (metadata.st_mode & 0777) != 0700 ||
        statfs(root, &filesystem) != 0 || filesystem.f_type != expected_magic)
        return fail_closed("required root filesystem is absent or unsafe");
    return 0;
}

static int self_executable_path(char output[PATH_MAX])
{
    const ssize_t count = readlink("/proc/self/exe", output, PATH_MAX - 1);

    if (count <= 0 || count >= PATH_MAX - 1)
        return -1;
    output[count] = '\0';
    return is_absolute_clean_path(output) ? 0 : -1;
}

static int require_secure_artifact(const char *path, bool helper)
{
    struct stat metadata;

    if (!is_absolute_clean_path(path) || lstat(path, &metadata) != 0 ||
        !S_ISREG(metadata.st_mode) || S_ISLNK(metadata.st_mode) ||
        metadata.st_uid != 0 || (metadata.st_mode & (S_IWGRP | S_IWOTH)) != 0)
        return -1;
    if (helper) {
        if ((metadata.st_mode & (S_ISUID | 0777)) != (S_ISUID | 0750) ||
            (metadata.st_mode & S_ISGID) != 0)
            return -1;
    } else if ((metadata.st_mode & (S_ISUID | S_ISGID)) != 0) {
        return -1;
    }
    return 0;
}

static int require_host_layout(void)
{
    if (access("/sys/fs/cgroup/cgroup.controllers", R_OK) != 0)
        return fail_closed("cgroup v2 is unavailable");
    if (require_secure_root(FORTGYM_CGROUP_ROOT, CGROUP2_SUPER_MAGIC) != 0)
        return 70;
    if (require_secure_root(FORTGYM_BPFFS_ROOT, BPF_FS_MAGIC) != 0)
        return 70;
    return 0;
}

static int sha256_file(const char *path, char output[65])
{
    unsigned char buffer[65536];
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_length = 0;
    EVP_MD_CTX *context = NULL;
    FILE *stream = NULL;
    size_t count;
    size_t index;
    int result = -1;

    context = EVP_MD_CTX_new();
    stream = fopen(path, "rb");
    if (context == NULL || stream == NULL ||
        EVP_DigestInit_ex(context, EVP_sha256(), NULL) != 1)
        goto done;
    while ((count = fread(buffer, 1, sizeof(buffer), stream)) != 0) {
        if (EVP_DigestUpdate(context, buffer, count) != 1)
            goto done;
    }
    if (ferror(stream) || EVP_DigestFinal_ex(context, digest, &digest_length) != 1 ||
        digest_length != 32)
        goto done;
    for (index = 0; index < digest_length; ++index)
        snprintf(output + (index * 2), 3, "%02x", digest[index]);
    output[64] = '\0';
    result = 0;

done:
    if (stream != NULL)
        fclose(stream);
    EVP_MD_CTX_free(context);
    return result;
}

static int sha256_text(const char *value, char output[65])
{
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_length = 0;
    size_t index;

    if (EVP_Digest(value, strlen(value), digest, &digest_length, EVP_sha256(), NULL) !=
            1 ||
        digest_length != 32)
        return -1;
    for (index = 0; index < digest_length; ++index)
        snprintf(output + (index * 2), 3, "%02x", digest[index]);
    output[64] = '\0';
    return 0;
}

static void print_json_string(const char *value)
{
    const unsigned char *cursor = (const unsigned char *)value;

    putchar('"');
    while (*cursor != '\0') {
        if (*cursor == '"' || *cursor == '\\') {
            putchar('\\');
            putchar((int)*cursor);
        } else if (*cursor < 0x20) {
            printf("\\u%04x", (unsigned int)*cursor);
        } else {
            putchar((int)*cursor);
        }
        ++cursor;
    }
    putchar('"');
}

static void print_hooks(void)
{
    fputs("[\"connect4\",\"connect6\",\"sendmsg4\",\"sendmsg6\"]", stdout);
}

static void print_policy(unsigned int port)
{
    fputs("{\"mode\":\"cgroup_bpf_default_deny\",\"hooks\":", stdout);
    print_hooks();
    fputs(",\"allow\":{\"hook\":\"connect4\",\"family\":\"AF_INET\","
          "\"protocol\":\"tcp\",\"host\":\"127.0.0.1\",\"port\":",
          stdout);
    printf("%u", port);
    fputs("},\"deny\":{\"connect4_nonmatching\":true,\"connect6\":true,"
          "\"sendmsg4\":true,\"sendmsg6\":true}}",
          stdout);
}

static int parse_loopback_endpoint(const char *value, unsigned int *port)
{
    const char *prefix = "127.0.0.1:";
    char *end = NULL;
    unsigned long parsed;

    if (strncmp(value, prefix, strlen(prefix)) != 0)
        return -1;
    errno = 0;
    parsed = strtoul(value + strlen(prefix), &end, 10);
    if (errno != 0 || end == value + strlen(prefix) || *end != '\0' || parsed == 0 ||
        parsed > 65535 || parsed == 53 || parsed == 443)
        return -1;
    *port = (unsigned int)parsed;
    return 0;
}

static int parse_nonloopback_ipv4_endpoint(const char *value, uint32_t *address_be,
                                           uint16_t *port_be)
{
    char host[INET_ADDRSTRLEN];
    const char *separator = strrchr(value, ':');
    char *end = NULL;
    size_t host_length;
    unsigned long parsed_port;

    if (separator == NULL || separator == value)
        return -1;
    host_length = (size_t)(separator - value);
    if (host_length >= sizeof(host))
        return -1;
    memcpy(host, value, host_length);
    host[host_length] = '\0';
    errno = 0;
    parsed_port = strtoul(separator + 1, &end, 10);
    if (errno != 0 || end == separator + 1 || *end != '\0' || parsed_port == 0 ||
        parsed_port > 65535 || inet_pton(AF_INET, host, address_be) != 1 ||
        *address_be == htonl(INADDR_LOOPBACK) ||
        (strcmp(host, NEGATIVE_DNS_IPV4) == 0 && parsed_port == 53) ||
        (strcmp(host, NEGATIVE_HTTPS_IPV4) == 0 && parsed_port == 443))
        return -1;
    *port_be = htons((uint16_t)parsed_port);
    return 0;
}

static int set_memlock_limit(void)
{
    const struct rlimit unlimited = {RLIM_INFINITY, RLIM_INFINITY};

    return setrlimit(RLIMIT_MEMLOCK, &unlimited);
}

static int verify_bpf_object_contract(const char *object_path, bool load)
{
    struct bpf_object *object;
    struct bpf_object_open_opts open_options = {
        .sz = sizeof(struct bpf_object_open_opts),
        .kernel_log_buf = bpf_kernel_log,
        .kernel_log_size = sizeof(bpf_kernel_log),
        .kernel_log_level = 1,
    };
    struct bpf_program *program;
    struct bpf_map *map;
    long open_error;
    size_t index;
    int load_error;
    int saved_errno;
    int result = -1;

    memset(bpf_kernel_log, 0, sizeof(bpf_kernel_log));
    object = bpf_object__open_file(object_path, &open_options);
    open_error = libbpf_get_error(object);
    if (open_error != 0) {
        fprintf(stderr, "fortgym-provider-network-helper: BPF object open failed: %ld\n",
                open_error);
        return -1;
    }
    for (index = 0; index < sizeof(required_programs) / sizeof(required_programs[0]);
         ++index) {
        program = bpf_object__find_program_by_name(object, required_programs[index]);
        if (program == NULL) {
            fprintf(stderr,
                    "fortgym-provider-network-helper: required BPF program is absent: %s\n",
                    required_programs[index]);
            goto done;
        }
    }
    for (index = 0; index < sizeof(pinned_maps) / sizeof(pinned_maps[0]); ++index) {
        map = bpf_object__find_map_by_name(object, pinned_maps[index]);
        if (map == NULL) {
            fprintf(stderr,
                    "fortgym-provider-network-helper: required BPF map is absent: %s\n",
                    pinned_maps[index]);
            goto done;
        }
    }
    if (load) {
        errno = 0;
        load_error = bpf_object__load(object);
        saved_errno = errno;
        if (load_error != 0) {
            bpf_kernel_log[sizeof(bpf_kernel_log) - 1] = '\0';
            fprintf(stderr,
                    "fortgym-provider-network-helper: BPF object load failed: result=%d errno=%d %s\n",
                    load_error, saved_errno, strerror(saved_errno));
            fprintf(stderr,
                    "fortgym-provider-network-helper: BPF verifier log follows (bounded to %u bytes)\n%s\n",
                    (unsigned int)(sizeof(bpf_kernel_log) - 1), bpf_kernel_log);
            goto done;
        }
    }
    result = 0;

done:
    bpf_object__close(object);
    return result;
}

static int build_pin_path(char output[PATH_MAX], const char *pin_root,
                          const char *name)
{
    const int count = snprintf(output, PATH_MAX, "%s/%s", pin_root, name);

    return count > 0 && count < PATH_MAX ? 0 : -1;
}

static int read_pinned_policy(const char *pin_root,
                              struct fortgym_provider_policy *policy)
{
    char path[PATH_MAX];
    uint32_t key = 0;
    int descriptor;
    int result;

    if (build_pin_path(path, pin_root, "policy") != 0)
        return -1;
    descriptor = bpf_obj_get(path);
    if (descriptor < 0)
        return -1;
    result = bpf_map_lookup_elem(descriptor, &key, policy);
    close(descriptor);
    return result;
}

static int verify_pinned_identity(const char *pin_root, const char *identity,
                                  struct fortgym_provider_policy *policy)
{
    memset(policy, 0, sizeof(*policy));
    if (read_pinned_policy(pin_root, policy) != 0 ||
        strncmp(policy->identity_sha256, identity,
                FORTGYM_IDENTITY_BUFFER_BYTES) != 0 ||
        policy->allowed_ipv4_be != htonl(INADDR_LOOPBACK) ||
        policy->allowed_port_be == 0)
        return -1;
    return 0;
}

static int read_members(const char *cgroup_path, pid_t members[FORTGYM_MAX_MEMBERS],
                        size_t *member_count)
{
    char path[PATH_MAX];
    FILE *stream;
    long value;
    size_t count = 0;

    if (snprintf(path, sizeof(path), "%s/cgroup.procs", cgroup_path) >=
        (int)sizeof(path))
        return -1;
    stream = fopen(path, "re");
    if (stream == NULL)
        return -1;
    while (fscanf(stream, "%ld", &value) == 1) {
        if (value <= 1 || value > INT_MAX || count == FORTGYM_MAX_MEMBERS) {
            fclose(stream);
            return -1;
        }
        members[count++] = (pid_t)value;
    }
    if (!feof(stream)) {
        fclose(stream);
        return -1;
    }
    fclose(stream);
    *member_count = count;
    return 0;
}

static void print_member_array(const pid_t *members, size_t count)
{
    size_t index;

    putchar('[');
    for (index = 0; index < count; ++index) {
        if (index != 0)
            putchar(',');
        printf("%ld", (long)members[index]);
    }
    putchar(']');
}

static int command_probe(int argc, char **argv)
{
    char helper_digest[65];
    char object_digest[65];
    char helper_path[PATH_MAX];

    if (argc != 6 || strcmp(argv[2], "--bpf-object") != 0 ||
        strcmp(argv[4], "--format") != 0 || strcmp(argv[5], "json") != 0 ||
        !is_absolute_clean_path(argv[3]))
        return fail_closed("probe command vector is noncanonical");
    if (require_privileged_helper() != 0 || require_host_layout() != 0 ||
        set_memlock_limit() != 0)
        return 70;
    if (self_executable_path(helper_path) != 0 ||
        require_secure_artifact(helper_path, true) != 0 ||
        require_secure_artifact(argv[3], false) != 0 ||
        sha256_file("/proc/self/exe", helper_digest) != 0 ||
        sha256_file(argv[3], object_digest) != 0 ||
        verify_bpf_object_contract(argv[3], true) != 0)
        return fail_closed("required BPF capability probe failed");

    fputs("{\"schema\":\"" CAPABILITY_SCHEMA
          "\",\"ok\":true,\"os\":\"linux\",\"architecture\":\"x86_64\","
          "\"cgroup_version\":2,\"bpffs\":true,\"cgroup_bpf\":true,"
          "\"default_deny\":true,\"structured_capture\":true,"
          "\"join_before_exec\":true,\"hooks\":",
          stdout);
    print_hooks();
    fputs(",\"helper_sha256\":", stdout);
    print_json_string(helper_digest);
    fputs(",\"bpf_object_sha256\":", stdout);
    print_json_string(object_digest);
    fputs("}\n", stdout);
    return 0;
}

static int remove_known_pins(const char *pin_root)
{
    char path[PATH_MAX];
    size_t index;

    for (index = 0; index < sizeof(pinned_links) / sizeof(pinned_links[0]); ++index) {
        if (build_pin_path(path, pin_root, pinned_links[index]) != 0 ||
            (unlink(path) != 0 && errno != ENOENT))
            return -1;
    }
    for (index = 0; index < sizeof(pinned_maps) / sizeof(pinned_maps[0]); ++index) {
        if (build_pin_path(path, pin_root, pinned_maps[index]) != 0 ||
            (unlink(path) != 0 && errno != ENOENT))
            return -1;
    }
    return 0;
}

static int install_policy(const char *object_path, const char *cgroup_path,
                          const char *pin_root, const char *identity,
                          unsigned int port, uint32_t poison_address_be,
                          uint16_t poison_port_be)
{
    struct fortgym_provider_policy policy;
    struct bpf_object *object = NULL;
    struct bpf_program *program;
    struct bpf_map *policy_map;
    struct bpf_map *lost_map;
    struct bpf_link *links[4] = {NULL, NULL, NULL, NULL};
    uint32_t key = 0;
    uint64_t zero = 0;
    int cgroup_descriptor = -1;
    size_t index;
    int result = -1;
    char pin_path[PATH_MAX];

    memset(&policy, 0, sizeof(policy));
    policy.allowed_ipv4_be = htonl(INADDR_LOOPBACK);
    policy.poison_ipv4_be = poison_address_be;
    policy.allowed_port_be = htons((uint16_t)port);
    policy.poison_port_be = poison_port_be;
    memcpy(policy.identity_sha256, identity, FORTGYM_IDENTITY_HEX_BYTES);
    policy.identity_sha256[FORTGYM_IDENTITY_HEX_BYTES] = '\0';

    object = bpf_object__open_file(object_path, NULL);
    if (libbpf_get_error(object) || bpf_object__load(object) != 0)
        goto done;
    policy_map = bpf_object__find_map_by_name(object, "policy");
    lost_map = bpf_object__find_map_by_name(object, "lost_events");
    if (policy_map == NULL || lost_map == NULL ||
        bpf_map_update_elem(bpf_map__fd(policy_map), &key, &policy, BPF_ANY) != 0 ||
        bpf_map_update_elem(bpf_map__fd(lost_map), &key, &zero, BPF_ANY) != 0)
        goto done;

    if (bpf_object__pin_maps(object, pin_root) != 0)
        goto done;
    cgroup_descriptor = open(cgroup_path, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (cgroup_descriptor < 0)
        goto done;
    for (index = 0; index < sizeof(required_programs) / sizeof(required_programs[0]);
         ++index) {
        program = bpf_object__find_program_by_name(object, required_programs[index]);
        if (program == NULL)
            goto done;
        links[index] = bpf_program__attach_cgroup(program, cgroup_descriptor);
        if (libbpf_get_error(links[index])) {
            links[index] = NULL;
            goto done;
        }
        if (build_pin_path(pin_path, pin_root, pinned_links[index]) != 0 ||
            bpf_link__pin(links[index], pin_path) != 0)
            goto done;
    }
    result = 0;

done:
    for (index = 0; index < sizeof(links) / sizeof(links[0]); ++index) {
        if (links[index] != NULL)
            bpf_link__destroy(links[index]);
    }
    if (cgroup_descriptor >= 0)
        close(cgroup_descriptor);
    if (object != NULL && !libbpf_get_error(object))
        bpf_object__close(object);
    if (result != 0)
        (void)remove_known_pins(pin_root);
    return result;
}

static int command_prepare(int argc, char **argv)
{
    const char *object_path;
    const char *cgroup_path;
    const char *pin_root;
    const char *identity;
    const char *expected_helper_sha256;
    const char *expected_object_sha256;
    uint32_t poison_address_be;
    uint16_t poison_port_be;
    unsigned int port;
    struct stat metadata;
    char helper_path[PATH_MAX];
    char observed_helper_sha256[65];
    char observed_object_sha256[65];

    if (argc != 23 || strcmp(argv[2], "--bpf-object") != 0 ||
        strcmp(argv[4], "--expected-helper-sha256") != 0 ||
        strcmp(argv[6], "--expected-bpf-object-sha256") != 0 ||
        strcmp(argv[8], "--cgroup") != 0 || strcmp(argv[10], "--pin-root") != 0 ||
        strcmp(argv[12], "--identity-sha256") != 0 ||
        strcmp(argv[14], "--allow-connect4") != 0 ||
        strcmp(argv[16], "--negative-canary-poison") != 0 ||
        strcmp(argv[18], "--deny-connect6") != 0 ||
        strcmp(argv[19], "--deny-sendmsg4") != 0 ||
        strcmp(argv[20], "--deny-sendmsg6") != 0 ||
        strcmp(argv[21], "--format") != 0 || strcmp(argv[22], "json") != 0)
        return fail_closed("prepare command vector is noncanonical");

    object_path = argv[3];
    expected_helper_sha256 = argv[5];
    expected_object_sha256 = argv[7];
    cgroup_path = argv[9];
    pin_root = argv[11];
    identity = argv[13];
    if (!is_absolute_clean_path(object_path) ||
        !is_lower_hex_sha256(expected_helper_sha256) ||
        !is_lower_hex_sha256(expected_object_sha256) ||
        !is_direct_child(cgroup_path, FORTGYM_CGROUP_ROOT) ||
        !is_direct_child(pin_root, FORTGYM_BPFFS_ROOT) ||
        !is_lower_hex_sha256(identity) ||
        !resource_component_matches_identity(cgroup_path, pin_root, identity) ||
        parse_loopback_endpoint(argv[15], &port) != 0 ||
        parse_nonloopback_ipv4_endpoint(argv[17], &poison_address_be,
                                        &poison_port_be) != 0)
        return fail_closed("prepare identity or path is invalid");
    if (require_privileged_helper() != 0 || require_host_layout() != 0 ||
        set_memlock_limit() != 0 || verify_bpf_object_contract(object_path, false) != 0)
        return 70;
    if (self_executable_path(helper_path) != 0 ||
        require_secure_artifact(helper_path, true) != 0 ||
        require_secure_artifact(object_path, false) != 0 ||
        sha256_file("/proc/self/exe", observed_helper_sha256) != 0 ||
        sha256_file(object_path, observed_object_sha256) != 0 ||
        strcmp(observed_helper_sha256, expected_helper_sha256) != 0 ||
        strcmp(observed_object_sha256, expected_object_sha256) != 0)
        return fail_closed("prepare pinned artifact identity changed");
    if (lstat(cgroup_path, &metadata) == 0 || errno != ENOENT ||
        lstat(pin_root, &metadata) == 0 || errno != ENOENT)
        return fail_closed("provider-network resources already exist");
    if (mkdir(cgroup_path, 0700) != 0 || mkdir(pin_root, 0700) != 0) {
        (void)rmdir(cgroup_path);
        return fail_closed("provider-network resource creation failed");
    }
    if (install_policy(object_path, cgroup_path, pin_root, identity, port,
                       poison_address_be, poison_port_be) != 0) {
        (void)remove_known_pins(pin_root);
        (void)rmdir(pin_root);
        (void)rmdir(cgroup_path);
        return fail_closed("provider-network BPF installation failed");
    }

    fputs("{\"schema\":\"" PREPARE_SCHEMA "\",\"ok\":true,"
          "\"identity_sha256\":",
          stdout);
    print_json_string(identity);
    fputs(",\"cgroup_path\":", stdout);
    print_json_string(cgroup_path);
    fputs(",\"pin_root\":", stdout);
    print_json_string(pin_root);
    fputs(",\"policy\":", stdout);
    print_policy(port);
    fputs(",\"hooks\":", stdout);
    print_hooks();
    fputs(",\"evidence_external\":true}\n", stdout);
    return 0;
}

static int identity_from_environment(unsigned int port, char output[65])
{
    static const char manifest_schema[] = "fortgym.provider-network-manifest/v1";
    const char *run_id = getenv("FORT_GYM_RUN_ID");
    const char *contract = getenv("FORT_GYM_RUN_CONTRACT_SHA256");
    const char *nonce = getenv("FORT_GYM_RUN_NONCE");
    const char *host = getenv("FORT_GYM_NETWORK_ALLOWED_HOST");
    char port_text[16];
    const char *parts[6];
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_length = 0;
    EVP_MD_CTX *context;
    size_t index;

    if (!is_safe_component(run_id) || !is_lower_hex_sha256(contract) || nonce == NULL ||
        strlen(nonce) < 32 || strlen(nonce) > 128 || host == NULL ||
        strcmp(host, "127.0.0.1") != 0)
        return -1;
    for (index = 0; nonce[index] != '\0'; ++index) {
        if (!((nonce[index] >= 'a' && nonce[index] <= 'z') ||
              (nonce[index] >= 'A' && nonce[index] <= 'Z') ||
              (nonce[index] >= '0' && nonce[index] <= '9') || nonce[index] == '_' ||
              nonce[index] == '-'))
            return -1;
    }
    snprintf(port_text, sizeof(port_text), "%u", port);
    parts[0] = manifest_schema;
    parts[1] = run_id;
    parts[2] = contract;
    parts[3] = nonce;
    parts[4] = host;
    parts[5] = port_text;
    context = EVP_MD_CTX_new();
    if (context == NULL || EVP_DigestInit_ex(context, EVP_sha256(), NULL) != 1)
        goto failed;
    for (index = 0; index < 6; ++index) {
        if ((index != 0 && EVP_DigestUpdate(context, "\0", 1) != 1) ||
            EVP_DigestUpdate(context, parts[index], strlen(parts[index])) != 1)
            goto failed;
    }
    if (EVP_DigestFinal_ex(context, digest, &digest_length) != 1 ||
        digest_length != 32)
        goto failed;
    EVP_MD_CTX_free(context);
    for (index = 0; index < digest_length; ++index)
        snprintf(output + (index * 2), 3, "%02x", digest[index]);
    output[64] = '\0';
    return 0;

failed:
    EVP_MD_CTX_free(context);
    return -1;
}

static int update_guard_policy(const char *pin_root, const char *identity,
                               const char *evidence_path_sha256)
{
    struct fortgym_provider_policy policy;
    char path[PATH_MAX];
    uint32_t key = 0;
    int descriptor;
    int result;

    if (verify_pinned_identity(pin_root, identity, &policy) != 0 ||
        build_pin_path(path, pin_root, "policy") != 0)
        return -1;
    descriptor = bpf_obj_get(path);
    if (descriptor < 0)
        return -1;
    policy.guard_attested = 1;
    memcpy(policy.evidence_path_sha256, evidence_path_sha256,
           FORTGYM_IDENTITY_HEX_BYTES);
    policy.evidence_path_sha256[FORTGYM_IDENTITY_HEX_BYTES] = '\0';
    result = bpf_map_update_elem(descriptor, &key, &policy, BPF_EXIST);
    close(descriptor);
    return result;
}

static int join_owned_cgroup(const char *cgroup_path)
{
    char path[PATH_MAX];
    char pid_text[32];
    pid_t members[FORTGYM_MAX_MEMBERS];
    size_t member_count = 0;
    int descriptor;
    int count;

    if (snprintf(path, sizeof(path), "%s/cgroup.procs", cgroup_path) >=
        (int)sizeof(path))
        return -1;
    count = snprintf(pid_text, sizeof(pid_text), "%ld\n", (long)getpid());
    descriptor = open(path, O_WRONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0)
        return -1;
    if (write(descriptor, pid_text, (size_t)count) != count) {
        close(descriptor);
        return -1;
    }
    close(descriptor);
    if (read_members(cgroup_path, members, &member_count) != 0 ||
        member_count != 1 || members[0] != getpid())
        return -1;
    return 0;
}

static int expect_denied_connect4(uint32_t address_be, uint16_t port_be)
{
    struct sockaddr_in destination;
    int descriptor;
    int result;
    int observed_errno;

    memset(&destination, 0, sizeof(destination));
    destination.sin_family = AF_INET;
    destination.sin_addr.s_addr = address_be;
    destination.sin_port = port_be;
    descriptor = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK,
                        IPPROTO_TCP);
    if (descriptor < 0)
        return -1;
    result = connect(descriptor, (const struct sockaddr *)&destination,
                     sizeof(destination));
    observed_errno = errno;
    close(descriptor);
    return result == -1 && (observed_errno == EPERM || observed_errno == EACCES) ? 0
                                                                                : -1;
}

static int expect_denied_connect6(uint16_t port_be)
{
    struct sockaddr_in6 destination;
    int descriptor;
    int result;
    int observed_errno;

    memset(&destination, 0, sizeof(destination));
    destination.sin6_family = AF_INET6;
    destination.sin6_addr = in6addr_loopback;
    destination.sin6_port = port_be;
    descriptor = socket(AF_INET6, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK,
                        IPPROTO_TCP);
    if (descriptor < 0)
        return -1;
    result = connect(descriptor, (const struct sockaddr *)&destination,
                     sizeof(destination));
    observed_errno = errno;
    close(descriptor);
    return result == -1 && (observed_errno == EPERM || observed_errno == EACCES) ? 0
                                                                                : -1;
}

static int expect_denied_sendmsg4(uint32_t address_be, uint16_t port_be)
{
    struct sockaddr_in destination;
    const unsigned char byte = 0;
    int descriptor;
    ssize_t result;
    int observed_errno;

    memset(&destination, 0, sizeof(destination));
    destination.sin_family = AF_INET;
    destination.sin_addr.s_addr = address_be;
    destination.sin_port = port_be;
    descriptor = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK,
                        IPPROTO_UDP);
    if (descriptor < 0)
        return -1;
    result = sendto(descriptor, &byte, sizeof(byte), 0,
                    (const struct sockaddr *)&destination, sizeof(destination));
    observed_errno = errno;
    close(descriptor);
    return result == -1 && (observed_errno == EPERM || observed_errno == EACCES) ? 0
                                                                                : -1;
}

static int expect_denied_sendmsg6(uint16_t port_be)
{
    struct sockaddr_in6 destination;
    const unsigned char byte = 0;
    int descriptor;
    ssize_t result;
    int observed_errno;

    memset(&destination, 0, sizeof(destination));
    destination.sin6_family = AF_INET6;
    destination.sin6_addr = in6addr_loopback;
    destination.sin6_port = port_be;
    descriptor = socket(AF_INET6, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK,
                        IPPROTO_UDP);
    if (descriptor < 0)
        return -1;
    result = sendto(descriptor, &byte, sizeof(byte), 0,
                    (const struct sockaddr *)&destination, sizeof(destination));
    observed_errno = errno;
    close(descriptor);
    return result == -1 && (observed_errno == EPERM || observed_errno == EACCES) ? 0
                                                                                : -1;
}

static int perform_negative_canary(const struct fortgym_provider_policy *policy)
{
    uint32_t dns_address_be;
    uint32_t https_address_be;

    if (inet_pton(AF_INET, NEGATIVE_DNS_IPV4, &dns_address_be) != 1 ||
        inet_pton(AF_INET, NEGATIVE_HTTPS_IPV4, &https_address_be) != 1 ||
        expect_denied_connect4(dns_address_be, htons(53)) != 0 ||
        expect_denied_connect4(https_address_be, htons(443)) != 0 ||
        expect_denied_connect4(policy->poison_ipv4_be,
                               policy->poison_port_be) != 0 ||
        expect_denied_connect6(policy->allowed_port_be) != 0 ||
        expect_denied_sendmsg4(dns_address_be, htons(53)) != 0 ||
        expect_denied_sendmsg6(htons(53)) != 0)
        return -1;
    return 0;
}

static int format_guard_attestation(char output[FORTGYM_MAX_GUARD_BYTES],
                                    const char *identity, unsigned int port,
                                    const char *evidence_path_sha256)
{
    const int count = snprintf(
        output, FORTGYM_MAX_GUARD_BYTES,
        "{\"schema\":\"" GUARD_SCHEMA
        "\",\"installed\":true,\"identity_sha256\":\"%s\","
        "\"policy\":\"loopback-port-only\",\"allowed_host\":\"127.0.0.1\","
        "\"allowed_port\":%u,\"evidence_path_sha256\":\"%s\"}\n",
        identity, port, evidence_path_sha256);

    return count > 0 && count < FORTGYM_MAX_GUARD_BYTES ? count : -1;
}

static int write_guard_payload_exclusive(const char *path, const char *payload,
                                         size_t payload_length)
{
    int descriptor;
    int saved_errno;
    size_t offset = 0;

    if (path == NULL || payload == NULL || payload_length == 0) {
        errno = EINVAL;
        return -1;
    }
    descriptor =
        open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (descriptor < 0)
        return -1;
    while (offset < payload_length) {
        const ssize_t written =
            write(descriptor, payload + offset, payload_length - offset);

        if (written < 0 && errno == EINTR)
            continue;
        if (written <= 0 || (size_t)written > payload_length - offset) {
            saved_errno = written < 0 ? errno : EIO;
            goto remove_partial;
        }
        offset += (size_t)written;
    }
    if (fsync(descriptor) != 0) {
        saved_errno = errno;
        goto remove_partial;
    }
    /* Never retry close: on Linux an EINTR close has already released the fd. */
    if (close(descriptor) != 0) {
        saved_errno = errno;
        (void)unlink(path);
        errno = saved_errno;
        return -1;
    }
    return 0;

remove_partial:
    /*
     * Only this successful O_EXCL open can have created path.  Remove a
     * partial attestation before returning, but retain the identity-owned
     * cgroup and pins for the privileged controller's exact reconciliation.
     */
    (void)unlink(path);
    (void)close(descriptor);
    errno = saved_errno;
    return -1;
}

static int write_guard_attestation_as_caller(const char *path, const char *payload,
                                             size_t payload_length, uid_t uid,
                                             gid_t gid)
{
    if (setgroups(0, NULL) != 0 || setresgid(gid, gid, gid) != 0 ||
        setresuid(uid, uid, uid) != 0 || getuid() != uid || geteuid() != uid ||
        getgid() != gid || getegid() != gid ||
        prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0) != 0 ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0)
        return -1;
    return write_guard_payload_exclusive(path, payload, payload_length);
}

static int command_enter(int argc, char **argv)
{
    const char *cgroup_path;
    const char *identity;
    const char *guard_path;
    const char *evidence_path;
    const char *port_value;
    struct fortgym_provider_policy policy;
    char expected_identity[65];
    char evidence_path_sha256[65];
    char attestation[FORTGYM_MAX_GUARD_BYTES];
    char *end = NULL;
    unsigned long parsed_port;
    int attestation_length;
    uid_t caller_uid = getuid();
    gid_t caller_gid = getgid();

    if (argc < 12 || strcmp(argv[2], "--cgroup") != 0 ||
        strcmp(argv[4], "--identity-sha256") != 0 ||
        strcmp(argv[6], "--require-python-policy") != 0 ||
        strcmp(argv[7], "loopback-port-only") != 0 ||
        strcmp(argv[8], "--guard-attestation") != 0 || strcmp(argv[10], "--") != 0 ||
        argv[11][0] != '/')
        return fail_closed("enter command vector is noncanonical");
    cgroup_path = argv[3];
    identity = argv[5];
    guard_path = argv[9];
    if (!is_direct_child(cgroup_path, FORTGYM_CGROUP_ROOT) ||
        !is_lower_hex_sha256(identity) || !is_absolute_clean_path(guard_path) ||
        caller_uid == 0 || caller_gid == 0)
        return fail_closed("enter identity, path, or caller is invalid");
    if (require_privileged_helper() != 0 || require_host_layout() != 0)
        return 70;

    /* The cgroup and pin directory share the exact controller resource component. */
    {
        const char *component = strrchr(cgroup_path, '/');
        char pin_root[PATH_MAX];

        if (component == NULL ||
            snprintf(pin_root, sizeof(pin_root), "%s/%s", FORTGYM_BPFFS_ROOT,
                     component + 1) >= (int)sizeof(pin_root) ||
            !resource_component_matches_identity(cgroup_path, pin_root, identity) ||
            verify_pinned_identity(pin_root, identity, &policy) != 0)
            return fail_closed("enter cannot prove pinned policy ownership");

        port_value = getenv("FORT_GYM_NETWORK_ALLOWED_PORT");
        evidence_path = getenv("FORT_GYM_NETWORK_EVIDENCE_PATH");
        errno = 0;
        parsed_port = port_value == NULL ? 0 : strtoul(port_value, &end, 10);
        if (getenv("FORT_GYM_NETWORK_POLICY") == NULL ||
            strcmp(getenv("FORT_GYM_NETWORK_POLICY"), "loopback-port-only") != 0 ||
            errno != 0 || end == port_value || *end != '\0' || parsed_port == 0 ||
            parsed_port > 65535 || htons((uint16_t)parsed_port) != policy.allowed_port_be ||
            evidence_path == NULL || !is_absolute_clean_path(evidence_path) ||
            identity_from_environment((unsigned int)parsed_port, expected_identity) != 0 ||
            strcmp(expected_identity, identity) != 0 ||
            sha256_text(evidence_path, evidence_path_sha256) != 0 ||
            update_guard_policy(pin_root, identity, evidence_path_sha256) != 0 ||
            join_owned_cgroup(cgroup_path) != 0 ||
            perform_negative_canary(&policy) != 0)
            return fail_closed("enter guard identity or atomic cgroup join failed");
    }

    attestation_length = format_guard_attestation(
        attestation, identity, (unsigned int)parsed_port, evidence_path_sha256);
    if (attestation_length < 0 ||
        write_guard_attestation_as_caller(guard_path, attestation,
                                          (size_t)attestation_length, caller_uid,
                                          caller_gid) != 0)
        return fail_closed(
            "guard attestation or privilege drop failed; owned enforcement "
            "retained for reconciliation");

    execve(argv[11], &argv[11], environ);
    /* Keep the complete guard so snapshot-and-cleanup can prove this failure. */
    return fail_closed(
        "inner worker exec failed; guard and owned enforcement retained for "
        "reconciliation");
}

static int inspect_owned_state(const char *cgroup_path, const char *pin_root,
                               const char *identity, bool *cgroup_exists,
                               bool *pins_exist, pid_t members[FORTGYM_MAX_MEMBERS],
                               size_t *member_count,
                               struct fortgym_provider_policy *policy)
{
    struct stat metadata;

    *cgroup_exists = lstat(cgroup_path, &metadata) == 0;
    if (*cgroup_exists && (!S_ISDIR(metadata.st_mode) || S_ISLNK(metadata.st_mode)))
        return -1;
    if (!*cgroup_exists && errno != ENOENT)
        return -1;
    *pins_exist = lstat(pin_root, &metadata) == 0;
    if (*pins_exist && (!S_ISDIR(metadata.st_mode) || S_ISLNK(metadata.st_mode)))
        return -1;
    if (!*pins_exist && errno != ENOENT)
        return -1;
    if (*cgroup_exists != *pins_exist)
        return -1;
    if (*pins_exist && verify_pinned_identity(pin_root, identity, policy) != 0)
        return -1;
    if (*cgroup_exists && read_members(cgroup_path, members, member_count) != 0)
        return -1;
    if (!*cgroup_exists)
        *member_count = 0;
    return 0;
}

static int parse_owned_resource_command(int argc, char **argv, const char *operation,
                                        const char **cgroup_path,
                                        const char **pin_root,
                                        const char **identity)
{
    if (argc != 10 || strcmp(argv[1], operation) != 0 ||
        strcmp(argv[2], "--cgroup") != 0 || strcmp(argv[4], "--pin-root") != 0 ||
        strcmp(argv[6], "--identity-sha256") != 0 ||
        strcmp(argv[8], "--format") != 0 || strcmp(argv[9], "json") != 0)
        return -1;
    *cgroup_path = argv[3];
    *pin_root = argv[5];
    *identity = argv[7];
    if (!is_direct_child(*cgroup_path, FORTGYM_CGROUP_ROOT) ||
        !is_direct_child(*pin_root, FORTGYM_BPFFS_ROOT) ||
        !is_lower_hex_sha256(*identity) ||
        !resource_component_matches_identity(*cgroup_path, *pin_root, *identity))
        return -1;
    return 0;
}

static int command_inspect(int argc, char **argv)
{
    const char *cgroup_path;
    const char *pin_root;
    const char *identity;
    bool cgroup_exists;
    bool pins_exist;
    pid_t members[FORTGYM_MAX_MEMBERS];
    size_t member_count;
    struct fortgym_provider_policy policy;

    if (parse_owned_resource_command(argc, argv, "inspect", &cgroup_path, &pin_root,
                                     &identity) != 0)
        return fail_closed("inspect command vector is noncanonical");
    if (require_privileged_helper() != 0 || require_host_layout() != 0 ||
        inspect_owned_state(cgroup_path, pin_root, identity, &cgroup_exists, &pins_exist,
                            members, &member_count, &policy) != 0)
        return fail_closed("inspect cannot prove exact resource ownership");

    fputs("{\"schema\":\"" INSPECT_SCHEMA
          "\",\"ok\":true,\"identity_sha256\":",
          stdout);
    print_json_string(identity);
    printf(",\"cgroup_exists\":%s,\"pins_exist\":%s,\"member_pids\":",
           cgroup_exists ? "true" : "false", pins_exist ? "true" : "false");
    print_member_array(members, member_count);
    fputs("}\n", stdout);
    return 0;
}

static int capture_event(void *context, void *data, size_t size)
{
    struct captured_events *captured = context;

    if (size != sizeof(struct fortgym_provider_event) ||
        captured->count >= FORTGYM_MAX_EVENTS) {
        ++captured->userspace_lost;
        return 0;
    }
    memcpy(&captured->items[captured->count], data,
           sizeof(struct fortgym_provider_event));
    ++captured->count;
    return 0;
}

static int drain_capture(const char *pin_root, struct captured_events *captured,
                         uint64_t *kernel_lost)
{
    char events_path[PATH_MAX];
    char lost_path[PATH_MAX];
    struct ring_buffer *ring = NULL;
    uint32_t key = 0;
    int events_descriptor = -1;
    int lost_descriptor = -1;
    int consumed;
    int result = -1;

    if (build_pin_path(events_path, pin_root, "events") != 0 ||
        build_pin_path(lost_path, pin_root, "lost_events") != 0)
        return -1;
    events_descriptor = bpf_obj_get(events_path);
    lost_descriptor = bpf_obj_get(lost_path);
    if (events_descriptor < 0 || lost_descriptor < 0)
        goto done;
    ring = ring_buffer__new(events_descriptor, capture_event, captured, NULL);
    if (libbpf_get_error(ring)) {
        ring = NULL;
        goto done;
    }
    do {
        consumed = ring_buffer__consume(ring);
    } while (consumed > 0);
    if (consumed < 0 ||
        bpf_map_lookup_elem(lost_descriptor, &key, kernel_lost) != 0)
        goto done;
    *kernel_lost += captured->userspace_lost;
    result = 0;

done:
    ring_buffer__free(ring);
    if (events_descriptor >= 0)
        close(events_descriptor);
    if (lost_descriptor >= 0)
        close(lost_descriptor);
    return result;
}

static int read_exact_guard(const char *path, const char *expected,
                            size_t expected_length)
{
    char value[FORTGYM_MAX_GUARD_BYTES];
    struct stat metadata;
    int descriptor;
    ssize_t count;

    descriptor = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0 || fstat(descriptor, &metadata) != 0 ||
        !S_ISREG(metadata.st_mode) || metadata.st_size != (off_t)expected_length) {
        if (descriptor >= 0)
            close(descriptor);
        return -1;
    }
    count = read(descriptor, value, sizeof(value));
    close(descriptor);
    if (count != (ssize_t)expected_length ||
        memcmp(value, expected, expected_length) != 0)
        return -1;
    return 0;
}

static const char *hook_name(uint8_t hook)
{
    switch (hook) {
    case FORTGYM_HOOK_CONNECT4:
        return "connect4";
    case FORTGYM_HOOK_CONNECT6:
        return "connect6";
    case FORTGYM_HOOK_SENDMSG4:
        return "sendmsg4";
    case FORTGYM_HOOK_SENDMSG6:
        return "sendmsg6";
    default:
        return NULL;
    }
}

static int validate_captured_event(const struct fortgym_provider_event *event,
                                   const char *identity)
{
    const char *name = hook_name(event->hook);
    const bool ipv4 = event->hook == FORTGYM_HOOK_CONNECT4 ||
                      event->hook == FORTGYM_HOOK_SENDMSG4;

    if (name == NULL ||
        strncmp(event->identity_sha256, identity,
                FORTGYM_IDENTITY_BUFFER_BYTES) != 0 ||
        (ipv4 && event->family != AF_INET) || (!ipv4 && event->family != AF_INET6) ||
        (event->decision != FORTGYM_DECISION_ALLOW &&
         event->decision != FORTGYM_DECISION_DENY) ||
        (event->decision == FORTGYM_DECISION_ALLOW && event->denied_errno != 0) ||
        (event->decision == FORTGYM_DECISION_DENY && event->denied_errno != EPERM))
        return -1;
    return 0;
}

static int print_captured_event(const struct fortgym_provider_event *event,
                                size_t sequence)
{
    char destination[INET6_ADDRSTRLEN];
    const bool ipv4 = event->hook == FORTGYM_HOOK_CONNECT4 ||
                      event->hook == FORTGYM_HOOK_SENDMSG4;
    const char *operation = event->hook == FORTGYM_HOOK_CONNECT4 ||
                                    event->hook == FORTGYM_HOOK_CONNECT6
                                ? "connect"
                                : "sendmsg";
    const char *protocol = event->protocol == IPPROTO_TCP
                               ? "tcp"
                               : (event->protocol == IPPROTO_UDP ? "udp" : "other");

    if (inet_ntop(ipv4 ? AF_INET : AF_INET6,
                  ipv4 ? (const void *)&event->destination_ipv4_be
                       : (const void *)event->destination_ipv6,
                  destination, sizeof(destination)) == NULL)
        return -1;
    printf("{\"sequence\":%zu,\"identity_sha256\":", sequence);
    print_json_string(event->identity_sha256);
    fputs(",\"hook\":", stdout);
    print_json_string(hook_name(event->hook));
    fputs(",\"operation\":", stdout);
    print_json_string(operation);
    fputs(",\"family\":", stdout);
    print_json_string(ipv4 ? "AF_INET" : "AF_INET6");
    fputs(",\"protocol\":", stdout);
    print_json_string(protocol);
    fputs(",\"destination_host\":", stdout);
    print_json_string(destination);
    printf(",\"destination_port\":%u,\"decision\":",
           (unsigned int)ntohs(event->destination_port_be));
    print_json_string(event->decision == FORTGYM_DECISION_ALLOW ? "allow" : "deny");
    if (event->decision == FORTGYM_DECISION_ALLOW)
        fputs(",\"errno\":0}", stdout);
    else
        fputs(",\"errno\":\"EPERM\"}", stdout);
    return 0;
}

static int command_snapshot(int argc, char **argv)
{
    const char *cgroup_path;
    const char *pin_root;
    const char *identity;
    const char *guard_path;
    bool cgroup_exists;
    bool pins_exist;
    pid_t members[FORTGYM_MAX_MEMBERS];
    size_t member_count;
    size_t index;
    struct fortgym_provider_policy policy;
    struct captured_events captured;
    uint64_t lost = 0;
    unsigned int port;
    char guard[FORTGYM_MAX_GUARD_BYTES];
    int guard_length;

    if (argc != 12 || strcmp(argv[1], "snapshot") != 0 ||
        strcmp(argv[2], "--cgroup") != 0 || strcmp(argv[4], "--pin-root") != 0 ||
        strcmp(argv[6], "--identity-sha256") != 0 ||
        strcmp(argv[8], "--guard-attestation") != 0 ||
        strcmp(argv[10], "--format") != 0 || strcmp(argv[11], "json") != 0)
        return fail_closed("snapshot command vector is noncanonical");
    cgroup_path = argv[3];
    pin_root = argv[5];
    identity = argv[7];
    guard_path = argv[9];
    if (!is_direct_child(cgroup_path, FORTGYM_CGROUP_ROOT) ||
        !is_direct_child(pin_root, FORTGYM_BPFFS_ROOT) ||
        !is_lower_hex_sha256(identity) ||
        !resource_component_matches_identity(cgroup_path, pin_root, identity) ||
        !is_absolute_clean_path(guard_path))
        return fail_closed("snapshot identity or path is invalid");
    if (require_privileged_helper() != 0 || require_host_layout() != 0 ||
        inspect_owned_state(cgroup_path, pin_root, identity, &cgroup_exists, &pins_exist,
                            members, &member_count, &policy) != 0 ||
        !cgroup_exists || !pins_exist || member_count != 0 ||
        policy.guard_attested != 1 ||
        !is_lower_hex_sha256(policy.evidence_path_sha256))
        return fail_closed("snapshot cannot prove quiescent owned enforcement");
    port = (unsigned int)ntohs(policy.allowed_port_be);
    guard_length = format_guard_attestation(guard, identity, port,
                                             policy.evidence_path_sha256);
    if (guard_length < 1 || read_exact_guard(guard_path, guard, (size_t)guard_length) != 0)
        return fail_closed("snapshot Python guard attestation is absent");
    memset(&captured, 0, sizeof(captured));
    if (drain_capture(pin_root, &captured, &lost) != 0)
        return fail_closed("snapshot structured capture is unavailable");
    for (index = 0; index < captured.count; ++index) {
        if (validate_captured_event(&captured.items[index], identity) != 0)
            return fail_closed("snapshot captured event is contradictory");
    }

    fputs("{\"schema\":\"" SNAPSHOT_SCHEMA
          "\",\"final\":true,\"identity_sha256\":",
          stdout);
    print_json_string(identity);
    fputs(",\"policy\":", stdout);
    print_policy(port);
    fputs(",\"hooks\":", stdout);
    print_hooks();
    printf(",\"lost_events\":%llu,\"event_count\":%zu,\"events\":[",
           (unsigned long long)lost, captured.count);
    for (index = 0; index < captured.count; ++index) {
        if (index != 0)
            putchar(',');
        if (print_captured_event(&captured.items[index], index + 1) != 0)
            return fail_closed("snapshot event encoding failed");
    }
    fputs("],\"python_guard\":", stdout);
    guard[(size_t)guard_length - 1] = '\0';
    fputs(guard, stdout);
    fputs("}\n", stdout);
    return 0;
}

static int command_cleanup(int argc, char **argv)
{
    const char *cgroup_path;
    const char *pin_root;
    const char *identity;
    bool cgroup_exists;
    bool pins_exist;
    pid_t members[FORTGYM_MAX_MEMBERS];
    size_t member_count;
    struct fortgym_provider_policy policy;
    struct stat metadata;

    if (parse_owned_resource_command(argc, argv, "cleanup", &cgroup_path, &pin_root,
                                     &identity) != 0)
        return fail_closed("cleanup command vector is noncanonical");
    if (require_privileged_helper() != 0 || require_host_layout() != 0 ||
        inspect_owned_state(cgroup_path, pin_root, identity, &cgroup_exists, &pins_exist,
                            members, &member_count, &policy) != 0 ||
        member_count != 0)
        return fail_closed("cleanup cannot prove empty exact ownership");
    if (pins_exist &&
        (remove_known_pins(pin_root) != 0 || rmdir(pin_root) != 0))
        return fail_closed("cleanup could not remove exact BPF pins");
    if (cgroup_exists && rmdir(cgroup_path) != 0)
        return fail_closed("cleanup could not remove exact cgroup");
    if (lstat(cgroup_path, &metadata) == 0 || errno != ENOENT ||
        lstat(pin_root, &metadata) == 0 || errno != ENOENT)
        return fail_closed("cleanup residue remains");

    fputs("{\"schema\":\"" CLEANUP_SCHEMA
          "\",\"ok\":true,\"identity_sha256\":",
          stdout);
    print_json_string(identity);
    fputs(",\"cgroup_absent\":true,\"pins_absent\":true}\n", stdout);
    return 0;
}

int main(int argc, char **argv)
{
    libbpf_set_strict_mode(LIBBPF_STRICT_ALL);
    libbpf_set_print(NULL);
    umask(0077);

    if (argc < 2)
        return fail_closed("command is required");
    if (strcmp(argv[1], "probe") == 0)
        return command_probe(argc, argv);
    if (strcmp(argv[1], "prepare") == 0)
        return command_prepare(argc, argv);
    if (strcmp(argv[1], "enter") == 0)
        return command_enter(argc, argv);
    if (strcmp(argv[1], "snapshot") == 0)
        return command_snapshot(argc, argv);
    if (strcmp(argv[1], "inspect") == 0)
        return command_inspect(argc, argv);
    if (strcmp(argv[1], "cleanup") == 0)
        return command_cleanup(argc, argv);
    return fail_closed("unknown command");
}
