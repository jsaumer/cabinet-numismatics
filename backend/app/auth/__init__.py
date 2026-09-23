"""Sign-in (v0.30.0): the credential services (`passwords`, `sessions`,
`tokens`, `devices`, `throttle`, `audit`, `notify`) and `accounts`, which
puts them together for the routes and the container commands.

Everything here stores only hashes of secrets and never logs a password, a
setup code, or a token secret. See docs/specs/SPEC_0300.md, section 5.
"""
