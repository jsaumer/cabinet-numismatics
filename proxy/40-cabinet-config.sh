#!/bin/sh
# Cabinet: nginx's generated configuration (run by the nginx image's
# entrypoint before nginx starts). Writes two files into
# $CABINET_NGINX_DIR (default /etc/nginx/cabinet):
#
# hosts.conf: the server_name of Cabinet's one real server block: the hosts
# of PUBLIC_ORIGINS (the names browsers use) plus ALLOWED_HOSTS (internal
# names such as cabinet_proxy, localhost, or a LAN name). Any other Host gets
# no answer at all (444, the default server).
#
# cabinet-identity.conf (v0.33.0): one proxy_set_header line for every
# identity header a forward-auth or SSO gateway adds, each set to "" so a
# client can never send one through to the backend, except the one header
# TRUSTED_ASSERTION_HEADER names, which is passed on as the client sent it
# (the gateway's signed assertion, which the backend verifies). Unset, every
# name is blanked. Every proxied location includes it through
# cabinet-proxy.conf.
#
# A bad value exits non-zero, which stops the container before nginx serves
# anything.
set -eu
set -f # no glob expansion of the values below

dir=${CABINET_NGINX_DIR:-/etc/nginx/cabinet}
fail() {
    echo "cabinet: $*" >&2
    exit 1
}

# --- the identity headers ---------------------------------------------------

# Identity headers that forward-auth and SSO gateways add (Authentik,
# Authelia, oauth2-proxy, Pomerium, Cloudflare Access, Google IAP), blanked
# whoever sent them. nginx can't wildcard a header name, so the list is
# explicit. Version 2 (v0.33.0): X-Goog-IAP-JWT-Assertion added, since every
# assertion header the trusted-header mode supports must be on it (CR-18).
identity_headers="
Remote-User
Remote-Groups
Remote-Email
Remote-Name
X-Forwarded-User
X-Forwarded-Email
X-Forwarded-Preferred-Username
X-Forwarded-Groups
X-authentik-username
X-authentik-groups
X-authentik-email
X-authentik-name
X-authentik-uid
X-authentik-jwt
X-authentik-meta-jwks
X-authentik-meta-outpost
X-authentik-meta-provider
X-authentik-meta-app
X-authentik-meta-version
X-Auth-Request-User
X-Auth-Request-Email
X-Auth-Request-Preferred-Username
X-Auth-Request-Groups
X-Auth-Request-Access-Token
X-Pomerium-Jwt-Assertion
Cf-Access-Authenticated-User-Email
Cf-Access-Jwt-Assertion
X-Goog-IAP-JWT-Assertion
"

# Headers nginx sets or the gate reads (R2-14): passing a client's copy of
# one of these would override nginx's own. A trailing * is a prefix. The
# backend refuses the same list (app/config.py, TRUSTED_HEADER_FORBIDDEN; a
# test keeps the two equal).
forbidden="host cookie authorization origin referer sec-fetch-* content-length content-type transfer-encoding connection upgrade x-real-ip x-forwarded-* forwarded"

lower() { printf '%s' "$1" | tr 'A-Z' 'a-z'; }

assertion=${TRUSTED_ASSERTION_HEADER:-}
wanted=""
if [ -n "$assertion" ]; then
    printf '%s' "$assertion" | grep -Eq '^[A-Za-z][A-Za-z0-9-]{1,60}$' ||
        fail "TRUSTED_ASSERTION_HEADER: '$assertion' is not a header name (a letter, then 1 to 60 letters, digits, or dashes)"
    wanted=$(lower "$assertion")
    for entry in $forbidden; do
        case $wanted in
            $entry) fail "TRUSTED_ASSERTION_HEADER may not be '$assertion': nginx sets that header or Cabinet's gate reads it" ;;
        esac
    done
fi

identity=""
passed=""
nl='
'
for name in $identity_headers; do
    if [ -n "$wanted" ] && [ "$(lower "$name")" = "$wanted" ]; then
        var=$(lower "$name" | sed 's/-/_/g')
        identity="${identity}proxy_set_header $name \$http_$var;$nl"
        passed=$name
    else
        identity="${identity}proxy_set_header $name \"\";$nl"
    fi
done
if [ -n "$wanted" ] && [ -z "$passed" ]; then
    # The gateway may use a name not on the list; it is still passed on.
    var=$(printf '%s' "$wanted" | sed 's/-/_/g')
    identity="${identity}proxy_set_header $assertion \$http_$var;$nl"
    passed=$assertion
    echo "cabinet: TRUSTED_ASSERTION_HEADER $assertion is not on Cabinet's list of identity headers; passing it on anyway"
fi

# --- the host names ---------------------------------------------------------

names=""
add() { # $1 = variable name, $2 = host
    host=$(lower "$2")
    if [ "$host" = "_" ] || ! printf '%s' "$host" |
        grep -Eq '^[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?(\.[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?)*$'; then
        fail "$1: '$2' is not a host name (letters, digits, dots, dashes, and underscores; no scheme, port, or path)"
    fi
    case " $names " in
        *" $host "*) ;;
        *) names="$names $host" ;;
    esac
}

for origin in $(printf '%s' "${PUBLIC_ORIGINS:-}" | tr ',' ' '); do
    printf '%s' "$origin" | grep -Eq '^[Hh][Tt][Tt][Pp][Ss]?://[^:/?#@]+(:[0-9]{1,5})?$' ||
        fail "PUBLIC_ORIGINS: '$origin' is not an origin (scheme://host[:port], no path)"
    rest=${origin#*://}
    add PUBLIC_ORIGINS "${rest%%:*}"
done
for host in $(printf '%s' "${ALLOWED_HOSTS:-}" | tr ',' ' '); do
    add ALLOWED_HOSTS "$host"
done

[ -n "$names" ] || fail "PUBLIC_ORIGINS is required (the address browsers use for Cabinet); ALLOWED_HOSTS adds internal names"

# --- write ------------------------------------------------------------------

mkdir -p "$dir"
printf 'server_name%s;\n' "$names" >"$dir/hosts.conf.new"
mv "$dir/hosts.conf.new" "$dir/hosts.conf"
{
    echo "# Generated by 40-cabinet-config.sh at container start; do not edit."
    printf '%s' "$identity"
} >"$dir/cabinet-identity.conf.new"
mv "$dir/cabinet-identity.conf.new" "$dir/cabinet-identity.conf"

echo "cabinet: answering Host$names; any other Host gets no response"
if [ -n "$passed" ]; then
    echo "cabinet: passing the trusted assertion header $passed to the backend; every other identity header is blanked"
else
    echo "cabinet: every identity header is blanked (TRUSTED_ASSERTION_HEADER is unset)"
fi
