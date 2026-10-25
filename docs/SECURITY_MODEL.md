# Nexus v1 execution security model

Updated for implementation head `bc4e310a4303f6304b1073f925e99740c3dc3d31`.

Nexus distinguishes durable execution from host isolation. A child process that can be timed out and fenced is not automatically a sandbox for hostile code.

## Execution profiles

| Profile | Intended use | Current status |
|---|---|---|
| Trusted | Reviewed first-party handlers | Supported. Non-importable handlers currently use a same-user fork fallback with bounded protocol and timeout containment. |
| Restricted | Importable third-party handlers with controlled process launch | Partially implemented. Importable handlers launch through `python -I -m nexus._action`, with fixed arguments, `shell=False`, `close_fds=True`, a new session/process group, bounded stdin/stdout/stderr, minimal environment, monotonic timeout, active cancellation/lease-loss termination, and POSIX CPU/address-space/file-size limits. Filesystem/network restrictions are not implied by this profile. |
| Isolated | Potentially hostile or unknown packages | Opt-in and fail-closed. The supervisor requires an absolute filesystem root, probes unprivileged Linux user/mount/pid/network namespace capability, launches with `unshare`, and the child applies CPU/address-space/file-size/process-count limits before entering the root with `chroot`. The isolated network namespace has no inherited interfaces (`network_mode="none"`). If any required capability is unavailable, no action is launched. A namespace alone must not be treated as a complete hostile-code guarantee. |

`Engine` and `Worker` expose an explicit `execution_profile` (`trusted`, `restricted`, or `isolated`) and optional `ResourceLimits`. Isolated execution rejects non-importable handlers and missing/relative filesystem roots. The default remains `trusted` for compatibility; non-importable handlers use the trusted fallback. Deployments requiring Restricted or Isolated policy must opt in explicitly.

## Clean subprocess boundary

The clean path invokes an absolute Python executable with the fixed vector:

```text
python -I -m nexus._action module:qualname
```

The child receives only bounded JSON on stdin. It resolves the registered module and qualified function name, constructs an `ActionContext`, and emits one bounded JSON response. The parent supplies a minimal environment containing only locale, Python buffering, and a basic `PATH`; bearer tokens, provider credentials, and unrelated environment variables are not copied. File descriptors are closed, and the child begins a new session for process-group cleanup.

The supervisor drains stdout and stderr incrementally, applies 64 KiB/32 KiB limits, enforces a monotonic timeout, and terminates the process group on timeout. A heartbeat lease-loss or durable cancellation also terminates the child actively. Completion remains protected by durable owner/epoch fencing.

This is operational containment, not hostile-code isolation. The clean child still runs as the same operating-system user and can access resources permitted to that user. It may still perform external effects before termination, and those effects are not undone by killing the process.

## OS limits and filesystem boundary

`ResourceLimits` maps to POSIX `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, and `RLIMIT_NPROC`. These are enforced by the kernel and inherited by the action handler. The Isolated profile additionally requires a directory root and a successful `unshare --user --map-root-user --mount --pid --net --fork` capability probe. The child enters the configured root with `chroot` after resolving the registered handler, and the private network namespace starts without inherited host interfaces. This bootstrap arrangement requires a deployment image whose interpreter and action dependencies are available before the root transition; it is not a substitute for a complete container or VM image.

The current sandbox cannot create the required unprivileged namespace, so qualification verifies the fail-closed path. Deployments must rerun isolated-profile qualification on the target kernel and treat a failed capability probe as a deployment error.

## Release gates

The following gates are review requirements, not claims that all are complete:

1. No fork from a multithreaded worker for Restricted or Isolated execution. **Partially satisfied:** clean importable path avoids fork; the trusted fallback still uses fork.
2. No inherited provider credentials or unrelated descriptors. **Satisfied for the clean path;** adversarial descriptor testing remains incomplete.
3. Bounded child protocol and resource consumption. **CPU, address-space, file-size, and process-count limits implemented;** filesystem escape and network-deny behavior require further OS qualification.
4. Child termination on timeout, cancellation, and confirmed lease loss. **Implemented and locally tested for clean actions.**
5. Authenticated audit identity and HTTP concurrency/rate limits. **Implemented locally:** role tokens, role-derived principals, bounded handlers, socket timeout, and per-client sliding-window limiter.
6. Adversarial process-escape and resource-exhaustion tests. **Pending;** current tests cover limit validation and fail-closed namespace/root handling, not hostile escape behavior.
7. Documented trusted-code policy and external-effect semantics. **Documented:** execution remains at-least-once for external effects unless the provider honors the durable effect key.

## Operational policy

Until Restricted and Isolated profiles have OS-enforced controls, run only reviewed action packages under a dedicated low-privilege service account. Do not place bearer tokens, provider keys, wallet credentials, or unrelated secrets in the worker environment. Use approval gates for destructive, financial, or externally visible actions. Treat retries as at-least-once external execution and require provider-side idempotency using the durable effect key.
