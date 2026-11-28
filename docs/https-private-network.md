# HTTPS on a private network

The quick start gets Cabinet running over plain http, which is fine for a
first look. Before you rely on it, put HTTPS in front. Over plain http:

- your password, and the cookie that keeps you signed in, cross your
  network readable by anything else on it;
- browsers switch off some features outside HTTPS: taking a photo with the
  webcam, the Copy buttons, and installing Cabinet as an app ("Add to Home
  Screen") don't work (they do on `localhost`).

None of the three ways below needs Cabinet to be reachable from the
internet, and none should make it so. Cabinet is for private networks; see
[the exposure advisory](deployment.md#2-exposure-cabinet-is-for-private-networks).

## What Cabinet needs from whatever serves HTTPS

Whichever you pick, the settings are the same (in the `.env` beside your
Compose file, then `docker compose up -d`):

```
PUBLIC_ORIGINS=https://cabinet.home.arpa
AUTH_INSECURE_HTTP=false
CABINET_PORT=127.0.0.1:8080
```

- **`PUBLIC_ORIGINS`** is the exact address you will type, `https://`
  included, and the port if it isn't 443.
- **`AUTH_INSECURE_HTTP=false`** makes the sign-in cookies HTTPS-only. Left
  at `true` beside an https address, the backend stops and says so in
  `docker compose logs backend`.
- **`CABINET_PORT=127.0.0.1:8080`** publishes Cabinet's own port on this
  machine only, so the one way in from your network is the HTTPS one. Use
  it when the HTTPS proxy runs on the same host; leave the plain port
  (`8080`) when it runs elsewhere.
- **The proxy has to pass the name through.** Cabinet answers by the `Host`
  it is sent. Caddy, Traefik, and Tailscale pass it unchanged; with nginx
  as the outer proxy add `proxy_set_header Host $host;`. If you get a page
  headed "Cabinet isn't set up to answer at this address", the name
  reaching Cabinet isn't the one in `PUBLIC_ORIGINS`; if you can sign in
  and then get "Cabinet refused this address", the name is right and the
  scheme or the port isn't
  ([troubleshooting.md](troubleshooting.md#the-address)).

You will have to sign in again after the switch: cookies belong to an
address. Share links keep working at the new address, and a single sign-on
provider needs the new callback address (Settings → Sign-in shows it).

## 1. Caddy with its own certificates

The least to set up, and it needs no domain and no account anywhere. Caddy
makes its own certificate authority and issues a certificate for the name
you give it. The cost: every device that opens Cabinet has to be told once
to trust that authority.

`Caddyfile`:

```
cabinet.home.arpa {
	tls internal
	reverse_proxy 127.0.0.1:8080
}
```

Run Caddy on the same host, on the host's network so it can reach
`127.0.0.1:8080`:

```bash
docker run -d --name caddy --restart unless-stopped --network host \
  -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" -v caddy_data:/data caddy:2
```

Then two things on your network:

1. **The name has to resolve** to the server from your other devices: a
   local DNS record on your router or Pi-hole, or a line in each device's
   hosts file. `.home.arpa` is the suffix reserved for home networks; any
   name you control works.
2. **Trust Caddy's authority** on each device. Copy the root certificate
   out and install it as a trusted root (the steps differ by system):

   ```bash
   docker cp caddy:/data/caddy/pki/authorities/local/root.crt caddy-root.crt
   ```

   Until a device trusts it, its browser shows a certificate warning.

*Checked for this page on 26 November 2026 with Caddy 2.11: Cabinet claimed
and signed in through it, with HTTPS-only cookies, and the plain port
refused by name.*

## 2. Tailscale Serve

If the machine is on a Tailscale network, Tailscale can serve Cabinet over
HTTPS at the machine's own `ts.net` name, with a certificate browsers
already trust, to devices on your tailnet only. Nothing to install on the
other devices beyond Tailscale itself.

```bash
tailscale serve --bg 8080
tailscale serve status     # shows the https address
```

```
PUBLIC_ORIGINS=https://your-machine.your-tailnet.ts.net
AUTH_INSECURE_HTTP=false
CABINET_PORT=127.0.0.1:8080
```

Use **Serve**, never **Funnel**: Funnel publishes to the internet, which is
exactly what Cabinet should not be.

*Not checked for this page: there was no tailnet to try it on. The commands
are Tailscale's own; see its documentation for Serve if they have changed.
If Cabinet shows its "not at this address" page, Tailscale is passing a
different name than the one in the address bar: add the name it uses to
`ALLOWED_HOSTS`.*

## 3. A real certificate for a private name

If you own a domain, a public certificate authority can issue a
certificate for a name that only resolves inside your network. The proof
of ownership goes through a DNS record (the "DNS-01" challenge), so
nothing has to be reachable from outside. Devices trust it with no extra
step.

- Point a name at the server's private address, in your public DNS or
  only in your network's own DNS: `cabinet.example.com` to `192.168.1.50`.
- Have your reverse proxy get the certificate by DNS challenge. Caddy does
  it with a build that includes your DNS provider's module; Traefik with
  `dnsChallenge` on its certificate resolver. Both need an API token for
  your DNS provider.
- Set `PUBLIC_ORIGINS=https://cabinet.example.com` and the other two lines
  above.

The plain "HTTP-01" challenge that many guides show needs port 80 open to
the internet. Don't use it for Cabinet.

*Not checked for this page: it needs a domain and a DNS provider account.*

## Already running a reverse proxy?

Traefik, nginx, or another proxy you already run does the same job; the
four points at the top are all Cabinet needs from it.
[deployment.md](deployment.md#4-tls-single-sign-on-and-an-optional-gateway-in-front)
has a Traefik example, upload limits for large restores, and single
sign-on.
