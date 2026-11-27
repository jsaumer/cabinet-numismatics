"""The CI-only mock provider stays off the LAN (SPEC_0330 section 19, CX-01):
it approves anyone as its current subject and signs assertions for whoever
asks, so its published port must bind to loopback alone. The stack's own
port is published the way the product publishes it; the mock is not the
product. Also: the host scripts CI could not otherwise see failing."""

import json
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


# --- the three ways to run the stack stay in step (v0.41.0) ---------------------

COMPOSE_FILES = {
    "source": REPO / "docker-compose.yaml",  # builds; reads .env
    "images": REPO / "deploy" / "docker-compose.yaml",  # pull and run, one file
    "swarm": REPO / "deploy" / "docker-stack.yaml",
}
# Supplied another way in one of the files, on purpose.
NOT_IN_SOURCE = {"AUTO_MIGRATE", "PUID", "PGID", "TZ", "REESTIMATE_DAYS", "SECRET_KEY",
                 "RESTORE_ENABLED", "RESTORE_MAX_GB"}  # fmt: skip
NOT_IN_SWARM = {"AUTH_INSECURE_HTTP", "SETUP_CODE", "SETUP_CODE_FILE", "BACKUP_KEY_FILE",
                "BACKUP_KEY", "AUTO_MIGRATE"}  # fmt: skip


def _environment(service: dict) -> set[str]:
    """The variable names a service is given, whichever way the file lists them."""
    env = service.get("environment") or {}
    if isinstance(env, list):
        return {entry.split("=", 1)[0] for entry in env}
    return set(env)


def _compose(name: str) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(COMPOSE_FILES[name].read_text(encoding="utf-8"))


def test_the_pull_and_run_file_needs_nothing_beside_it():
    """deploy/docker-compose.yaml is the README's quick start: one file in an
    empty folder. It can't build, read an env file, or mount a host path, and
    the only setting it insists on is the database password."""
    text = COMPOSE_FILES["images"].read_text(encoding="utf-8")
    stack = _compose("images")
    assert set(stack["services"]) == {"backend", "proxy", "db"}
    for name, service in stack["services"].items():
        assert "build" not in service and "env_file" not in service, name
        for volume in service.get("volumes", []):
            assert not volume.startswith(("/", ".", "~")), f"{name}: {volume}"
    assert set(re.findall(r"\$\{(\w+):\?", text)) == {"DB_PASSWORD"}
    # The same images the release publishes and the other two files name.
    for name in ("backend", "proxy"):
        image = stack["services"][name]["image"]
        assert image == f"ghcr.io/jsaumer/cabinet-numismatics-{name}:${{TAG:-latest}}"
        assert _compose("source")["services"][name]["image"] == image
        assert _compose("swarm")["services"][name]["image"] == image
    # Where it answers by default, and the cookie setting that goes with it.
    env = stack["services"]["backend"]["environment"]
    assert env["PUBLIC_ORIGINS"] == "${PUBLIC_ORIGINS:-http://localhost}"
    assert env["AUTH_INSECURE_HTTP"] == "${AUTH_INSECURE_HTTP:-true}"
    assert stack["services"]["proxy"]["environment"]["PUBLIC_ORIGINS"] == env["PUBLIC_ORIGINS"]


def test_a_setting_one_compose_file_passes_the_others_pass_too():
    """A variable added to one file and forgotten in another is a setting that
    silently does nothing for whoever runs the other."""
    images = _environment(_compose("images")["services"]["backend"])
    source = _environment(_compose("source")["services"]["backend"])
    swarm = _environment(_compose("swarm")["services"]["backend"])
    # The source file also hands the backend all of .env, so it may list fewer.
    assert source - images == set()
    assert images - source == NOT_IN_SOURCE
    assert swarm - images == set()
    assert images - swarm == NOT_IN_SWARM
    for name in COMPOSE_FILES:
        proxy = _environment(_compose(name)["services"]["proxy"])
        assert proxy == {"PUBLIC_ORIGINS", "ALLOWED_HOSTS", "TRUSTED_ASSERTION_HEADER"}, name
    # The database is given its three settings and no file of secrets.
    assert "env_file" not in _compose("source")["services"]["db"]


def test_a_wrong_address_gets_a_page_and_nothing_of_the_app():
    """The default server answers one static page (421). It proxies nothing,
    serves no file, and never repeats what the client sent: the page is one
    nginx string with no variable in it."""
    conf = (REPO / "proxy" / "nginx.conf").read_text(encoding="utf-8")
    start = conf.index("listen 80 default_server;")
    block = conf[start : conf.index("\nserver {", start)]
    assert "return 421" in block and "444" not in block
    for directive in ("proxy_pass", "root ", "try_files", "alias "):
        assert directive not in block, directive
    page = block[block.index('return 421 "') + len('return 421 "') :]
    page = page[: page.index('";')]
    assert "$" not in page and '"' not in page
    assert "PUBLIC_ORIGINS" in page and "ALLOWED_HOSTS" in page
    assert "Content-Security-Policy \"default-src 'none'\"" in block
    assert 'Cache-Control "no-store"' in block


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_every_shell_script_is_committed_executable():
    """CI and the docs run the scripts under scripts/ by path. The mode that
    counts is the one in git's index, not the one on disk: this repository
    came from a Windows machine with `core.fileMode` off, where a `chmod`
    never reaches a commit (use `git update-index --chmod=+x`). A script
    committed 100644 fails its job with "Permission denied" before its first
    line. (The images' own scripts are made executable by their Dockerfiles.)"""
    listed = subprocess.run(
        ["git", "ls-files", "-s", "--", "scripts"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0 or not listed.stdout.strip():
        pytest.skip("not a git checkout")
    scripts = {}
    for line in listed.stdout.splitlines():
        mode, _hash, _stage, path = line.split(maxsplit=3)
        if path.endswith(".sh"):
            scripts[path] = mode
    assert "scripts/ci/quick-start-test.sh" in scripts
    assert {path for path, mode in scripts.items() if mode != "100755"} == set()


def test_the_upgrade_job_starts_from_three_releases():
    """One job, three starting points: v0.29.1 (before sign-in), the newest
    published release, and v0.30.0 (the oldest whose archives restore), the
    last two each restoring the old release's own archive in the app. The
    job's name is one of the checks the ruleset on main requires, so it
    stays as it is unless the ruleset changes with it."""
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    job = workflow["jobs"]["upgrade"]
    assert job["name"] == "Upgrade test (v0.29.1 -> this commit)"
    runs = [step.get("run", "").strip() for step in job["steps"]]
    assert "scripts/ci/upgrade-test.sh" in runs
    assert "scripts/ci/upgrade-restore-test.sh latest" in runs
    assert "scripts/ci/upgrade-restore-test.sh 0.30.0" in runs
    script = (REPO / "scripts" / "ci" / "upgrade-restore-test.sh").read_text(encoding="utf-8")
    # The old release is pulled, never taken from a local build's tag, and
    # the build under test is never tagged `latest`.
    assert 'TAG="$FROM_TAG" compose pull' in script
    assert 'TAG="$BUILD_TAG" compose up --build -d' in script
    # The phrase comes from the inspection, not from an assumption.
    assert "confirm_phrase" in script


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR", path.name
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def test_the_web_app_manifest_names_files_that_exist():
    """ "Add to Home Screen" opens Cabinet in a window of its own: the page
    links a manifest, nginx serves it with the manifest type (its own list
    has none for the extension), and every icon it names is in public/ at
    the size it says, in a size for each of the two a phone asks for."""
    public = REPO / "frontend" / "public"
    manifest = json.loads((public / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert manifest["start_url"].startswith(manifest["scope"])
    sizes = set()
    for icon in manifest["icons"]:
        assert icon["src"].startswith("/") and icon["type"] == "image/png"
        width, height = _png_size(public / icon["src"].lstrip("/"))
        assert icon["sizes"] == f"{width}x{height}", icon
        sizes.add((icon["sizes"], icon["purpose"]))
    for size in ("192x192", "512x512"):
        assert (size, "any") in sizes and (size, "maskable") in sizes
    index = (REPO / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="manifest" href="/manifest.webmanifest" />' in index
    conf = (REPO / "proxy" / "nginx.conf").read_text(encoding="utf-8")
    assert "application/manifest+json webmanifest;" in conf


def test_the_page_is_built_knowing_its_release():
    """The web interface carries the version it was built from, so it can
    say when the backend is another release (one image's tag moved and not
    the other's). The version is read from the backend's pyproject.toml, the
    one place it is written, in a local build and in the image's alike."""
    config = (REPO / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert '"../backend/pyproject.toml"' in config and "__CABINET_VERSION__" in config
    dockerfile = (REPO / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    copy = dockerfile.index("COPY backend/pyproject.toml /backend/pyproject.toml")
    assert copy < dockerfile.index("RUN npm run build")
    ignored = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
    assert "backend" not in ignored and "backend/pyproject.toml" not in ignored
    version = (REPO / "frontend" / "src" / "version.ts").read_text(encoding="utf-8")
    assert "__CABINET_VERSION__" in version
