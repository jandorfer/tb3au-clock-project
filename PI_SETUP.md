# Provisioning the Raspberry Pi

This document ties together everything needed to stand up the tb3au e-ink
clock on a Raspberry Pi **from this repo alone**. SSH access to *this specific*
Pi (host / user / key) is documented in `PI_ACCESS.md` (gitignored, local only
— it never leaves your machine).

## Prerequisites
- A Pi with SPI + GPIO enabled (`sudo raspi-config → Interface Options`).
- Raspberry Pi OS (tested on Bullseye / Python 3.9).
- An SSH key trusted by the Pi (see `PI_ACCESS.md`).
- Home Assistant with the Mosquitto broker add-on (for MQTT push).

## One-command bootstrap
From the repo root on the Pi:

```bash
deploy/setup_pi.sh
```

It performs, idempotently:
1. `git submodule update --init` (Waveshare SDK)
2. `python3 -m pip install -r requirements.txt`
3. installs + enables the `tb3au-mqtt.service` systemd unit
4. makes `tb3au.sh` executable
5. installs the two cron jobs (daily joke at midnight + 15-min auto-update
   via `deploy/auto_update.sh`)

The installed 15-minute cron runs `deploy/auto_update.sh`, which also
auto-installs Python dependency changes (`requirements.txt`) and restarts the
daemon when code / unit / SDK change — so a dependency version bump needs no
manual step.

## Then configure secrets
Create `.env` from the template and fill it in (see README §3):

```bash
cp .env.example .env
# edit OPENAI_API_KEY, API_NINJAS_KEY, MQTT_BROKER, MQTT_USER, MQTT_PASSWORD
```

Then restart the daemon so it reads the new values:

```bash
sudo systemctl restart tb3au-mqtt.service
```

## Reference (in README.md)
- §1 Clone + submodule
- §2 Python dependencies
- §3 `.env` / secrets
- §4 Run manually
- §5 Automatic daily refresh (cron) — `tb3au.sh` + auto-pull
- §6 Push from Home Assistant (MQTT topics / payloads)
- §7 Run the MQTT daemon (systemd)

## MQTT broker in Home Assistant
Create a **dedicated HA user** (Settings → People) with Mosquitto access, then
put its credentials in `.env`. The daemon connects to `MQTT_BROKER` (use the HA
machine's LAN IP on a Pi that is **not** the HA host) and publishes
`tb3au/status = online`. Full schema in `MQTT_DESIGN.md`.

## Notes / caveats
- **Do not edit tracked files directly on the Pi if you also push from another
  machine** — the auto-pull uses `git pull --ff-only`, which refuses a divergent
  local history. Edit on your dev machine, commit, push.
- **After a force-push** (e.g. a history rewrite) the Pi's `--ff-only` pull will
  fail. On the Pi, resync with:
  ```bash
  git fetch origin && git reset --hard origin/main
  ```
  (untracked files like `.env` are preserved). Then re-run `deploy/setup_pi.sh`
  if the unit file changed.
- The daily cron job keeps running independently of the MQTT daemon.
- The HA broker user / password and the OpenAI / API-Ninjas keys are
  environment-specific secrets and are **not** committed (they live in `.env`,
  which is gitignored).
