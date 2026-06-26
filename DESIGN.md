# Design

aisnekbox is a small REST service that runs untrusted Python in an NsJail jail
and returns its output and any files it produced. This document explains the
architecture and the rationale behind the main decisions so the implementation
is easy to audit and extend.

## Goals

* **Security first** — untrusted code must never compromise the host or other
  requests (see [SECURITY.md](SECURITY.md)).
* **Auditability** — limits live in one validated place; the request path is
  short and readable; logs are structured and privacy-preserving.
* **Sustainability** — small, typed, well-tested modules; linting, type
  checking, a coverage gate and dependency automation in CI.
* **Performance** — predictable latency under load via bounded concurrency.

## Components

```
aisnekbox/
├── api/app.py     FastAPI app: validation, observability, concurrency, routing
├── sandbox.py     Builds the NsJail argv and supervises the subprocess
├── concurrency.py Non-blocking slot limiter (backpressure)
├── models.py      Pydantic request/response models + input validation
└── config.py      Centralised, validated, env-overridable settings
config/nsjail.cfg  Namespaces, mounts, rlimits and the seccomp policy
```

### Request flow (`POST /eval`)

1. **Observability middleware** assigns a request id, enforces the
   `Content-Length` body cap (→ `413`), and logs method/path/status/duration.
2. **Pydantic** validates the body: input size, argument count/length, and file
   paths (no absolute paths, no `..`).
3. The **limiter** acquires one of `max_concurrent_evals` slots without blocking;
   if none is free the request is rejected with `429` + `Retry-After`.
4. **Sandbox** creates a fresh temp work dir, writes the entrypoint and any
   uploaded files (re-checking path containment and total-upload size), and
   builds the NsJail argv with per-request rlimit overrides.
5. The NsJail subprocess runs the interpreter; the supervisor captures combined
   stdout/stderr up to `max_output_size` and enforces a wall-clock deadline.
6. New/modified files are collected, base64-encoded and returned; the work dir
   is always removed in a `finally` block.

## Key decisions

* **Out-of-process execution.** Untrusted code is never imported or `exec`-ed in
  the API process. The only execution path is an NsJail child, which keeps the
  trust boundary explicit and small.
* **Pure `build_command`.** The NsJail argument vector is produced by a
  side-effect-free method so the exact flags can be unit-tested without a kernel
  (see `tests/test_sandbox.py`) and reviewed at a glance.
* **Defence-in-depth limits.** Time, memory, network and filesystem-escape
  protections are each enforced at two layers (jail + supervisor/edge) so a
  single misconfiguration is not catastrophic.
* **Non-blocking backpressure.** The limiter uses a bounded semaphore acquired
  with `blocking=False`. Rejecting fast with `429` keeps tail latency bounded
  and protects the host, rather than queueing unbounded work.
* **Privacy-preserving logs.** Only metadata is logged (sizes, durations,
  returncodes, request ids). Submitted code and file contents are never logged,
  which is both a security and a compliance property.
* **Centralised settings.** All security-relevant limits are Pydantic fields
  with bounds and descriptions, overridable via `AISNEKBOX_*` env vars, so the
  policy is auditable and tunable without code changes.

## Testing strategy

The full request→jail→response pipeline is exercised in CI without kernel
privileges by a **fake NsJail** (`tests/conftest.py`) that parses the real argv
(bind mount, rlimit flags, `--` separator) and runs the entrypoint directly.
This validates command construction, file round-tripping, output truncation,
upload caps, error mapping and concurrency behaviour. The real NsJail path is
validated by the Docker build and manual end-to-end runs.

## Operational notes

* The service binds `0.0.0.0:8060` and is intended to sit behind a reverse proxy
  / ingress that adds TLS and authentication.
* The container runs `privileged` because NsJail needs to create namespaces; in
  production this should be scoped down to the specific capabilities required.
* Tunable limits (`AISNEKBOX_*`) let operators trade throughput against
  isolation strictness without modifying code.
