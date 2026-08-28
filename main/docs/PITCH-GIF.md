# Cadence — README Hero GIF (10-second loop)

> **What this is:** instructions for capturing the silent 10-second looped
> GIF that the README uses as its hero image. GitHub renders this directly
> in the README's first screen on desktop and mobile.
>
> **Specs that work in 2026:**
> - Size: ≤ 5 MB (GitHub hard cap is 10 MB but 5 MB is the practical ceiling for
>   fast mobile loads)
> - Dimensions: 1280×720 (16:9) or 1200×600
> - Duration: 8–12 s, loops infinitely
> - Audio: **none** — GitHub auto-plays muted
> - Format: GIF (universally compatible) or MP4 (smaller, supported since
>   2024 in markdown)
> - Placement: first image after the title, before the problem statement

## The 10-second story (record this sequence)

The GIF should show **Cadence recovering money in real time** on the live
SPA. Five beats, ~2 s each:

| Beat | Duration | What to show |
|---|---|---|
| 1 | 0:00–0:02 | **Overview** tab. Camera lands on the KPI row. The "Total Recovered" counter visibly ticks up. |
| 2 | 0:02–0:04 | Camera scrolls down to the "Decline Root-Cause Distribution" bar chart. One bar (e.g. NO_FUNDS) flashes. |
| 3 | 0:04–0:06 | **Testbench** tab. Click "Inject Webhook" with `sub_demo_gif / cust_demo_gif / insufficient_funds / 1499`. The "Webhook Ingested" success line appears. |
| 4 | 0:06–0:08 | **Journeys** tab. Click on the new row. The drawer slides in showing the timeline (webhook → classify → guardian → schedule). |
| 5 | 0:08–0:10 | Bottom of the drawer. The "SHA-256 Hash Chain Verified" green checkmark visible. |

The loop seam (last frame → first frame) is at the Overview → first beat
transition, so the counter keeps ticking smoothly.

## Capture: Windows (10 steps, ~5 minutes)

Tools: **OBS Studio** (free, 1080p) + **ScreenToGif** (free, in Microsoft
Store).

1. **Open all the panels** in advance. The SPA on `:3000`, the API on
   `:8000`, a terminal with `python scripts/run_eval.py` already run.
2. **Open OBS** → Settings → Video → 1280×720. Recording → mkv (or mp4).
3. **In OBS main window**, add a Window Capture source pointed at your
   browser. Crop the source to just the browser window.
4. **Add an Audio source** set to "Disabled" — you want a silent GIF.
5. **Click "Start Recording"**. Do the 10-second sequence slowly,
   deliberately, with cursor visible. The 2-second-per-beat pace is
   what makes the GIF readable.
6. **Stop**. OBS saves to disk. Note the file path.
7. **Open ScreenToGif** → File → New → select the OBS recording (drag the
   .mkv/.mp4 into ScreenToGif, or use "Insert" → "Video").
8. **Trim** to the best 10 seconds. Delete the rest.
9. **Save as GIF**. Settings: 15 fps, dithering = FloydSteinberg, max
   colors = 128. Aim for under 5 MB.
10. **Save to `main/docs/hero.gif`**. Commit. Push.

## Capture: macOS (10 steps)

Tools: **QuickTime Player** + **Gifox** or **ffmpeg**.

1. Open the same three panels.
2. QuickTime → File → New Screen Recording. Select the browser area.
3. Click Record. Do the 10-second sequence.
4. Stop. Save the .mov.
5. `ffmpeg -i recording.mov -vf "fps=15,scale=1200:-1:flags=lanczos,split[s0][s1];[s0]palettegen[pstats_mode=diff];[s1][s0]paletteuse=dither=floyd_steinberg" -loop 0 main/docs/hero.gif`
6. Verify file size < 5 MB. If too big, reduce to 8 fps.

## Capture: headless / scripted (CI-friendly)

If you want to script the GIF capture (e.g. in CI on every push), use
`puppeteer` or `playwright` against the live SPA:

```python
# scripts/capture_hero_gif.py
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto("http://localhost:3000")
        # Beat 1: Overview tick
        await page.wait_for_timeout(2000)
        # Beat 3: Testbench click
        await page.click("text=Simulate Webhook")
        await page.fill("input[placeholder='sub_...']", "sub_hero_gif")
        await page.click("text=Inject Payment Failure Webhook")
        await page.wait_for_timeout(2000)
        # Beat 4: Journeys click
        await page.click("text=Journeys")
        await page.wait_for_timeout(1000)
        # Screenshot per beat; ffmpeg to stitch
        for i in range(5):
            await page.screenshot(path=f"beat_{i}.png")
            await page.wait_for_timeout(2000)
        await browser.close()
```

## README usage

In `main/README.md`, after the title and one-line tagline:

```markdown
![Cadence recovery engine in action](docs/hero.gif)
```

The first thing a judge sees when they open the repo is the live
recovery engine doing its job. That single image replaces 90 seconds
of pitch video.
