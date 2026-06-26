# Security model

aisnekbox executes **untrusted, attacker-controlled Python code**. The whole
design assumes the submitted code is hostile and must not be able to read host
data, reach the network, persist anything, or affect other requests. This
document records the threat model and the concrete mitigations so the security
posture is auditable in one place.

## Trust boundary

```
client ──HTTP──▶ API process (trusted) ──spawns──▶ NsJail (boundary) ──▶ user code (untrusted)
```

* The **API process** is trusted. It validates input, enforces limits and never
  imports or executes the submitted code in-process.
* **NsJail** is the enforcement boundary. Untrusted code only ever runs as a
  child of NsJail, inside its namespaces, capability set and seccomp filter.
* **User code** is assumed hostile.

## Assets to protect

1. Host filesystem confidentiality and integrity.
2. Host/network reachability (no exfiltration, no SSRF, no lateral movement).
3. Availability of the service for other requests (no DoS).
4. The API process and the host kernel.

## Threats and mitigations

| # | Threat | Mitigation |
|---|--------|------------|
| T1 | Read host files (`/etc/passwd`, secrets) | System dirs are bind-mounted **read-only**, `nosuid`+`nodev`; the only writable path is a per-request tmpfs work dir. |
| T2 | Write/modify host files | Work dir is a throwaway temp dir bind-mounted into the jail and `shutil.rmtree`-d after every run. No host path is writable. |
| T3 | Network access / exfiltration / SSRF | Empty network namespace (`clone_newnet` with no interface) **and** seccomp denies `socket`/`socketpair` (EPERM) as defence-in-depth. |
| T4 | Privilege escalation | `no_new_privs` set, all capabilities dropped, `setuid`/`setgid` binaries neutralised via `nosuid` mounts, user namespace maps to an unprivileged id. |
| T5 | Fork bomb / resource exhaustion in jail | `rlimit_nproc` (default 1), `rlimit_as` (memory), `rlimit_cpu`, `rlimit_fsize`, `rlimit_nofile`, `rlimit_stack`, `rlimit_core=0`. |
| T6 | Infinite loop / sleeping to dodge CPU limit | Supervisor enforces an independent **wall-clock** deadline and escalates `SIGTERM`→`SIGKILL`. |
| T7 | Output flooding (OOM the API via stdout) | Output capture is capped at `max_output_size`; the pipe keeps draining but excess bytes are discarded and the result is marked truncated. |
| T8 | Path traversal via uploaded file paths | File paths are validated at the edge (reject absolute paths and `..`) and re-checked with a resolved-path containment test (`_safe_join`) before writing. |
| T9 | Oversized request body (memory pressure) | Requests above `max_request_body_size` are rejected with `413` from `Content-Length` before the body is buffered; per-file and total-upload caps bound decoded bytes. |
| T10 | Service-wide DoS via request floods | Bounded concurrency: at most `max_concurrent_evals` jails run at once; excess requests get `429` with `Retry-After` instead of overcommitting the host. |
| T11 | Kernel attack surface (exploit syscalls) | Seccomp **kills** `ptrace`, `process_vm_*`, module (un)loading, `mount`/`pivot_root`/`chroot`, `kexec_*`, `bpf`, `setns`/`unshare`, `perf_event_open`, key management and clock-setting syscalls. |
| T12 | Arbitrary binary execution | The interpreter path is constrained to a configurable **allowlist** (`allowed_executables`); anything else is rejected. |
| T13 | Sensitive data leaking into logs | Logs are request-scoped and record only metadata (request id, method, path, status, duration, returncode, output size, file count). **Submitted code and file contents are never logged.** |

## Defence-in-depth layering

Every limit is enforced at more than one layer where practical:

* **Time:** `rlimit_cpu` inside the jail *and* an independent wall-clock timeout
  in the supervisor.
* **Network:** empty netns *and* seccomp `socket` denial.
* **Memory:** `rlimit_as` inside the jail *and* a request-body cap at the edge.
* **Filesystem escape:** edge validation in Pydantic *and* a resolved-path
  containment check before any write.

## Residual risks / assumptions

* Security depends on a correctly configured host kernel with namespace and
  seccomp support; NsJail must run with the privileges it needs to set up
  namespaces (the container runs `privileged` for this reason).
* A 0-day in the Linux kernel reachable through the *allowed* syscall set is out
  of scope; the seccomp policy reduces but cannot eliminate kernel attack
  surface.
* The seccomp policy is a denylist over a default-allow base to keep CPython
  working across versions; a strict allowlist would be tighter but more brittle.

## Reporting

This is an experimental project. Please open an issue describing the problem
(without a public exploit) if you find a security weakness.
