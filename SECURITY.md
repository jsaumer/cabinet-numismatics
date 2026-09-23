# Security Policy

## Supported versions

Cabinet is developed on `main`, and fixes land there. The most recent release
is the supported one.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[security advisory form](https://github.com/jsaumer/cabinet-numismatics/security/advisories/new).
Include what you found, how to reproduce it, and what an attacker could do
with it. You'll get an acknowledgement as soon as it's seen. This is a
personal project, so please allow a few days.

## Scope and design context

Cabinet is a **single-user, self-hosted** application. Every route needs a
sign-in or an API token (v0.30.0): one admin, database-backed sessions,
scoped API tokens, and a deny-by-default gate. It is still designed to run
on a trusted network, or behind an authenticating reverse proxy as a second
door until single sign-on (v0.33.0) ships; see
[docs/security.md](docs/security.md). Reports that amount to "the API is
reachable without a login when exposed directly to the internet" describe a
real bug now, not the documented deployment model, since v0.30.0.

Things that *are* in scope and worth reporting:

- Any way to reach a route without a valid session or API token, or to act
  outside what a token's scope allows.
- Any way to bypass the CSRF check, guess or forge a session or token, or
  read another user's session or token.
- Any way to read the setup code, a password, or a stored price-source
  credential back through the API, the logs, or a response body: passwords
  are hashed, and credentials are encrypted at rest and write-only.
- Any way to read or forge a backup archive without the backup key.
- Path traversal, or any route that serves files outside the photo volume.
- SQL or template injection.
- Stored XSS via item fields, custom fields, tags, or filenames.
- Anything that lets an uploaded file be served or executed as something other
  than a static image.

[docs/security.md](docs/security.md) documents the full model: authentication,
secrets at rest, key management and rotation, input handling, and what is
deliberately not encrypted.
