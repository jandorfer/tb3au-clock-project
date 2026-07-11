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
```

- `OPENAI_API_KEY` — an OpenAI API key (the script uses `gpt-image-1`).
- `API_NINJAS_KEY` — from <https://api-ninjas.com/api/jokes>.

`.env` is gitignored, so it is **never committed**. Keys are read at runtime
via a small built-in loader in `tb3au.py` (no extra dependencies).

> **Security:** rotate these keys if they are ever exposed. Because `.env` is
> gitignored the live key lives only on the device, not in git history.

## 4. Run it

```bash
python tb3au.py
```

Paths to the SDK (`e-Paper/RaspberryPi_JetsonNano/python/...`) are resolved
relative to the script, so it works from any directory / user.

## 5. Automatic daily refresh (cron)

`tb3au.sh` runs the display once; schedule it and an auto-pull:

```cron
# Refresh the display every day at midnight
0 0 * * * /home/jason/epaper/tb3au.sh

# Auto-update code + SDK from GitHub every 15 minutes
*/15 * * * * cd /home/jason/epaper && git pull --ff-only origin main && git submodule update --init >> /home/jason/epaper/git_pull.log 2>&1
```

Edit with `crontab -e`. After a `git push` from your dev machine, the Pi picks
up both code changes and any SDK update within 15 minutes.

## Notes

- The SDK submodule is pinned to a known-good commit. To update it to the
  latest Waveshare release: `cd e-Paper && git pull origin master && cd .. &&
  git add e-Paper && git commit -m "Bump e-Paper SDK"`.
- Don't edit files directly on the Pi if you also push from another machine;
  the `--ff-only` pull will refuse a divergent local history. Edit on your dev
  machine, commit, and push.
