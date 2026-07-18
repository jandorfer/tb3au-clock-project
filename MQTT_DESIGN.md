# MQTT push design — tb3au e-ink clock

This document captures the agreed design for pushing **text or images from
Home Assistant onto the Waveshare 4.2" e-Paper display** over MQTT (Mosquitto,
already running as the HA add-on).

## Locked decisions

1. **Image transport:** base64-encoded bytes embedded in the JSON payload
   (self-contained; no need for the Pi to reach HA's HTTP server).
2. **HA can trigger *and* restore joke mode** via a `joke` command, so the
   daily joke job and on-demand pushes coexist.
3. **The panel is exposed as a Home Assistant device/entity** (state + availability).
4. **The listener runs as a `systemd` service** on the Pi alongside the existing
   cron job.

## Topic namespace

| Topic | Direction | Retained | QoS | Purpose |
|---|---|---|---|---|
| `tb3au/status` | Pi → HA | yes | 1 | Availability. LWT publishes `offline`. |
| `tb3au/display/set` | HA → Pi | **no** | 1 | Render command (JSON). Not retained so a reconnect never replays a stale render. |
| `tb3au/display/state` | Pi → HA | yes | 1 | Echo of what is currently shown (`{"status","mode","text","ts"}`). |

All topics are configurable via env vars (`TB3AU_TOPIC_*`).

## Payload schema — `tb3au/display/set`

A single JSON envelope covers every case:

```json
{
  "mode": "text | image | both | clear | joke | markdown",
  "text": "optional string",
  "image": "optional base64 string OR http(s) url",
  "image_type": "base64 | url",
  "layout": "image_top | image_only | text_only",
  "markdown": "optional bool — render `text` as markdown (text/markdown mode)"
}
```

| `mode` | Behaviour | Required fields |
|---|---|---|
| `text` | Wrap + draw text. Set `"markdown": true` to render the text as markdown (headings, **bold**, *italic*, `code`, lists, quotes, rules) and auto-scale the font to fill the panel. | `text` |
| `markdown` | Alias for `text` with markdown always on. | `text` |
| `image` | Decode image, fit to panel, centre. | `image` (+ `image_type`) |
| `both` | Image at `(0,100)` + wrapped caption above (joke layout). | `text`, `image` |
| `clear` | Blank the screen. | — |
| `joke` | Re-run the daily joke render (hand control back). | — |

`image_type` defaults to `base64`. `layout` is accepted but the code maps
`image`→centred and `both`→`image_top` + caption (matches the existing joke
layout); it can be extended later.

## Pi-side behaviour (`tb3au_mqtt.py`)

- Connects to Mosquitto (`MQTT_BROKER` / `MQTT_PORT`, default
  `core-mosquitto:1883` for same-host HAOS).
- Authenticates with an HA-created MQTT user (`MQTT_USER` / `MQTT_PASSWORD`
  from `.env`) — **not** the API keys.
- On connect: publish `tb3au/status = "online"` (retained), subscribe to
  `tb3au/display/set`.
- **LWT** (`will_set`): `tb3au/status = "offline"` (retained) so HA flips the
  panel to *unavailable* if the daemon dies.
- On message: parse JSON → dispatch to a `render_*` function (shared with the
  cron job) → publish a `tb3au/display/state` echo.
- Auto-reconnect with backoff; each render is wrapped so failures are shown on
  the panel via `show_error()` and reported in `state`.

## Code layout

- **`tb3au.py`** — refactored into importable functions:
  `render_joke()`, `render_text()`, `render_image()`, `render_both()`,
  `render_clear()`, plus helpers. `main()` runs the joke (cron entry point).
  No side effects on import.
- **`tb3au_mqtt.py`** — the daemon; imports the `render_*` functions.
- **`deploy/tb3au-mqtt.service`** — systemd unit.
- **`.env.example`** — documents the new MQTT variables.

## Home Assistant side

- Publish from any automation/script with the `mqtt.publish` service.
- A device is registered via `mqtt:` YAML:
  - `sensor` on `tb3au/display/state` (last shown text).
  - `binary_sensor` on `tb3au/status` (online/offline).
- Text-only pushes are pure YAML. Base64 image pushes need a small Python
  step (pyscript / AppDaemon / `shell_command`) to encode the bytes — see
  README.

## Coexistence with the daily joke

The cron job keeps running `tb3au.py` at midnight. HA can override the screen
at any time (alerts, etc.) and later publish `{"mode":"joke"}` to restore the
daily joke, or simply let the next midnight refresh take over.

## Local testing (no hardware)

Waveshare ships **no emulator**; the driver talks straight to SPI/GPIO. To test
locally, `tests/run_local_test.py` injects fake `waveshare_epd`, `openai`, and
`paho.mqtt` modules, then runs the **real** `render_*` and `handle_payload` /
on_message code against an in-memory display that captures the final PIL image.

```bash
.venv/Scripts/python.exe tests/run_local_test.py
```

It asserts on image size / black-pixel content for `text` / `image` / `both` /
`clear`, exercises the MQTT dispatch (valid, missing-field, unknown-mode,
non-JSON, joke-without-key, and the `on_message` state echo), and writes PNGs
to `tests/output/` for visual inspection. Requires only Pillow + requests.

This validates layout and dispatch logic; the **real** e-paper hardware and
Mosquitto broker are still the final truth test on the Pi.

## Security

- MQTT credentials are a dedicated HA user, stored in `.env` (gitignored).
- `tb3au/display/set` is not retained (no replay on reconnect).
- Payloads are validated/length-bounded before rendering.
