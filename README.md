# tb3au-clock-project

A Raspberry Pi e-ink clock/quote display. It fetches a daily joke from the
[API-Ninjas](https://api-ninjas.com) jokes API, generates a matching cartoon
image with OpenAI's `gpt-image-1` model, and renders both the text and the
image onto a **Waveshare 4.2" e-Paper display** (400×300).

## Hardware

- Raspberry Pi (tested on a Pi 1/Zero-class board, armv6l)
- Waveshare 4.2" e-Paper (V2, `epd4in2_V2`) connected over SPI
- SPI and GPIO must be enabled (`sudo raspi-config → Interface Options`)

## Repository layout

```
tb3au.py            # main script: joke + AI image -> e-paper
peppe8o-paper.py    # hardware/drawing demo (not used in production; 2.13" panel)
e-Paper/            # Waveshare SDK  -> GIT SUBMODULE (see below)
.env                # local secrets  -> gitignored, NOT committed
```

> **`e-Paper/` is a git submodule**, pinned to a specific commit of
> [`waveshare/e-Paper`](https://github.com/waveshare/e-Paper). It is **not**
> stored in this repo, so you must initialise it after cloning (step 2).

## 1. Clone (with the SDK submodule)

```bash
git clone https://github.com/jandorfer/tb3au-clock-project.git
cd tb3au-clock-project
git submodule update --init        # fetches the Waveshare SDK into e-Paper/
```

## 2. Python dependencies

```bash
pip install -r requirements.txt
```

The driver also needs `RPi.GPIO` and `spidev` (preinstalled on Raspberry Pi OS,
or `sudo apt install python3-rpi.gpio python3-spidev`).

## 3. Configure secrets (`.env`)

Create a file named `.env` next to `tb3au.py`:

```ini
OPENAI_API_KEY=sk-svcacct-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
API_NINJAS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# MQTT push from Home Assistant (only needed for tb3au_mqtt.py)
MQTT_BROKER=core-mosquitto
MQTT_PORT=1883
MQTT_USER=tb3au
MQTT_PASSWORD=your-mqtt-password
```

- `OPENAI_API_KEY` — an OpenAI API key (the script uses `gpt-image-1`).
- `API_NINJAS_KEY` — from <https://api-ninjas.com/api/jokes>.
- `MQTT_BROKER` / `MQTT_PORT` — the Mosquitto broker HA runs. On a Pi that is
  **not** the HA host, use the HA machine's LAN IP. On HAOS the broker
  container is reachable from another container as `core-mosquitto`.
- `MQTT_USER` / `MQTT_PASSWORD` — a **dedicated Home Assistant user** (create
  it under Settings → People) with Mosquitto access. Do **not** reuse the API
  keys. See `MQTT_DESIGN.md` and section 6.

`.env` is gitignored, so it is **never committed**. Keys are read at runtime
via a small built-in loader in `tb3au.py` (no extra dependencies). A committed
`.env.example` shows every variable.

> **Security:** rotate these keys if they are ever exposed. Because `.env` is
> gitignored the live key lives only on the device, not in git history.

## 4. Run it

```bash
python tb3au.py
```

Paths to the SDK (`e-Paper/RaspberryPi_JetsonNano/python/...`) are resolved
relative to the script, so it works from any directory / user.

## 5. Automatic daily refresh (cron)

`tb3au.sh` runs the display once; an auto-update hook pulls code + SDK and
applies changes:

```cron
# Refresh the display every day at midnight
0 0 * * * /home/jason/epaper/tb3au.sh

# Auto-update from GitHub every 15 minutes (code + SDK + deps + daemon)
*/15 * * * * /home/jason/epaper/deploy/auto_update.sh >> /home/jason/epaper/git_pull.log 2>&1
```

`deploy/auto_update.sh` runs `git pull --ff-only`, updates the SDK submodule,
and — **only when something that affects the running service changed** —
reinstalls Python dependencies (`requirements.txt`), reinstalls the systemd
unit, and restarts `tb3au-mqtt.service`. So a dependency version bump is applied
automatically; the daily joke cron keeps running independently.

Edit with `crontab -e`. After a `git push` from your dev machine, the Pi picks
up code, SDK, and dependency changes within 15 minutes.

## 6. Push content from Home Assistant (MQTT)

You can push **text or images** from Home Assistant onto the display over
MQTT (Mosquitto). A small daemon, `tb3au_mqtt.py`, subscribes to commands and
renders them using the same code path as the daily joke.

### Topics

| Topic | Direction | Purpose |
|---|---|---|
| `tb3au/status` | Pi → HA | Availability (`online`/`offline`, retained + LWT) |
| `tb3au/display/set` | HA → Pi | Render command (JSON, QoS 1, **not** retained) |
| `tb3au/display/state` | Pi → HA | What is currently shown (echo, retained) |

### Payload (`tb3au/display/set`)

```json
{
  "mode": "text | image | both | clear | joke | markdown",
  "text": "optional string",
  "image": "optional base64 string OR http(s) url",
  "image_type": "base64 | url",
  "markdown": "optional bool — render `text` as markdown"
}
```

- `text` — wrapped text on the panel. Add `"markdown": true` (or use `mode:
  markdown`) to render the text as **markdown** — `#`/`##`/`###` headings,
  `**bold**`, `*italic*`, `` `code` ``, `- ` bullet lists, `> ` quotes, and
  `---` rules — with the font **auto-scaled to fill the panel** (short text is
  drawn large, long text shrinks to fit). Text is rendered with the bundled
  Liberation Sans/Mono TrueType family (real **bold**/`*italic*`/code weights,
  anti-aliased then thresholded to the 1-bit panel); the auto-fit base size is
  capped (see `MAX_BASE` in `tb3au.py`) so short text stays readable rather
  than ballooning to fill the whole panel.
- `image` — decoded (base64) or fetched (url), fitted and centred.
- `both` — image at the top + wrapped caption below (the joke layout).
- `clear` — blank the screen.
- `joke` — re-run the daily joke render (hands control back to the cron job).

### HA example (text)

```yaml
# automation / script
- service: mqtt.publish
  data:
    topic: tb3au/display/set
    qos: 1
    payload: '{"mode":"text","text":"Front door left open!"}'
```

### HA example (image, base64)

Home Assistant cannot base64-encode an image in pure YAML. Use **pyscript**,
**AppDaemon**, or a `shell_command` that encodes the bytes and then publishes.
Sketch (pyscript):

```python
@service
def tb3au_show_image(path):
    import base64, json
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    mqtt.publish("tb3au/display/set",
                json.dumps({"mode": "image", "image": b64,
                            "image_type": "base64"}))
```

### The panel appears as a Home Assistant device automatically

`tb3au_mqtt.py` publishes **MQTT discovery** messages on connect (built in
`ha_discovery.py`), so Home Assistant creates a device called **“E-ink Clock”**
with these entities — no manual YAML required:

| Entity | Type | What it does |
|---|---|---|
| Connection | `binary_sensor` | online/offline from `tb3au/status` |
| Last Shown | `sensor` | last content — `(joke) …` for jokes, the text/caption otherwise, `(image)`/`(cleared)` when blank |
| Display Message | `text` | type a message → rendered on the panel |
| Show Joke | `button` | re-runs the daily joke |
| Clear Screen | `button` | blanks the panel |

The device is re-advertised whenever Home Assistant announces itself online, so
it survives HA restarts. Discovery uses the default `homeassistant/` prefix.

<details>
<summary>Prefer manual YAML instead of discovery?</summary>

If you disable MQTT discovery, add this to `configuration.yaml` (or a package).
**Remove it if you already rely on the automatic discovery above**, to avoid
duplicate entities.

```yaml
mqtt:
  sensor:
    - name: "E-ink Last Shown"
      state_topic: tb3au/display/state
      value_template: "{{ value_json.text | default('(image)') }}"
      json_attributes_topic: tb3au/display/state
  binary_sensor:
    - name: "E-ink Panel Online"
      state_topic: tb3au/status
      payload_on: "online"
      payload_off: "offline"
      device_class: connectivity
```
</details>

See `MQTT_DESIGN.md` for the full schema.

### A dashboard button that sends a typed message

You already get a **“Display Message” `text` entity** from discovery — add it to
a dashboard and type+submit to push text. If you want a dedicated **button** that
prompts for the text when tapped, add a small HA **script** (tracked in
[`homeassistant/tb3au_clock.yaml`](homeassistant/tb3au_clock.yaml)).

**Easiest (no packages):** copy just the `set_clock_message:` block (the part
*under* `script:`, not the `script:` line itself) from that file into your
existing `scripts.yaml`. Your `configuration.yaml` already does
`script: !include scripts.yaml`, so nothing else changes — no `homeassistant:`
block, no include path. Then restart/reload scripts.

**As a tracked package (alternative):** copy `homeassistant/tb3au_clock.yaml`
into your HA config dir as `/config/homeassistant/tb3au_clock.yaml`, then add a
top-level `homeassistant:` block to `configuration.yaml`:

```yaml
homeassistant:
  packages:
    tb3au_clock: !include homeassistant/tb3au_clock.yaml
```

This merges with your existing top-level `script: !include scripts.yaml` — that
is expected and fine. Restart Home Assistant.

Then add the `Set clock message` **script** to a dashboard as a Button/Tile card.
Tapping it opens a dialog to type the message, then publishes
`{"mode":"text","text":"…"}` to `tb3au/display/set`.

The **Show Joke** (`button.tb3au_epd_joke`) and **Clear Screen**
(`button.tb3au_epd_clear`) buttons are created automatically by discovery — just
add them to the dashboard as Button/Tile cards; no extra config needed. Tapping
**Show Joke** renders a fresh joke on the panel.

**Troubleshooting — nothing appears on the panel:** the daemon only acts
on messages it actually receives on `tb3au/display/set`. If tapping the script
does nothing, it is almost always an HA-side issue, not the clock:

- Add the script as a **Button card** (entity `script.set_clock_message`). Tapping
  it opens a dialog to type the message. A Tile / "toggle" card may run the script
  *without* prompting, and HA then refuses to run it (required field missing) — so
  nothing is published.
- After editing `scripts.yaml`, reload scripts (Developer Tools → YAML → Reload
  scripts) or restart HA.
- Quick check: run `script.set_clock_message` from **Developer Tools → Actions**
  with a `text` value. If the panel updates, the script is fine and only the card
  needs fixing.

Use a script rather than a raw Lovelace button `tap_action` → `mqtt.publish`
with a template payload — that path does **not** render the template
(HA core issue #137260). The file also shows how to add one-tap preset buttons.

## 7. Run the MQTT daemon (systemd)

The daemon is a long-running service. A unit file is provided at
`deploy/tb3au-mqtt.service` (edit the `User` / `WorkingDirectory` /
`ExecStart` paths to match your Pi).

```bash
# Install
cp deploy/tb3au-mqtt.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tb3au-mqtt.service

# Logs
journalctl -u tb3au-mqtt.service -f
```

The daemon connects to `MQTT_BROKER` using the credentials in `.env`, publishes
`tb3au/status = online`, and listens on `tb3au/display/set`. The daily cron
job (section 5) keeps running independently.

## 8. Local testing & CI

### Hardware-free tests

The display code can be tested **without hardware**. `tests/run_local_test.py`
injects fake `waveshare_epd` / `openai` / `paho` modules and runs the real
`render_*` and MQTT-dispatch logic against an in-memory display, writing sample
PNGs to `tests/output/`:

```bash
# Windows (this repo's venv)
.venv/Scripts/python.exe tests/run_local_test.py             # full checks
.venv/Scripts/python.exe tests/run_local_test.py --save-only  # render PNGs only
# Linux / macOS
python tests/run_local_test.py
pytest
```

`tests/test_local.py` is the pytest wrapper (11 checks) with a **coverage gate**
(≥ 60% of `tb3au`).

### Linting & pre-commit

Code quality is enforced by [`pre-commit`](https://pre-commit.com) using
`.pre-commit-config.yaml`:

- `ruff` (lint + format) — config in `ruff.toml`
- `detect-secrets` — scans for leaked credentials; findings recorded in
  `.secrets.baseline`
- `bandit` — security lint of the app source
- `pip-audit` — CVE check of dev/test dependencies (`requirements-dev.txt`)
- file hygiene hooks (trailing whitespace, EOF, line endings, YAML, large files)

Activate locally once:

```bash
pip install pre-commit
pre-commit install
```

Then hooks run on every commit, and the **`lint` job** in
`.github/workflows/tests.yml` runs `pre-commit run --all-files` on every
PR/push (alongside the `test` job). Dev dependencies live in
`requirements-dev.txt`. See `MQTT_DESIGN.md` for the full design.

## 9. Connecting to & provisioning the Pi

The display code, the systemd unit, the daily cron launcher (`tb3au.sh`, now
**tracked in this repo**), and a bootstrap script (`deploy/setup_pi.sh`) are all
committed, so a fresh Pi can be stood up from this repo alone.

- **SSH access** to this specific Pi (host, user, key) is in `PI_ACCESS.md`
  (gitignored — local only, so it never leaves your machine).
- **Full provisioning walkthrough** (clone → bootstrap → secrets → MQTT →
  caveats, including the force-push resync) is in `PI_SETUP.md`.

One-command bootstrap on the Pi (after cloning with the submodule):

```bash
deploy/setup_pi.sh        # submodule init, pip install, install+enable the
                        # systemd unit, install the cron jobs
cp .env.example .env    # then fill in OPENAI_API_KEY / API_NINJAS_KEY / MQTT_*
sudo systemctl restart tb3au-mqtt.service
```

## Notes

- The SDK submodule is pinned to a known-good commit. To update it to the
  latest Waveshare release: `cd e-Paper && git pull origin master && cd .. &&
  git add e-Paper && git commit -m "Bump e-Paper SDK"`.
- Don't edit files directly on the Pi if you also push from another machine;
  the `--ff-only` pull will refuse a divergent local history. Edit on your dev
  machine, commit, and push.
