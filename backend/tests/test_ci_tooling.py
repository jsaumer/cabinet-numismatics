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


# --- the release's supply chain (v0.40.0) --------------------------------------

WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
BUILD_IMAGES = REPO / ".github" / "actions" / "build-images" / "action.yml"
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")


def test_every_action_is_pinned_by_commit():
    """A tag on someone else's repository can be moved; a commit can't. Each
    `uses:` names a full commit hash with the version in a comment beside it,
    which is also the form Dependabot updates. Local actions (`./`) are this
    repository's own."""
    checked = 0
    for path in [*WORKFLOWS, BUILD_IMAGES]:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*(?:-\s*)?uses:\s*(.+?)\s*$", line)
            if not match or match.group(1).startswith("./"):
                continue
            assert PINNED.match(match.group(1)), f"{path.name}: {match.group(1)}"
            checked += 1
    assert checked >= 20


def test_dependabot_watches_the_shared_build_too():
    text = (REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "/.github/actions/build-images" in text


def test_the_release_builds_both_platforms_with_provenance_and_an_sbom():
    yaml = pytest.importorskip("yaml")
    action = yaml.safe_load(BUILD_IMAGES.read_text(encoding="utf-8"))
    builds = [s for s in action["runs"]["steps"] if "build-push-action" in s.get("uses", "")]
    assert [b["with"]["context"] for b in builds] == ["./backend", "."]
    for build in builds:
        options = build["with"]
        assert options["platforms"] == "linux/amd64,linux/arm64"
        assert options["provenance"] == "mode=max" and options["sbom"] is True
        assert options["push"] == "${{ inputs.push == 'true' }}"
        for label in ("source", "version", "revision", "created", "licenses=MIT"):
            assert f"org.opencontainers.image.{label}" in options["labels"]
        assert "index:org.opencontainers.image.source" in options["annotations"]

    def shared_build(workflow: str, job: str) -> dict:
        jobs = yaml.safe_load((REPO / ".github" / "workflows" / workflow).read_text("utf-8"))
        steps = jobs["jobs"][job]["steps"]
        [step] = [s for s in steps if s.get("uses") == "./.github/actions/build-images"]
        return step["with"]

    # The release pushes; the pull request check runs the same build and doesn't.
    assert shared_build("ci.yml", "publish")["push"] == "true"
    assert shared_build("images.yml", "check")["push"] == "false"

    # The frontend is compiled once, on the builder's own platform.
    first = next(
        line
        for line in (REPO / "frontend" / "Dockerfile").read_text("utf-8").splitlines()
        if line.startswith("FROM ")
    )
    assert first == "FROM --platform=$BUILDPLATFORM node:26-alpine AS build"


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="needs bash on a POSIX host"
)
@pytest.mark.parametrize(
    "tag, prerelease, expected",
    [
        ("v0.40.0", "false", ["0.40.0", "latest"]),  # before 1.0: no floating tags
        ("v1.0.0-rc.1", "true", ["1.0.0-rc.1"]),  # a candidate moves nothing
        ("v1.0.0", "false", ["1.0.0", "latest", "1", "1.0"]),
        ("v1.2.3", "false", ["1.2.3", "latest", "1", "1.2"]),
        ("v2.0.0", "false", ["2.0.0", "latest", "2", "2.0"]),
    ],
)
def test_the_tags_a_release_pushes(tmp_path, tag, prerelease, expected):
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    [step] = [s for s in workflow["jobs"]["publish"]["steps"] if s.get("id") == "tags"]
    script = step["run"].replace("${{ github.repository_owner }}", "owner")
    assert "${{" not in script
    major, minor = re.match(r"v(\d+)\.(\d+)", tag).groups()
    output = tmp_path / "output"
    env = {
        **os.environ,
        "GITHUB_REF_NAME": tag,
        "GITHUB_OUTPUT": str(output),
        "PRERELEASE": prerelease,
        "MAJOR": major,
        "MINOR": minor,
    }
    subprocess.run(["bash", "-euo", "pipefail", "-c", script], env=env, check=True)
    text = output.read_text(encoding="utf-8")
    for image in ("backend", "proxy"):
        block = text.split(f"{image}<<EOF\n", 1)[1].split("EOF", 1)[0].split()
        assert block == [f"ghcr.io/owner/cabinet-numismatics-{image}:{t}" for t in expected]
    assert f"version={tag[1:]}\n" in text
