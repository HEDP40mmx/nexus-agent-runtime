# Nexus v1 execution security model

Updated for implementation head `bc4e310a4303f6304b1073f925e99740c3dc3d31`.

Nexus distinguishes durable execution from host isolation. A child process that can be timed out and fenced is not automatically a sandbox for hostile code.

## Execution profiles

| Profile | Intended use | Current status |
|---|---|---|
| Trusted | Reviewed first-party handlers | Supported. Non-importable handlers currently use a same-user fork fallback with bounded protocol and timeout containment. |
| Restricted | Importable third-party handlers with controlled process launch | Partially implemented. Importable handlers launch through `python -I -m nexus._action`, with fixed arguments, `shell=False`, `close_fds=True`, a new session/process group, bounded stdin/stdout/stderr, minimal environment, monotonic timeout, and active cancellation/lease-loss termination. OS resource limits and filesystem/network restrictions are not yet implemented. |
| Isolated | Potentially hostile or unknown packages | Not implemented. Requires demonstrated OS-enforced confinement such as a carefully configured container, namespace/seccomp profile, or dedicated VM. A container alone must not be treated as a complete guarantee. |

The current API does not yet expose an explicit profile field. The effective selection is based on handler registration: importable top-level handlers use the clean subprocess path; non-importable handlers use the trusted fallback. This is an interim migration boundary, not a final policy interface.

## Clean subprocess boundary

The clean path invokes an absolute Python executable with the fixed vector:

```text
python -I -m nexus._action module:qualname
```

The child receives only bounded JSON on stdin. It resolves the registered module and qualified function name, constructs an `ActionContext`, and emits one bounded JSON response. The parent supplies a minimal environment containing only locale, Python buffering, and a basic `PATH`; bearer tokens, provider credentials, and unrelated environment variables are not copied. File descriptors are closed, and the child begins a new session for process-group cleanup.

The supervisor drains stdout and stderr incrementally, applies 64 KiB/32 KiB limits, enforces a monotonic timeout, and terminates the process group on timeout. A heartbeat lease-loss or durable cancellation also terminates the child actively. Completion remains protected by durable owner/epoch fencing.

This is operational containment, not hostile-code isolation. The clean child still runs as the same operating-system user and can access resources permitted to that user. It may still perform external effects before termination, and those effects are not undone by killing the process.

## Release gates

The following gates are review requirements, not claims that all are complete:

1. No fork from a multithreaded worker for Restricted or Isolated execution. **Partially satisfied:** clean importable path avoids fork; the trusted fallback still uses fork.
2. No inherited provider credentials or unrelated descriptors. **Satisfied for the clean path;** adversarial descriptor testing remains incomplete.
3. Bounded child protocol and resource consumption. **Protocol bounds satisfied;** OS CPU, memory, process-count, filesystem, and network controls remain incomplete.
4. Child termination on timeout, cancellation, and confirmed lease loss. **Implemented and locally tested for clean actions.**
5. Authenticated audit identity and HTTP concurrency/rate limits. **Implemented locally:** role tokens, role-derived principals, bounded handlers, socket timeout, and per-client sliding-window limiter.
6. Adversarial process-escape and resource-exhaustion tests. **Pending.**
7. Documented trusted-code policy and external-effect semantics. **Documented:** execution remains at-least-once for external effects unless the provider honors the durable effect key.

## Operational policy

Until Restricted and Isolated profiles have OS-enforced controls, run only reviewed action packages under a dedicated low-privilege service account. Do not place bearer tokens, provider keys, wallet credentials, or unrelated secrets in the worker environment. Use approval gates for destructive, financial, or externally visible actions. Treat retries as at-least-once external execution and require provider-side idempotency using the durable effect key.
