# E-Ink Panel Debugging Notes (tb3au clock)

A running log of how we diagnosed and fixed MQTT text rendering on the
Waveshare 4.2" e-Paper panel. Written so future sessions (and the human
operator) can see what was tried, what worked, and the panel's quirks.

## What we were debugging

MQTT text mode — publishing `{"mode":"text","text":"..."}` to
`tb3au/display/set` — rendered to an **empty white screen**, even though the
daily joke (cartoon + text) rendered fine. Goal: make MQTT-pushed text
**visible and readable** on the panel.

**Outcome so far:** the render code is now correct and a render in a *fresh*
process shows the text large and centered. One open question remains about the
long-running daemon (see "Open issue" below).

## How to drive the panel (reference)

- **Panel:** Waveshare 4.2" e-Paper (`epd4in2`), 400×300, 1-bit black/white.
- **Pi:** `jason@192.168.1.26`, SSH key `~/.ssh/id_ed25519_tb3au`.
- **Code on Pi:** `/home/jason/epaper` (pulled with `git pull --ff-only`
  via `deploy/auto_update.sh`).
- **MQTT broker:** `192.168.1.215:1883` (`core-mosquitto`). Credentials live
  in the Pi's `/home/jason/epaper/.env` as `MQTT_USER` / `MQTT_PASSWORD`.
  Read them on the Pi with:
  `grep -E '^MQTT_(USER|PASSWORD)=' /home/jason/epaper/.env`
- **Daemon:** `systemd` unit `tb3au-mqtt.service` — a long-running process
  (`tb3au_mqtt.main()`) with `tb3au._KEEP_AWAKE = True`.
- **Display rotation:** `DISPLAY_ROTATION = 180`. A buffer drawn at top-left
  appears at the **physical bottom-right**. Centering content makes it
  orientation-agnostic.
- **Render takes a couple of seconds** — wait ~8s before judging the result.

### Publish snippets (run on the Pi)

Render text over MQTT (uses the broker creds from the .env):

```python
import json, time, paho.mqtt.client as mqtt, tb3au_mqtt as t
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.username_pw_set(t.USERNAME, t.PASSWORD)
c.connect(t.BROKER, t.PORT, 10)
c.loop_start()
c.publish("tb3au/display/set",
          json.dumps({"mode": "text", "text": "MQTT TEST OK"}), qos=1)
time.sleep(8)
c.loop_stop(); c.disconnect()
```

Force a full-black buffer (hardware/pipeline sanity check):

```python
import tb3au, time
tb3au.init_display()
img = tb3au.Image.new("1", (tb3au.epd.width, tb3au.epd.height), 0)
if tb3au.DISPLAY_ROTATION:
    img = img.rotate(tb3au.DISPLAY_ROTATION)
tb3au.epd.display(tb3au.epd.getbuffer(img))
time.sleep(tb3au.PANEL_REFRESH_PAUSE)
```

Watch the daemon log: `journalctl -u tb3au-mqtt.service -b -f`
Check last render state: subscribe to `tb3au/display/state` (retained JSON
with `status`, `mode`, `text`).

## Panel behavior notes (important quirks)

- **180° rotation:** content drawn at the buffer *top-left* ends up at the
  physical *bottom-right*. Center content to avoid "it's in a corner"
  confusion.
- **Liberation `*.ttf` fonts render as hollow outlines** on this panel (the
  original markdown engine bug). Use the bundled `Font.ttc` for solid text.
- **Full-black and partial-black both display fine** — the hardware and the
  `epd.display(epd.getbuffer(img))` pipeline are healthy.
- **Stuck-black:** the panel was once observed stuck on a solid black image.
  A full **power-cycle of the Pi** cleared it. Don't leave it on solid black
  for long.
- **Bistable:** e-paper holds its image with power removed. A white render is
  the safe neutral state.
- **Nightly cron** renders the joke at midnight. Don't mistake it for an MQTT
  render when diagnosing.
- **Refresh latency:** allow ~8s after a publish before judging.

## Tests performed (chronological)

| # | Test | What it proved | Result |
|---|------|----------------|--------|
| 1 | Reviewed render functions | joke path uses `break_string_into_array` + `draw.text` + `font15` | OK |
| 2 | Confirmed daemon running | subscribes `tb3au/display/set` | OK |
| 3 | Published text (old `render_text` → `_render_markdown`) | text used Liberation TTFs | **hollow / unreadable** |
| 4 | Rewrote `render_text` to use bundled `Font.ttc` + `break_string_into_array` | solid glyphs | code fix |
| 5 | Dumped pre-rotation buffer as ASCII | text was drawn into the buffer | text present |
| 6 | Dumped post-rotation (180°) sent buffer as ASCII | text landed tiny in the bottom-right corner | **position issue** |
| 7 | Deployed auto-fit + center (`fd2a709`); published text | — | user: **empty white** |
| 8 | Published a full-black buffer (fresh process) | hardware + pipeline work | **BLACK** (confirmed) |
| 9 | Published white + black border frame + center box (fresh process) | partial black shapes display | **framed box** (confirmed) |
| 10 | Ran real `render_text` in a fresh process; dumped the sent buffer as ASCII | buffer correct: "MQTT TEST OK" large + centered | text in buffer |
| 11 | Asked user after #10 | text visible on panel | **"MQTT TEST OK in large letters perfectly centered"** |
| 12 | Published text via MQTT (daemon path) | — | **inconclusive** — nightly cron joke overwrote it before user looked |

## Key findings

1. The panel hardware and the display pipeline are **healthy**: full-black
   (#8) and partial-black shapes (#9) render correctly.
2. The `render_text()` code now produces a **correct buffer** — large,
   centered "MQTT TEST OK". Confirmed by dumping the post-rotation sent
   buffer as ASCII (#10).
3. A **fresh-process** call to `render_text()` displays correctly (#11,
   confirmed by the user).
4. The original "empty white" was caused by two things, both now fixed:
   - (**a**) the hollow Liberation-font path (#3) → switched to `Font.ttc`.
   - (**b**) tiny text parked in a corner because the 180° rotation wasn't
     accounted for (#6) → auto-fit font size + centering.
5. **Open issue (unconfirmed):** the long-running **daemon**, after it has
   already rendered the nightly joke, did **not** show MQTT text in the early
   test (#7). A fresh process (#10/#11) did. This suggests the daemon may
   need to **re-initialize / reset the e-paper** before a text-only render.
   The clean daemon test (#12) was interrupted by the nightly cron, so it is
   not yet conclusive.

## Next steps (resume here)

1. **Cleanly re-test the daemon MQTT text path** (morning, no cron
   interference) and confirm whether the panel shows the text.
2. If the daemon shows **white** while a fresh process shows text:
   - add an e-paper **re-init / hardware reset** before each render in the
     daemon (or make `init_display()` re-initialize reliably). Guard against
     double GPIO init — prefer `epd.Reset()` (hardware reset pulse) over
     calling `epd.init()` repeatedly if GPIO can't be re-exported.
3. If the daemon shows **text**: the earlier white was the hollow-font /
   corner issue (now fixed). Close out and clean up the temp diagnostic
   files.
4. Update this doc with the final conclusion.

## Temp/diagnostic artifacts

Diagnostic PNGs/scripts live under `tests/output/` (gitignored) or were
run ad-hoc on the Pi in `/tmp`. Remove any `tests/tmp_*.py` left behind.
