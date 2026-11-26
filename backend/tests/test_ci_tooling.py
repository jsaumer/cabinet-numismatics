"""The CI-only mock provider stays off the LAN (SPEC_0330 section 19, CX-01):
it approves anyone as its current subject and signs assertions for whoever
asks, so its published port must bind to loopback alone. The stack's own
port is published the way the product publishes it; the mock is not the
product. Also: the host scripts CI could not otherwise see failing."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]


def test_ci_mock_is_published_on_loopback_only():
    text = (REPO / "docker-compose.ci.yml").read_text(encoding="utf-8")
    published = re.findall(r'^\s*-\s*"([^"]+)"\s*$', text, re.M)
    ports = [p for p in published if re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}:\d+:\d+|\d+:\d+", p)]
    assert ports == ["127.0.0.1:8555:8555"], ports


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="needs bash on a POSIX host"
)
@pytest.mark.parametrize("flags, suffix", [([], ".zip.age"), (["--data-only"], "-data.zip.age")])
def test_backup_script_writes_an_archive_of_either_kind(tmp_path, flags, suffix):
    """A full backup wrote nothing from v0.30.0 to v0.37.4: the name was built
    with a test inside a command substitution, and under `set -e` its failure
    ended the script silently. Run the script itself, with a stand-in docker."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOCKER_CALLS"\nprintf archive\n')
    docker.chmod(0o755)
    calls = tmp_path / "calls"
    out = tmp_path / "out"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env["DOCKER_CALLS"] = str(calls)
    done = subprocess.run(
        ["bash", str(REPO / "scripts" / "backup.sh"), *flags, str(out)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    written = list(out.iterdir())
    assert len(written) == 1 and written[0].read_text() == "archive"
    name = written[0].name
    assert name.startswith("cabinet-backup-") and name.endswith(suffix)
    assert ("-data" in name) == bool(flags)
    assert f"write-archive --name {name}" in calls.read_text()
