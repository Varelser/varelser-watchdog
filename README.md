# varelser-watchdog

Tiny uptime watchdog that runs on Deplexo's free tier (0.25 CPU / 128 MB).

- Serves a status page on `$PORT`
- Checks the public pages in `CHECK_URLS` every `CHECK_INTERVAL_SEC` seconds (default 300)
- Posts to `DISCORD_WEBHOOK_URL` when a site is down (2 consecutive failures) or recovers
- Standard library only; no dependencies

Open `/test-alert` on the deployed URL to send a test Discord notification.
