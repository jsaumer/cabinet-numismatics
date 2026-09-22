#!/bin/sh
# Cabinet: which Host names nginx answers (run by the nginx image's
# entrypoint before nginx starts). Writes /etc/nginx/cabinet/hosts.conf, the
# server_name of Cabinet's one real server block: the hosts of PUBLIC_ORIGINS
# (the names browsers use) plus ALLOWED_HOSTS (internal names such as
# cabinet_proxy, localhost, or a LAN name). Any other Host gets no answer at
# all (444, the default server). A bad value exits non-zero, which stops the
# container before nginx serves anything.
set -eu
set -f # no glob expansion of the values below

out=/etc/nginx/cabinet/hosts.conf
fail() {
    echo "cabinet: $*" >&2
    exit 1
}

names=""
add() { # $1 = variable name, $2 = host
    host=$(printf '%s' "$2" | tr 'A-Z' 'a-z')
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

mkdir -p "$(dirname "$out")"
printf 'server_name%s;\n' "$names" >"$out"
echo "cabinet: answering Host$names; any other Host gets no response"
