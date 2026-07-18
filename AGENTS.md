# AGENTS.md — tb3au e-ink clock

Guidance for AI coding agents working in this repository. Follow the
conventions and guardrails below; they are load-bearing for the test suite and
the deployment model.

## What this repo is

A Raspberry Pi e-ink "quote clock". On a schedule it fetches a **daily joke**
from the API-Ninjas jokes API, generates a matching cartoon image with
OpenAI's `gpt-image-1` model, and renders **text + image** onto a
**Waveshare 4.2" e-Paper display** (400×300, 1-bit black/white) over SPI.

It can also be driven **on demand** from Home Assistant: `tb3au_mqtt.py` is a
long-running daemon that subscribes to an MQTT topic and renders text/images
pushed over MQTT, coexisting with the daily cron job.

- README.md — user-facing setup, hardware, MQTT topics, deploy.
- MQTT_DESIGN.md — agreed MQTT topic/payload schema + design decisions.
- AGENTS.md — this file (agent conventions).

## Repository layout

```
tb3au.py            # main script + importable render_* functions (cron entry)
tb3au_mqtt.py       # MQTT daemon (imports render_* from tb3au.py)
peppe8o-paper.py    # dev-only 2.13" reference demo (NOT used in prod)
e-Paper/            # Waveshare SDK — GIT SUBMODULE (pinned, do not edit)
deploy/
  tb3au-mqtt.service  # systemd unit for the MQTT daemon
tests/
  run_local_test.py  # hardware-free harness (injects fake modules)
  test_local.py      # pytest wrapper (11 checks) + coverage gate
.env                 # local secrets — gitignored, never committed
.env.example         # documents every env var
```

`e-Paper/` is a **pinned git submodule** of `waveshare/e-Paper`. It is excluded
from linting and security scans (see `ruff.toml`, `.pre-commit-config.yaml`).

## Architecture & entry points

- `tb3au.py` is the single source of truth for drawing. It exposes importable
  `render_*()` functions: `render_joke()`, `render_text()`, `render_image()`,
  `render_both()`, `render_clear()`. Each returns `True/False`, **always sleeps
  the panel** in a `finally`, and never crashes the caller (errors are drawn to
  the panel via `show_error()`).
- `main()` (guarded by `if __name__ == "__main__"`) runs the daily joke — this
  is the cron entry point.
- `tb3au_mqtt.py` imports the `render_*` functions and dispatches decoded MQTT
  payloads via `handle_payload()` → `on_message()`. Reuse the existing
  `render_*` functions; do not duplicate drawing logic.
- Config is read from `os.environ` via a built-in loader `_load_dotenv()` at the
  bottom of `tb3au.py` (no extra dependency). There is **no** pydantic/dotenv.
- Shared module-level state (`epd`, `image`, `draw`, `font15`) is initialised
  in `init_display()`; helpers rely on it. The OpenAI client is lazily created
  (`get_openai_client()`).
- Paths are resolved relative to the script via `_BASE = os.path.dirname(
  os.path.abspath(__file__))`. SDK paths live under `e-Paper/RaspberryPi_JetsonNano/python`.

## Environment setup (working locally)

The display has **no emulator** and talks straight to SPI/GPIO, but the code is
testable without hardware (see Testing). To set up a dev environment:

```bash
git submodule update --init        # required: fetches the Waveshare SDK
python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements-dev.txt
cp .env.example .env               # fill in keys if you need live API/MQTT calls
pre-commit install                  # activate lint/secret hooks (optional but recommended)
```

Notes:
- `requirements.txt` (Pi runtime) pins **intentionally old** versions
  (Pillow==8.1.2, requests==2.25.1, paho-mqtt==2.1.0, openai==2.6.1) for SDK
  compatibility on the Pi. `requirements-dev.txt` uses current releases for CI.
- Tooling targets Python 3.11 (`ruff.toml` `target-version = "py311"`); CI runs
  on 3.11/3.12. The local dev venv may be newer — that's fine.

## How to test

**Hardware-free harness (primary, runs anywhere, no keys, no broker):**

```bash
.venv/Scripts/python.exe tests/run_local_test.py            # full 16 checks + PNGs
.venv/Scripts/python.exe tests/run_local_test.py --save-only # render samples only
```

It injects fake `waveshare_epd` / `openai` / `paho.mqtt` modules **before**
importing the real `tb3au` / `tb3au_mqtt`, then runs the actual `render_*` and
`handle_payload()` / `on_message()` logic against an in-memory display, writing
PNGs to `tests/output/`.

**pytest (CI-equivalent, with coverage gate):**

```bash
pytest                                          # 11 checks
pytest --cov=tb3au --cov-report=term-missing --cov-fail-under=60
```

The CI `test` job enforces **≥60% coverage of `tb3au`**. Keep new code covered.

## How to lint / pre-commit

```bash
pre-commit run --all-files        # ruff + detect-secrets + bandit + pip-audit
ruff check . && ruff format .      # lint + format directly
```

The `lint` CI job runs `pre-commit run --all-files` on every PR/push. Config:
- `ruff.toml`: `line-length = 100`, `quote-style = "double"`, select `[E,F,I,W,B]`.
- `exclude`: `e-Paper`, `tests/output`, `peppe8o-paper.py`.
- `E402` (import-not-at-top) is allowed for `tb3au.py`,
  `tests/run_local_test.py`, `peppe8o-paper.py` (they inject modules / set
  `sys.path` first).
- `detect-secrets` uses `.secrets.baseline`; accepted findings are recorded
  there. `bandit` scans `.` minus `.venv/e-Paper/tests`. `pip-audit` checks
  `requirements-dev.txt` only.

## Conventions & guardrails (important)

1. **Keep `tb3au.py` import-safe.** The test harness imports it with fake
   modules and expects **no side effects on import** — no hardware init, no
   network calls, no broker connect at module load. Put all work inside
   functions or behind `if __name__ == "__main__"`. This is why `main()` and
   the MQTT `main()` are guarded.
2. **Reuse, don't duplicate, the `render_*` functions.** Any new display output
   should be a `render_*` function in `tb3au.py`; the MQTT daemon should only
   dispatch to it.
3. **No hardcoded paths.** Use `_BASE`-relative paths (or `os.path.join`).
   Never bake in `/home/jason/...` or Windows paths.
4. **Secrets only via `.env` + the loader.** Read with `os.environ.get(...)`.
   Never hardcode keys. Add every new variable to **both** `.env.example` and
   the loader if needed. `.env` is gitignored — never commit it.
5. **Respect the secret scanner.** If a value is a legitimate non-secret that
   trips `detect-secrets`, add it to `.secrets.baseline` (do not delete the
   baseline or the hook to hide a real finding). Rotate keys if ever exposed.
6. **Don't edit or commit the `e-Paper` submodule.** It's pinned upstream
   SDK. Bump it deliberately via `cd e-Paper && git pull origin master` then
   `git add e-Paper` (see README "Notes"). Keep it out of your lint/security
   workflow.
7. **Edit on the dev machine, then push.** The Pi pulls `--ff-only`; editing
   on the Pi creates a divergent history the auto-pull will refuse.
8. **Coverage & tests:** add hardware-free checks to
   `tests/run_local_test.py` + `tests/test_local.py` for any new render or
   dispatch logic. Keep `tb3au` coverage ≥60%.
9. **Keep docs in sync.** When you change the MQTT topic/payload schema
   (`handle_payload` in `tb3au_mqtt.py`), update **both** `README.md` (section
   6) and `MQTT_DESIGN.md`. When you change env vars, update `.env.example`.
10. **Don't casually "upgrade" Pi runtime pins.** `requirements.txt` is
    intentionally old for SDK/runtime compatibility. If you change a runtime
    dependency, verify it still works with the Waveshare SDK.
11. **Render functions return a bool and always sleep the panel** (the
    `finally: epd.sleep()` pattern). New modes must preserve this.

## Common tasks

- **Add a new MQTT render mode:** add a `render_*(...)` in `tb3au.py` → wire a
  `mode` branch in `tb3au_mqtt.handle_payload()` → update payload schema in
  `README.md` + `MQTT_DESIGN.md` → add a dispatch test in `tests/`.
- **Change the e-paper layout/coordinates:** edit the drawing helpers in
  `tb3au.py` (note the panel is created as `(epd.height, epd.width)` = `(300,
  400)` and rotated; `both`/`joke` place the image at `(0, 100)`). Re-render
  via `run_local_test.py --save-only` and inspect `tests/output/`.
- **Add a dependency:** runtime deps → `requirements.txt` (Pi-safe pins);
  test/dev deps → `requirements-dev.txt` (+ `pip-audit` will scan it).
- **Bump the SDK:** see guardrail 6.
- **Add an env var:** create it in `.env.example`, read it with
  `os.environ.get(...)` (the loader already populates `os.environ` from `.env`).

## Known gaps & gotchas

- **`tb3au.sh` is referenced in README §5 (cron) but does NOT exist in the
  repo.** The cron job currently depends on a script that isn't committed
  (the deploy dir only contains the MQTT `systemd` unit). Create it or fix the
  README before relying on the midnight refresh.
- The daily-cron and MQTT-daemon paths can both write the panel; the `joke`
  MQTT mode hands control back to the cron job. Don't make them fight.
- `peppe8o-paper.py` is a 2.13" reference demo, not production code; leave it
  out of scope unless explicitly asked.
- Coverage is measured only over `tb3au` (not `tb3au_mqtt`), by design.

## References

- `README.md` — full hardware/setup/MQTT/deploy guide.
- `MQTT_DESIGN.md` — MQTT schema, topic table, security model.
- `.pre-commit-config.yaml`, `ruff.toml`, `pytest.ini` — tooling config.
- `.github/workflows/tests.yml` — CI (`test` + `lint` jobs).
