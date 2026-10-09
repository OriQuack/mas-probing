"""`run_python`: model-written Python in a sandboxed child process (copied from the previous pilot's tools v3
`execute_code`, minus OWL's name and result format).

The child's preamble, before any model code:
1. **Landlock** (kernel LSM, unprivileged; ABI >= 4): the filesystem becomes an allowlist. Read: system dirs, the
   Python env, /proc/self. Read/write: the workspace dir only. Everything else is invisible, including /data2
   (GAIA dataset and answers, HF caches), the repo (other runs, .env), ~/.cache, /tmp and other processes' /proc.
   This also covers native-code readers (pyarrow) and child processes.
2. **No network**: Landlock's network rules deny every TCP bind/connect (kernel), and the audit hook refuses DNS
   lookups and socket connects with a clear message. Web content must come through the web tools (cached and
   blocklisted).
3. **Audit hook**: refuses to start processes.
The child gets no API keys; HOME/TMPDIR point into the workspace. Every refusal is tagged in the tool record as
`sandbox_denied: [file|process|network]`, so it is never mistaken for weak coding.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from minpilot.tools import blocklist
from minpilot.tools.documents import safe_dir

# Role-neutral (tools v4, K11): file workers have no web tools, so the message must not point them to one.
NETWORK_DENIED = ("Network access is not permitted from code in this environment. Web content is available only "
                  "through web tools, to workers that have them; if you have none, report that web access is needed.")
# Read-only for model code (plus the Python installation, added at runtime).
READ_ROOTS = ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", "/sys", "/run", "/opt", "/proc/self",
              "/proc/cpuinfo", "/proc/meminfo", "/proc/stat")


def python_roots() -> list[str]:
    return sorted({os.path.realpath(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix)})


def landlock_abi() -> int:
    import ctypes

    try:
        return int(ctypes.CDLL(None, use_errno=True).syscall(444, None, 0, 1))  # LANDLOCK_CREATE_RULESET_VERSION
    except Exception:
        return -1

_GUARD = r'''
import os as _os, sys as _sys
def _sandbox(work, read_roots, netlog, net_msg):
    import ctypes, struct
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    if libc.syscall(444, None, 0, 1) < 4:
        raise SystemExit("sandbox unavailable: Landlock ABI >= 4 required")
    handled = (1 << 15) - 1                       # all filesystem rights up to TRUNCATE (ABI 3+)
    read = 1 | 4 | 8                              # EXECUTE | READ_FILE | READ_DIR
    # handled_access_net = BIND_TCP | CONNECT_TCP with no net rule: every TCP bind/connect is refused (kernel)
    attr = struct.pack("QQ", handled, 1 | 2)
    ruleset = libc.syscall(444, attr, len(attr), 0)
    if ruleset < 0:
        raise SystemExit("sandbox: landlock_create_ruleset failed")
    def allow(path, rights):
        try:
            fd = _os.open(path, _os.O_PATH | _os.O_CLOEXEC)
        except OSError:
            return
        try:
            if not _os.path.isdir(path):
                rights &= 1 | 2 | 4 | (1 << 14)      # file rules accept file rights only
            rule = struct.pack("=Qi", rights, fd)
            if libc.syscall(445, ruleset, 1, rule, 0) < 0:   # LANDLOCK_RULE_PATH_BENEATH
                raise SystemExit(f"sandbox: landlock_add_rule failed for {path}")
        finally:
            _os.close(fd)
    for p in read_roots:
        allow(p, read)
    allow(work, handled)
    allow("/dev", read | 2)                       # /dev/null, /dev/urandom
    if libc.prctl(38, 1, 0, 0, 0) != 0:           # PR_SET_NO_NEW_PRIVS
        raise SystemExit("sandbox: prctl failed")
    if libc.syscall(446, ruleset, 0) != 0:        # landlock_restrict_self
        raise SystemExit("sandbox: landlock_restrict_self failed")
    _os.close(ruleset)

    def hook(event, args):
        if event in ("os.system", "subprocess.Popen", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
                     "pty.spawn"):
            raise PermissionError("Starting processes is not permitted in this environment; use Python only.")
        if event in ("socket.getaddrinfo", "socket.connect", "socket.bind") and args:
            target = args[0] if event == "socket.getaddrinfo" else args[1]
            if event != "socket.getaddrinfo" and isinstance(target, (str, bytes)):
                return  # AF_UNIX path sockets (local IPC), not the network
            host = str(target[0] if isinstance(target, tuple) else target).lower().rstrip(".")
            try:
                with open(netlog, "a") as f:
                    f.write(host + "\n")
            except Exception:
                pass
            raise PermissionError(net_msg)
    _sys.addaudithook(hook)
_sandbox(%(work)r, %(read_roots)r, %(netlog)r, %(net_msg)r)
del _sandbox
'''


def sandbox_denials(output: str) -> list[str]:
    """Which sandbox mechanism refused something in this run, so these failures are never mistaken for
    weak coding: `file` (Landlock: EACCES on a path outside the allowlist), `process` (audit hook),
    `network` (audit hook / Landlock net rules). An EACCES can in principle also be an ordinary permission
    error; the tool record keeps the full output for checking."""
    kinds = []
    network = "Network access is not permitted from code" in output
    if ("Permission denied" in output or "[Errno 13]" in output) and not network:
        kinds.append("file")
    if "Starting processes is not permitted" in output:
        kinds.append("process")
    if network:
        kinds.append("network")
    return kinds



@dataclass
class CodeResult:
    output: str            # what the model sees
    record: dict           # extra fields for the tool record


def run_python(code: str, work_dir: Path, run_no: int, *, timeout_s: float = 60.0, max_output_chars: int = 40_000,
               question: str | None = None, allowed: tuple[str, ...] = ()) -> CodeResult:
    work_dir = Path(work_dir).resolve()
    try:
        code_dir = safe_dir(work_dir, ".code")
        tmp = safe_dir(work_dir, ".code/tmp")
    except PermissionError as e:
        return CodeResult(f"Error: {e}", {"blocked": "outside_work_dir"})
    netlog = code_dir / f"net_{run_no:03d}.log"
    guard = _GUARD % {"work": str(work_dir), "read_roots": list(READ_ROOTS) + python_roots(),
                      "netlog": str(netlog), "net_msg": NETWORK_DENIED}
    script = code_dir / f"snippet_{run_no:03d}.py"
    script.write_text(guard + "\n" + code)
    keep = ("PATH", "LANG", "LC_ALL", "TZ", "TERM")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.update(HOME=str(work_dir), TMPDIR=str(tmp), MPLCONFIGDIR=str(tmp / "mpl"),
               XDG_CACHE_HOME=str(tmp / "cache"), PYTHONNOUSERSITE="1")
    timed_out = False
    try:
        # Relative script path: tracebacks shown to the agent carry no run-specific absolute path.
        proc = subprocess.run([sys.executable, "-u", "-s", str(script.relative_to(work_dir))], cwd=work_dir, env=env,
                              text=True, capture_output=True, timeout=timeout_s)
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = ((e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) + \
            f"\nProcess timed out after {timeout_s:g} seconds and was terminated."
        rc = -9
    raw = f"[stdout]\n{stdout}" if stdout else "[stdout]\n(empty)"
    if stderr:
        raw += f"\n[stderr]\n{stderr}"
    raw += f"\n[exit code] {rc}"
    hosts = sorted(set(netlog.read_text().split())) if netlog.exists() else []
    # Order matters: denial labels from the full raw output; then the workspace path -> "."; then the leak check on
    # the full normalised output (exempting the task's own attachment names); then truncation for the model only.
    denied = sandbox_denials(raw)
    out = normalize_paths(raw, work_dir)
    blocked = blocklist.content_block_reason(out, question, allowed=allowed)
    if blocked:
        out = "Error: the output contained content that is not permitted in this environment."
    elif len(out) > max_output_chars:
        out = out[:max_output_chars] + f"\n... (output truncated, total length {len(out)})"
    status = "timeout" if timed_out else ("error" if rc != 0 else "ok")
    return CodeResult(out, {"return_code": rc, "timed_out": timed_out, "execution_status": status, "hosts": hosts,
                            "sandbox_denied": denied, "blocked": blocked, "script": str(script.relative_to(work_dir))})


def normalize_paths(text: str, work_dir: Path) -> str:
    for root in {str(work_dir), os.path.realpath(work_dir)}:
        text = text.replace(root + "/", "./").replace(root, ".")
    return text
