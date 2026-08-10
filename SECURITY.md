# Security Policy

## Supported versions

Cabinet is developed on `main`, and fixes land there. The most recent release
is the supported one.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[security advisory form](https://github.com/jsaumer/cabinet-numismatics/security/advisories/new).
Include what you found, how to reproduce it, and what an attacker could do
with it. You'll get an acknowledgement as soon as it's seen — this is a
personal project, so please allow a few days.

## Scope and design context

Cabinet is a **single-user, self-hosted** application with **no
application-level authentication by design**. It expects to run on a trusted
network, or behind an authenticating reverse proxy (Traefik + Authentik
forward-auth is the documented path). Reports that amount to "the API is
reachable without a login when exposed directly to the internet" describe the
documented deployment model rather than a vulnerability — see
[docs/security.md](docs/security.md).

Things that *are* in scope and worth reporting:

- Any way to read a stored price-source credential back through the API, the
  logs, or a response body — these are encrypted at rest and write-only.
- Path traversal, or any route that serves files outside the photo volume.
- SQL or template injection.
- Stored XSS via item fields, custom fields, tags, or filenames.
- Anything that lets an uploaded file be served or executed as something other
  than a static image.

[docs/security.md](docs/security.md) documents the full model: secrets at
rest, key management and rotation, input handling, and what is deliberately
not encrypted.
