# Server deployment assets

Files installed on the WHM production server. See [DEPLOYMENT.md](../DEPLOYMENT.md) Part 10 for
the server layout and [SHOPIFY_WEBHOOK_LIVE.md](../SHOPIFY_WEBHOOK_LIVE.md) for what the sync does.

| File | Purpose |
|---|---|
| `shopify-sync.sh` | Catch-up sync wrapper — locking, log trimming. Runs from the deployed checkout, so it updates itself on every deploy. |
| `systemd/bolderp-shopify-sync.service` | Oneshot unit that runs the wrapper |
| `systemd/bolderp-shopify-sync.timer` | Fires it every 10 minutes |

## The catch-up poll

Shopify **never replays a webhook it failed to deliver**, so any gap — a wrong URL, a rotated
signing secret, a few minutes of downtime — loses those orders permanently unless something
polls. This poll is that backstop.

It is safe to run repeatedly: `ingest_order` upserts on `shopify_order_id`, an already-reserved
line is not reserved twice, and a line a print batch has claimed is left alone
(`RESYNCABLE_LINE_STATUSES` in `core/services/shopify.py`).

Currently installed as a **cron job for the `bolderp` user**, because installing a systemd unit
needs root and the deploy account's root sudo is scoped to `systemctl`/`journalctl` for
`bolderp.service` only. The systemd units below are the preferred form if you have root.

### Currently installed (cron)

```bash
sudo -u bolderp crontab -l          # inspect
tail -f /opt/bolderp/logs/shopify-sync.log
```

To change the schedule or remove it:

```bash
sudo -u bolderp crontab -e          # edit
sudo -u bolderp crontab -r          # remove entirely
```

### Switching to systemd (needs root)

```bash
cp /opt/bolderp/app/deploy/systemd/bolderp-shopify-sync.* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bolderp-shopify-sync.timer

# Remove the cron job so the two do not both run
crontab -u bolderp -r

# Verify
systemctl list-timers 'bolderp*'
systemctl start bolderp-shopify-sync.service   # run one now
journalctl -u bolderp-shopify-sync -n 30 --no-pager
```

Both routes call the same `shopify-sync.sh`, which takes an exclusive `flock` — so if you ever
leave both enabled the runs will skip rather than collide, but you should still remove one.

## Tuning

`shopify-sync.sh` reads these from the environment, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `BOLDERP_SYNC_LOOKBACK` | `30` | Minutes of history to re-fetch each run. Keep it well above the interval so a skipped run cannot leave a gap. |
| `BOLDERP_LOG_DIR` | `/opt/bolderp/logs` | Where `shopify-sync.log` is written |
| `BOLDERP_SYNC_LOG_LINES` | `2000` | Log is trimmed to this many lines after each run |
| `BOLDERP_APP_DIR` | `/opt/bolderp/app` | Django project root |
| `BOLDERP_PYTHON` | `/opt/bolderp/venv/bin/python` | Interpreter |

Shopify credentials are **not** listed here: the script runs `manage.py`, so Django loads
`SHOPIFY_SHOP_DOMAIN`, `SHOPIFY_ADMIN_API_TOKEN` and `SHOPIFY_API_VERSION` from
`/opt/bolderp/app/.env` exactly as the web process does. There is one copy of the secrets.
