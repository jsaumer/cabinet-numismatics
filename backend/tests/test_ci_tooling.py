"""The CI-only mock provider stays off the LAN (SPEC_0330 section 19, CX-01):
it approves anyone as its current subject and signs assertions for whoever
asks, so its published port must bind to loopback alone. The stack's own
port is published the way the product publishes it; the mock is not the
product."""

import re
from pathlib import Path

REPO = Path(__file__).parents[2]


def test_ci_mock_is_published_on_loopback_only():
    text = (REPO / "docker-compose.ci.yml").read_text(encoding="utf-8")
    published = re.findall(r'^\s*-\s*"([^"]+)"\s*$', text, re.M)
    ports = [p for p in published if re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}:\d+:\d+|\d+:\d+", p)]
    assert ports == ["127.0.0.1:8555:8555"], ports
