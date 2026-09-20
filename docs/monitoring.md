# Alerts, heartbeat, and metrics

Cabinet's scheduled work (backups, price refreshes, the trash clear-out)
runs inside the backend with nobody watching. Three things report on it,
all set in **Settings → Alerts & metrics** and all off until configured:

- **Alerts**: a webhook when something starts failing, and again when it's
  working.
- **Heartbeat**: an hourly push to an Uptime Kuma *Push* monitor, which also
  notices Cabinet not running at all.
- **Metrics**: a Prometheus endpoint at `/api/metrics`.

A [Homepage](#homepage-gethomepagedev) tile needs no setting at all: it
reads the same statistics the dashboard does.

## Alerts

| Check                     | Fails when                                                   | Recovers when                          |
|---------------------------|--------------------------------------------------------------|----------------------------------------|
| Backups                   | a scheduled or **Back up now** backup fails                  | the next backup succeeds               |
| Numista API key           | Numista answers 401/403                                      | Numista next answers a request         |
| Numista request quota     | Numista answers 429                                          | Numista next answers a request         |
| PCGS API token            | PCGS answers 401, or 500 (PCGS's way of saying the token is bad) | PCGS next answers a request        |
| PCGS request quota        | PCGS answers 429                                             | PCGS next answers a request            |
| Scheduled melt / Numista / PCGS refresh | a scheduled refresh run has any failed item    | a run finishes with none               |

An alert is sent **on the change only**: once when a check starts failing,
once when it recovers. A rejected key that stays rejected doesn't alert again
every refresh; its message is kept up to date in Settings. A rejected key or
exhausted quota also **stops a scheduled refresh** at the first refusal, because
every remaining request would fail the same way, and the quota is better
spent after the fix. Key and quota checks fire even when cached data covers
for the failure, since the next refresh will need the key.

Items a source can't price (no catalogue number, a proof on Numista) are
skipped, not failed, so they never raise a refresh alert. The same goes for
a 403 from Numista's paid auction-sales endpoint on a free key: the item
page says sales records need the paid plan, and no key alert is raised.

### Formats

One URL, in one of five formats. The URL is stored encrypted, like the API
keys, since it usually carries a token; Settings shows only its host.
**Send test** sends a test alert and shows the result.

| Format             | What's sent                                                                 |
|--------------------|-----------------------------------------------------------------------------|
| Generic JSON       | `POST` `{"app": "cabinet", "alert", "label", "status", "title", "message", "at"}`, for n8n, Home Assistant, Node-RED |
| ntfy               | `POST` to the topic URL: the message as the body, `Title`, `Priority` (high when failing), and `Tags` headers. A protected topic takes `?auth=…` in the URL |
| Discord            | `POST` `{"username": "Cabinet", "content": "**title**\nmessage"}` to a channel webhook |
| Slack / Mattermost | `POST` `{"text": "*title*\nmessage"}` to an incoming webhook                 |
| Gotify             | `POST` `{"title", "message", "priority"}` to `/message?token=<app token>`   |

`status` is `failing`, `recovered`, or `test`; `alert` is one of `backup`,
`numista_key`, `numista_quota`, `pcgs_key`, `pcgs_quota`, `refresh_melt`,
`refresh_numista`, `refresh_pcgs` (or `test`). An example:

```json
{
  "app": "cabinet",
  "alert": "backup",
  "label": "Backups",
  "status": "failing",
  "title": "Cabinet: Backups failing",
  "message": "Backup failed: pg_dump failed: connection refused",
  "at": "2026-09-18T03:15:02.114Z"
}
```

Delivery happens in the background with a 10-second timeout; a failed
delivery is logged (without the URL) and shown in Settings, and not retried.
The check's state is kept either way, so the metrics and heartbeat still see
it.

## Heartbeat (Uptime Kuma)

An alert can't report that Cabinet itself stopped. For that, add a monitor
of type **Push** in Uptime Kuma, give it a heartbeat interval of **at least
65 minutes** (Cabinet pushes hourly, starting five minutes after it
starts), and paste its push URL into Settings → Heartbeat.

Each push is `status=up&msg=OK` while nothing is failing, and
`status=down` with the failing checks as the message otherwise, so Kuma goes
red both when Cabinet stops pushing and when something inside it fails.
Kuma's own `status`, `msg`, and `ping` parameters in the pasted URL are
replaced. **Push now** sends one immediately.

## Homepage (gethomepage.dev)

Cabinet needs nothing special for a [Homepage](https://gethomepage.dev)
tile: `GET /api/stats/collection` already returns the owned coins and notes
and the estimated value, in your display currency, and Homepage's
`customapi` widget reads it. In `services.yaml`:

```yaml
- Collections:
    - Cabinet:
        icon: https://cabinet.example.com/logo-512.png
        href: https://cabinet.example.com
        description: Coin and paper money collection
        siteMonitor: https://cabinet.example.com/api/health
        widget:
          type: customapi
          url: https://cabinet.example.com/api/stats/collection
          refreshInterval: 300000 # 5 minutes; the numbers move slowly
          mappings:
            - field: counts.coins
              label: Coins
              format: number
            - field: counts.notes
              label: Notes
              format: number
            - field: estimated_value
              label: Est. value
              format: float
              prefix: "$"
```

The counts are owned pieces (sold and wish-list items are left out, as on
the dashboard), and the value follows Settings → value strategy. Homepage
has no currency format, so `prefix` is the symbol of your display currency.
Other fields the same response carries: `counts.owned`, `counts.wishlist`,
`cost_basis`, `unrealized_gain`, `estimated_items`.

Homepage fetches from its own server, not your browser. If Cabinet sits
behind forward-auth, point `url`, `siteMonitor`, and `icon` at the proxy
service over a Docker network both share (`http://cabinet_proxy/...` on a
Swarm, `http://proxy/...` in one compose project) so the requests skip the
login; keep `href` as the public address. The logo is served at
`/logo.svg`, `/logo-512.png`, and `/favicon.ico`.

## Metrics (Prometheus)

Turn on **Serve metrics at /api/metrics**. Off, the endpoint answers 404.
Values are computed from the database when scraped and cached for a minute,
so scraping more often than that gains nothing.

| Metric | Labels | Meaning |
|--------|--------|---------|
| `cabinet_info` | `version`, `schema` | Always 1 |
| `cabinet_schema_up_to_date` | | 1 when the database is at the revision this build expects |
| `cabinet_items` | `status`, `type` | Items, trash excluded |
| `cabinet_items_in_trash` | | Items in the trash |
| `cabinet_photos`, `cabinet_documents` | | Photos (trash included) and attached documents |
| `cabinet_collection_value` | `currency` | Owned items' value, per the value strategy, in the display currency |
| `cabinet_collection_cost_basis` | `currency` | Owned items' cost, fees included |
| `cabinet_unrealized_gain`, `cabinet_realized_gain` | `currency` | As on the dashboard |
| `cabinet_items_valued` | | Owned items with a value |
| `cabinet_amounts_unconverted` | | Amounts left out of totals for lack of an exchange rate |
| `cabinet_backup_scheduled` | | 1 when scheduled backups are on |
| `cabinet_backup_last_run_timestamp_seconds`, `cabinet_backup_last_run_success` | | The last backup run |
| `cabinet_backup_archives` | | Archives in the backup directory |
| `cabinet_backup_newest_timestamp_seconds`, `cabinet_backup_newest_size_bytes` | | The newest archive |
| `cabinet_refresh_last_run_timestamp_seconds` | `source` | Last scheduled refresh |
| `cabinet_refresh_last_run_items` | `source`, `outcome` | Its updated / skipped / failed items |
| `cabinet_estimate_attempts` | `source`, `outcome` | Each item's latest automatic attempt (`ok`, `not_applicable`, `unavailable`) |
| `cabinet_alert_failing` | `alert` | 1 while that check is failing |
| `cabinet_alert_delivery_success`, `cabinet_heartbeat_success` | | The last delivery / push (after the first one since startup) |

Timestamps are Unix seconds; ages come from PromQL:

```promql
# hours since the newest backup
(time() - cabinet_backup_newest_timestamp_seconds) / 3600
# anything failing
cabinet_alert_failing == 1
```

### Scraping it

The endpoint goes through the proxy like the rest of the API. With
Prometheus on the same Docker network as Cabinet's `proxy` service, scrape it
by service name (in a Swarm stack named `cabinet`, that's `cabinet_proxy`):

```yaml
scrape_configs:
  - job_name: cabinet
    scrape_interval: 60s
    metrics_path: /api/metrics
    static_configs:
      - targets: ["cabinet_proxy:80"]
```

Scraping through the public hostname works too, but an authenticating proxy
(Traefik + Authentik forward-auth) in front will turn Prometheus away unless
`/api/metrics` is exempted. Scraping over the internal network avoids that.

**Like the rest of the API, `/api/metrics` has no login**, and it includes the
collection's value. That's the reason it's off by default. See
[security.md](security.md).
