# Troubleshooting

What each failure looks like, and what to change. The messages are quoted
as Cabinet prints them, so searching this page for the words on your screen
should land on the right entry.

## Where to look first

```bash
docker compose ps                    # is each of the three containers up?
docker compose logs --tail 50 backend
docker compose logs --tail 20 proxy
```

Run these from the folder that holds your Compose file. In Portainer,
Dockge, or a NAS's container manager, the same three logs are on each
container's page.

- A backend that refuses to start says why on a line beginning
  `Cabinet cannot start:`, and then restarts and says it again. That line
  names the setting to change.
- Once you are signed in, **Settings → About** shows the version of the
  server and of the web interface, whether the database schema is current,
  and whether documents can be stored.
- After changing `.env`, run `docker compose up -d` again. A `restart` keeps
  the old settings.

## The address

Cabinet answers only at the addresses in `PUBLIC_ORIGINS`, and compares the
whole address: `http` or `https`, the name, and the port. Most first-run
trouble is one of these three.

**"Cabinet isn't set up to answer at this address".** The name in your
browser isn't one Cabinet was told to expect: you used an IP address and
`PUBLIC_ORIGINS` has a name, or the other way round. Put the address from
your browser's address bar in `PUBLIC_ORIGINS`, exactly as it appears
there, and run `docker compose up -d`. Several addresses are separated by
commas. A name that only another container uses (a dashboard reaching
Cabinet as `proxy` or `cabinet-proxy-1`) goes in `ALLOWED_HOSTS` instead.

**"Cabinet refused this address", after you sign in.** The name matches
and the rest doesn't: a port left out (`CABINET_PORT=8080` with
`PUBLIC_ORIGINS=http://nas.local`), or `http` where the setting says
`https`. The page shows the exact value to add. Behind a reverse proxy it
can also mean the proxy changed the address on the way: it has to pass the
original `Host` through, and `PUBLIC_ORIGINS` is the address people type,
not the one the proxy uses to reach Cabinet.

**The browser can't connect at all.** Nothing is listening where you
pointed it. `docker compose ps` shows the port the proxy publishes
(`0.0.0.0:80->80/tcp`); `CABINET_PORT` changes it. If another program
already has the port, the proxy container fails to start and
`docker compose up -d` says the port is already allocated. A
`CABINET_PORT` that starts with `127.0.0.1:` is reachable from that machine
only, on purpose.

## It never finishes starting

**"Cabinet isn't answering yet. It may still be starting; this page checks
again every few seconds."** For the first few seconds after a start this is
normal. If it stays, the backend isn't running: look at
`docker compose logs --tail 50 backend`.

| The log says | What to do |
|---|---|
| `Cabinet cannot start: PUBLIC_ORIGINS is required` | Set `PUBLIC_ORIGINS` to the address you will type. The published-image Compose file defaults it; a build from source needs it in `.env` |
| `PUBLIC_ORIGINS: '...' is not an origin. Each entry is scheme://host[:port] (http or https), with no path` | Write the entry with `http://` or `https://` in front, and nothing after the port: `http://nas.local:8080`, not `nas.local:8080` and not `http://nas.local:8080/` with a path |
| `AUTH_INSECURE_HTTP is on, which is only allowed when every PUBLIC_ORIGINS entry is http; set AUTH_INSECURE_HTTP=false for an https address` | Add `AUTH_INSECURE_HTTP=false` to `.env`. An `http` and an `https` address can't be listed together while it is `true` |
| `SETUP_CODE must be at least 32 characters` or `repeats one character too often` | Use a random code (`openssl rand -hex 32`), or remove `SETUP_CODE` and read the generated one from the log |
| `SETUP_CODE_FILE '...' cannot be read`, `SSO_CA_FILE '...' cannot be read` | The path is inside the container: the file has to be mounted there and readable by the user the backend runs as (`PUID`, default 1000) |
| `Set BACKUP_KEY_FILE or BACKUP_KEY, not both` | Keep one |
| `BACKUP_KEY: ... is not an age identity`, or `BACKUP_KEY_FILE: The backup key ... is missing` | The key has to be a line beginning `AGE-SECRET-KEY-1`, as `backup-key show` or `backup-key new` printed it. A missing file is never replaced with a new key: put your saved copy back |
| `The trusted-header mode needs all four TRUSTED_ASSERTION_* variables, or none` | Set the ones the message lists, or remove them all |
| `Database not reachable yet; retrying`, many times, then an error | See the next entry |

**"Database not reachable yet; retrying", then "password authentication
failed".** `DB_PASSWORD` in `.env` is no longer the password the database
was created with. Postgres takes the password on its very first start and
keeps it in its volume, so writing a new one to `.env` later (running the
quick start's `echo "DB_PASSWORD=..." > .env` a second time does exactly
this) locks the backend out. Put the original value back. If it is gone
and the collection is empty, `docker compose down -v` removes the volumes
and starts over; **that deletes everything**, so never do it to a
collection you want.

If the error is not about the password, the `db` container itself isn't
healthy: `docker compose logs db` says why (a full disk, most often).

**The proxy exits at once.** Its log ends with a line beginning
`cabinet:`, such as `PUBLIC_ORIGINS: '...' is not an origin` or
`ALLOWED_HOSTS: '...' is not a host name`. `ALLOWED_HOSTS` takes names
only: no `http://`, no port.

**It worked, then stopped answering after I rebuilt or recreated only the
backend.** Under Compose, nginx looks the backend's address up once, when
it starts. `docker compose restart proxy`, or bring the whole stack up
together with `docker compose up -d`.

## Setting up and signing in

**Where is the setup code?**

```bash
docker compose logs backend | grep "setup code"
```

Every start makes a new code until the admin account exists, so if the
command prints several lines, the last one is current. If you set
`SETUP_CODE` or `SETUP_CODE_FILE` yourself, the log says so and the code is
the one you supplied.

**"That setup code is not right."** Copy the newest code from the log; the
dashes and capitals don't matter. After five wrong codes from one address
you get "Too many attempts. Try again shortly." for up to fifteen minutes,
but the right code is always accepted.

**"A password is 12 to 256 characters."** The admin's password has to be at
least twelve characters long.

**Signing in brings the sign-in form straight back.** The page says "your
browser didn't keep the sign-in cookie". On a plain `http` address that
means Cabinet is sending cookies marked for `https` only, which a browser
drops without a word: set `AUTH_INSECURE_HTTP=true` and start Cabinet
again, or reach it over `https`. (The published-image Compose file sets it
to `true`; a build from source without it in `.env` gets `false`.) If the
address is `https` already, the browser is refusing cookies from it.

**"Wrong username or password."** The same answer covers a mistyped
username, on purpose. A few wrong tries add a short wait ("Too many
attempts. Try again shortly."); nothing ever locks the account for good.

**I forgot the password.** Whoever can run commands in the container is the
owner. This asks for a new password twice, signs every browser out, and
clears the waits:

```bash
docker compose exec backend python -m app.cli reset-password
```

**My sign-in provider is down, or misconfigured, and I can't get in.** The
password form on the sign-in page always works; single sign-on never
replaces it, and the page never sends you to a provider by itself. To take
a broken provider or gateway mode out of the picture altogether, switch
them all off from the container and use the password:

```bash
docker compose exec backend python -m app.cli disable-sso
```

**"Cross-site request refused." from a script.** That is the answer to a
request that carries a session cookie from somewhere other than Cabinet's
own pages. Scripts and dashboards should use an API token from Settings →
Account (`Authorization: Bearer cabinet_...`), not a browser's cookie.

## After an upgrade

**"This page is Cabinet X and the server is Y."** A tab that was open
during the upgrade is still running the old interface: press the button to
reload. If it says so again, the two images are on different versions.
Both `cabinet-numismatics-backend` and `cabinet-numismatics-proxy` have to
be on the same tag; with the Compose files that is one `TAG` in `.env`, and
on a Swarm or in a stack manager it is two image lines to change, not one.

**Settings → About says "migration pending".** The backend applies
database migrations itself when it starts, so this means it hasn't
restarted since the upgrade, or `AUTO_MIGRATE=false` is set and the
migration is yours to run
([deployment.md](deployment.md#1-install)).

**It says the schema is "newer than this build".** An older image is
running against a database a newer one already migrated. Go back to the
newer version; Cabinet doesn't migrate downward.

## Photos and documents

**"Documents can't be stored: ... isn't a mounted volume".** Cabinet won't
keep a receipt inside the container, where the next upgrade would delete
it. The three Compose files in the repository mount a volume at
`/data/documents`; a stack written by hand, or a Swarm bind that points at
a folder that doesn't exist, doesn't. Settings → About shows the state.

**Photos are broken images.** Photos are served only to a signed-in
browser, so a photo's address opened in another browser, or pasted into a
chat, shows nothing. If they are broken inside Cabinet itself for a moment
after a restart, the backend was still starting; reload.

**A photo upload is refused.** The limit is 25 MB a file, and 64
megapixels: "The image is too large: more than 64 megapixels. Save a
smaller copy and add that." JPEG, PNG, and WebP are accepted; a phone's
HEIC file has to be converted first.

**"Importing from private or local network addresses isn't allowed".** The
URL import fetches only from public addresses, so a link to a file on your
own network is refused. Save the file and upload it.

**The webcam button, the Copy buttons, or "install as an app" do
nothing.** Browsers switch those off on a plain `http` address other than
`localhost`. They need HTTPS:
[https-private-network.md](https-private-network.md).

## Values

A piece shows "unpriced" until a source can price it, and each source says
what it is missing when you ask it for a value on the piece's page.
**Insights → Pricing** lists the same reasons for the whole collection.

| The message | What it needs |
|---|---|
| `No precious metal found in composition. Set it to e.g. '90% silver'` | Melt value reads the metal from the composition: write gold, silver, platinum, or palladium there |
| `Set the item's weight to estimate melt value`, `Set fineness (or a percentage in composition) to estimate melt value` | The weight and the fineness of the piece |
| `Add a Numista API key in Settings to price items from Numista` | A free key from Numista, saved in Settings → Pricing |
| `Add a 'numista' catalog reference (e.g. N#1234) to price this item` | The piece's Numista number, which filling it from Numista adds for you |
| `Set the item's grade: Numista quotes prices per grade` | A grade on the piece |
| `Add a PCGS cert number, or a 'pcgs' catalog reference, to price this item` | The cert number on the holder |
| `Numista rejected the API key. Check it in Settings`, `PCGS rejected the API token. Check it in Settings` | The saved key is wrong or has expired. PCGS tokens expire; make a new one |
| `Numista request quota exhausted. Try again later`, `PCGS request quota exhausted. Try again tomorrow` | The service's own limit (Numista counts by the month, PCGS by the day). Values already fetched stay |

Neither Numista nor PCGS prices a proof or mint set, and PCGS prices coins
only. [price-sources.md](price-sources.md) has what each source covers.

## Backups and restore

**"Cabinet cannot tell where your backup key is stored relative to your
backups", or "Your backup key is stored beside your backups".** On a
default install both are true: the key Cabinet generated and the archives
it writes are on Docker volumes on one disk. That is fine as long as the
archives stay there. It matters the moment they are copied anywhere else,
because an archive is only as private as its key is separate from it, and
only as useful as your copy of the key. Print the key and keep it in a
password manager; the notice goes away for good when you supply the key
yourself (`BACKUP_KEY` in `.env`, or `BACKUP_KEY_FILE`).

```bash
docker compose exec backend python -m app.cli backup-key show
```

**I lost the backup key.** There is no recovery: nobody, the project
included, can open archives made with it. A running Cabinet still has the
key, so print it now with the command above and take a fresh backup. If
the key is gone from the running Cabinet too, the collection itself is
untouched: supply a new key yourself (`backup-key new` prints one; its
`AGE-SECRET-KEY-1` line goes in `.env` as `BACKUP_KEY`), save a copy this
time, and back up again.

**"Backup failed: The backup key ... is missing."** The key file isn't
where it was: a state volume was recreated, or a mounted secret went away.
Put your saved copy back. Cabinet never invents a replacement, since that
would leave every older archive unreadable without anyone noticing.

**"This archive can't be opened with your backup key: it was made with
another key, or it has been altered."** The Cabinet you are restoring into
has a different key from the one that wrote the archive. Start it with the
old key: one line in `.env`, `BACKUP_KEY=AGE-SECRET-KEY-1...`.

**"This is an unencrypted archive from before v0.30.0."** Cabinet restores
only encrypted archives. Take a new backup on the old installation after
upgrading it, and restore that.

**"This archive was made by a newer Cabinet ... Upgrade Cabinet first,
then restore."** As it says: an older release can't read a newer one's
archive.

**It asks me to type RESTORE OLDER.** The archive is older than the newest
backup this Cabinet has made, so restoring it goes back past newer work.
That is a second look, not a refusal.

**"Not enough space to open this archive".** A restore unpacks the archive
before it replaces anything, so it needs room for the archive, its
database, and a second copy of the photos while it works.

**"An earlier restore left files in .../.restore-old."** A previous
restore was interrupted after it had moved the old files aside, and that
folder may hold the only copy of them. Look inside before you remove it.

**"Cabinet can't replace the files in ...: ... aren't writable by the user
the backend runs as".** Some folders on the photo or document volume
belong to another account, usually `root`. Restart the backend, which
hands over what it can, or run `chown -R` on the folder to the `PUID` and
`PGID` the backend uses.

**`restore.sh` says "... is not a file".** The script reads the archive's
path from the folder that holds your Compose file, so name the folder too:
`./scripts/restore.sh backups/cabinet-backup-....zip.age`. It also needs
`unzip` and `sha256sum` on the host, and the containers running.

[backup-restore.md](backup-restore.md) has the whole procedure.

## Sharing

**A share link shows my gateway's sign-in page.** An authenticating proxy
in front of Cabinet guards every path unless told otherwise, share links
included. Exempt `/s/`, `/api/share/`, and `/robots.txt` from its check:
[deployment.md](deployment.md#sharing-and-the-forward-auth-exemption).

**"This link isn't active."** The link was revoked or regenerated, the set
or checklist it showed was deleted, or sharing is switched off in Settings
→ Sharing. Every one of those looks the same to a visitor, on purpose.

**"Switch sharing on in Settings first."** Links can't be made while the
switch in Settings → Sharing is off.

## Files on a NAS or a bind mount

**The backend's log begins with `WARNING:  /data/... is not writable by
1000:1000`, then `staying root`.** The backend runs as an unprivileged
user (`PUID`:`PGID`, default `1000`:`1000`) and couldn't take ownership of
a data folder, which is usual on an NFS export that squashes root. Set
`PUID` and `PGID` to the account that owns the folders on the NAS, or
change the folders' owner to match.

## Still stuck

Open an issue at
<https://github.com/jsaumer/cabinet-numismatics/issues> with the version
(Settings → About, or the image tag), how you run Cabinet (the published
Compose file, from source, a Swarm, a stack manager), the output of
`docker compose ps`, and the last fifty lines of the backend's log. Leave
out the setup code, any API token or key, and your real address.

For anything that looks like a security problem, don't open an issue:
[SECURITY.md](../SECURITY.md) says how to report it privately.
