"""Linux namespace boundary. Never imports application modules on the host."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess

from .manifest import git_entries, _git, _safe_relative

SAFE_DEVICES = {"null", "zero", "full", "random", "urandom", "tty"}


def export_tracked(repository_root: Path, destination: Path, *, revision: str = "HEAD") -> None:
    """Export Git objects, including link bytes; never dereference a source link."""
    if destination.exists():
        raise ValueError("snapshot destination must not exist")
    records = list(git_entries(repository_root, revision))
    if any(not _safe_relative(path) or path == ".env" or path.startswith(".git/") for path, *_ in records):
        raise ValueError("Unsafe tracked export")
    destination.mkdir(parents=True)
    for name, mode, kind, blob in records:
        if kind != "blob":
            raise ValueError(f"Unsupported Git object: {name}")
        target = destination / name
        if any(parent.is_symlink() for parent in target.parents if parent != destination.parent):
            raise ValueError(f"Export parent symlink: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _git(repository_root, "cat-file", "blob", blob)
        if mode == "120000":
            target.symlink_to(data.decode())
        else:
            target.write_bytes(data)
            target.chmod(0o755 if mode == "100755" else 0o644)


def validate_dependencies(dependencies: Path) -> Path:
    sites = list(dependencies.glob("lib/python*/site-packages"))
    if len(sites) != 1:
        raise ValueError("Expected exactly one isolated dependency site-packages")
    site = sites[0]
    for path in site.rglob("*"):
        if (path.name.endswith(".pth") and path.name not in {"_virtualenv.pth", "distutils-precedence.pth"}) or "__editable__" in path.name:
            raise ValueError(f"Dependency pth/editable hook prohibited: {path.name}")
        if path.is_symlink() and not path.resolve().is_relative_to(dependencies.resolve()):
            raise ValueError(f"Dependency link escapes isolated tree: {path.name}")
    return site


def sandbox_command(snapshot: Path, dependencies: Path, argv: list[str], *, cwd: str,
                    native_identity: bool = False) -> list[str]:
    if cwd not in {"/snapshot", "/snapshot/runtime"}:
        raise ValueError("cwd must be an executable snapshot root")
    if not argv:
        raise ValueError("Empty sandbox command")
    snapshot, dependencies = snapshot.resolve(), dependencies.resolve()
    site = validate_dependencies(dependencies)
    # Python -S prevents *all* site hooks (including system .pth) from executing.
    command = list(argv)
    if command[0] in {"python", "python3"}:
        # Keep sys.executable coherent with filtered fresh children, which must
        # resolve dependencies without inheriting this parent's PYTHONPATH.
        if not (dependencies / 'bin/python3').is_file():
            raise ValueError('Isolated dependency interpreter bin/python3 is required')
        command = ["/deps/bin/python3", "-S", *command[1:]]
    host_ns = {name: os.readlink(f"/proc/self/ns/{name}") for name in ("pid", "net", "mnt", "ipc", "user")}
    env = {"PATH": "/deps/validation-tools/bin:/usr/bin:/bin", "HOME": "/tmp/home", "XDG_CACHE_HOME": "/tmp/cache",
           "TMPDIR": "/tmp", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": f"{cwd}:/deps/{site.relative_to(dependencies)}", "LANG": "C.UTF-8",
           "ATR_SANDBOX_HOST_NAMESPACES": json.dumps(host_ns),
           "ATR_SANDBOX_HOST_PID": str(os.getpid()),
           "ATR_SANDBOX_HOST_PATH": str(Path.cwd()), "ATR_LAYOUT_SANDBOX": "1",
           "AUTONOMOUS_USE_REAL_LLM_IN_TEST": "0", "AUTONOMOUS_ALLOW_MOCK_FALLBACK": "1",
           "AUTONOMOUS_BACKEND": "ollama", "OLLAMA_BASE_URL": "http://127.0.0.1:9",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "OMP_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
           "ATR_CPU_WORKERS": "1", "MPLBACKEND": "Agg"}
    args = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
            "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/tmp/home",
            "--dir", "/tmp/cache", "--ro-bind", str(dependencies), "/deps",
            "--bind", str(snapshot), "/snapshot", "--clearenv"]
    for key, value in env.items():
        args.extend(["--setenv", key, value])
    if native_identity:
        # Native CLI account/localhost lookups need only these synthetic files.
        # Never expose host /etc, DNS, user names, profiles, or service records.
        contents = {'passwd': f'audit:x:{os.getuid()}:{os.getgid()}:Audit fixture:/tmp/home:/bin/sh\n',
                    'group': f'audit:x:{os.getgid()}:\n',
                    'hosts': '127.0.0.1 localhost\n::1 localhost\n',
                    'nsswitch.conf': 'passwd: files\ngroup: files\nhosts: files\n'}
        fixture = snapshot / '.atr-native-identity'
        if fixture.is_symlink():
            raise ValueError('Unsafe synthetic identity fixture')
        fixture.mkdir(exist_ok=True)
        if {p.name for p in fixture.iterdir()} - set(contents):
            raise ValueError('Unexpected synthetic identity fixture file')
        args.extend(['--dir', '/etc', '--setenv', 'ATR_NATIVE_IDENTITY', '1'])
        for name, content in contents.items():
            path = fixture / name
            if path.is_symlink() or (path.exists() and path.read_text() != content):
                raise ValueError('Synthetic identity fixture differs')
            if not path.exists():
                path.write_text(content)
            args.extend(['--ro-bind', str(path), '/etc/' + name])
    cpus = ",".join(str(cpu) for cpu in sorted(os.sched_getaffinity(0))[:2])
    return ["/usr/bin/taskset", "--cpu-list", cpus, *args,
            "--chdir", cwd, "--remount-ro", "/", "--", *command]


def require_boundary() -> None:
    expected = json.loads(os.environ.get("ATR_SANDBOX_HOST_NAMESPACES", "{}"))
    if set(expected) != {"pid", "net", "mnt", "ipc", "user"}:
        raise RuntimeError("OS namespace attestation missing; refusing app import")
    for kind, host_identity in expected.items():
        if os.readlink(f"/proc/self/ns/{kind}") == host_identity:
            raise RuntimeError(f"Host {kind} namespace still shared")
    if Path("/sys").exists() or Path("/home/jin").exists():
        raise RuntimeError("Host filesystem exposed")
    status = Path("/proc/self/status").read_text()
    if "CapEff:\t0000000000000000" not in status:
        raise RuntimeError("Capabilities not dropped")


def boundary_probe() -> dict:
    require_boundary()
    forbidden = [os.environ["ATR_SANDBOX_HOST_PATH"], "/home/jin/autonomous_researcher/.venv",
                 "/sys", "/run/docker.sock", "/tmp/.X11-unix"]
    visible, denied = [], 0
    for path in forbidden:
        try:
            os.stat(path)
            visible.append(path)
        except OSError:
            denied += 1
    devices = []
    for path in Path("/dev").iterdir():
        if path.name not in SAFE_DEVICES and not path.is_symlink() and stat.S_ISCHR(path.stat().st_mode):
            devices.append(str(path))
    for path in ("/dev/nvidia0", "/dev/video0", "/dev/ttyUSB0"):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            denied += 1
        else:
            os.close(descriptor)
            devices.append(path)
    sock = socket.socket()
    sock.settimeout(0.2)
    try:
        sock.connect(("192.0.2.1", 9))
        connected = True
    except OSError:
        denied += 1
        connected = False
    finally:
        sock.close()
    host_pid = int(os.environ["ATR_SANDBOX_HOST_PID"])
    # Never signal the numeric host PID, even in a private namespace.
    host_pid_visible = Path(f"/proc/{host_pid}").exists()
    if not host_pid_visible:
        denied += 1
    return {"host_paths_visible": visible, "device_nodes": devices,
            "host_pid_visible": host_pid_visible, "non_loopback_connected": connected,
            "denied_attempts": denied, "capabilities": "0000000000000000"}


def run_bounded(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    """Kill only the new test-owned process group on timeout, never host services."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, start_new_session=True) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
            return subprocess.CompletedProcess(command, 124, output + "\nSandbox timeout\n")
        return subprocess.CompletedProcess(command, process.returncode, output)
