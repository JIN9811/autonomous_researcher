"""Exercise the generated launcher without starting servers or touching devices."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def launcher(tmp_path):
    project = tmp_path / "checkout with spaces"
    python = project / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    # Replace only the external server/process-control interpreter. The real
    # generated shell dispatch, down/up ordering and error handling run intact.
    python.write_text(f"#!{sys.executable}\n" + '''
import os, pathlib, sys
args = sys.argv[1:]
if args == ["-m", "app.serve"]:
    phase = "up"
elif len(args) == 2 and args[0] == "-c" and "targets = []" in args[1]:
    phase = "down"
elif len(args) == 2 and args[0] == "-c" and "pids_by_group = {}" in args[1]:
    phase = "cleanup"
else:
    raise SystemExit("Unexpected process boundary")
with pathlib.Path(os.environ["CLI_TEST_TRACE"]).open("a") as stream:
    stream.write(phase + "\\n")
if os.environ.get("CLI_TEST_FAIL") == phase:
    raise SystemExit(7)
''')
    python.chmod(0o755)
    target = tmp_path / "atr"
    installer = (ROOT / "install/install_cli.sh").read_text()
    # Use the installer's actual here-document expansion, without installing
    # into the user's home or modifying shell profiles.
    heredoc = installer.split('cat > "${TARGET}" <<EOF\n', 1)[1].split('\nEOF\n', 1)[0]
    generator = 'PROJECT_DIR="$1"\nTARGET="$2"\ncat > "${TARGET}" <<EOF\n' + heredoc + '\nEOF\n'
    subprocess.run(["bash", "-c", generator, "generate", str(project), str(target)], check=True)
    target.chmod(0o755)
    trace = tmp_path / "trace"
    return target, trace


@pytest.mark.parametrize("failure, expected, code", [
    ("", ["down", "cleanup", "up"], 0),
    ("down", ["down"], 7),
    ("cleanup", ["down", "cleanup"], 7),
    ("up", ["down", "cleanup", "up"], 7),
])
def test_restart_uses_down_then_up_and_propagates_failures(launcher, failure, expected, code):
    command, trace = launcher
    result = subprocess.run([str(command), "restart"], env={**os.environ,
        "CLI_TEST_TRACE": str(trace), "CLI_TEST_FAIL": failure}, capture_output=True, text=True)
    assert result.returncode == code, result.stdout + result.stderr
    assert (trace.read_text().splitlines() if trace.exists() else []) == expected


def test_restart_rejects_extra_arguments_without_stopping(launcher):
    command, trace = launcher
    result = subprocess.run([str(command), "restart", "--force"],
        env={**os.environ, "CLI_TEST_TRACE": str(trace)}, capture_output=True)
    assert result.returncode == 2
    assert not trace.exists()


@pytest.mark.parametrize("command, expected", [("up", ["up"]), ("down", ["down", "cleanup"])])
def test_existing_up_and_down_paths_are_unchanged(launcher, command, expected):
    executable, trace = launcher
    result = subprocess.run([str(executable), command],
        env={**os.environ, "CLI_TEST_TRACE": str(trace), "CLI_TEST_FAIL": ""}, capture_output=True)
    assert result.returncode == 0
    assert trace.read_text().splitlines() == expected
