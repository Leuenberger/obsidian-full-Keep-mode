#!/usr/bin/env python3
"""
Record docs/demo.gif: plays a short scenario in a temporary note in a running
Obsidian (debugging port 9222, see live_test.py) and stitches screenshots.

    pip install websocket-client pillow
    python tests/record_demo.py
"""
import base64
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import live_test as lt  # noqa: E402  (reuses its Obsidian connection and helpers)

OUT = Path(__file__).resolve().parent.parent / "docs" / "demo.gif"
NOTE = """Weekend:

- [ ] Groceries
\t- [ ] Bread
\t- [ ] Coffee beans
\t- [ ] Apples
- [ ] Call grandma
- [ ] Book train tickets
- [ ] Birthday present for Sam
\t\tA book or a nice tea,
\t\tmaybe both
- [ ] Water the plants"""

frames = []


def clip():
    return lt.ob.js("""
    const r = window.__tcLeaf.view.contentEl.querySelector('.cm-scroller').getBoundingClientRect();
    const c = window.__tcLeaf.view.editor.cm.contentDOM.getBoundingClientRect();
    return { x: Math.max(r.left, c.left - 40), y: r.top + 60, width: Math.min(620, c.width + 60), height: 400 };
    """)


def shot(ms, hover=None):
    # Park the text cursor at the start of the title line, out of the way.
    lt.ob.js("window.__tcLeaf.view.editor.cm.dispatch({ selection: { anchor: 0 } }); await new Promise(r => setTimeout(r, 150));")
    if hover:
        g = lt.ob.js(lt.line_el(hover) + "const r = el.getBoundingClientRect(); return { x: r.left + 120, y: r.top + r.height / 2 };")
        lt.ob.mouse("mouseMoved", g["x"], g["y"], 0)
        time.sleep(0.15)
    c = clip()
    data = lt.ob.call("Page.captureScreenshot", format="png", clip={**c, "scale": 1})["data"]
    frames.append((Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB"), ms))


def drag_recorded(label, dx, target=None, lower=True):
    g = lt.ob.js(lt.line_el(label) + """
    const g = el.querySelector(".fkm-grip").getBoundingClientRect();
    return { x: g.left + g.width / 2, y: g.top + g.height / 2 };""")
    x, y = g["x"], g["y"]
    ty = y
    if target:
        r = lt.ob.js(lt.line_el(target) + "const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom };")
        ty = r["bottom"] - 3 if lower else r["top"] + 3
    lt.ob.mouse("mouseMoved", x, y, 0)
    time.sleep(0.2)
    shot(500)
    lt.ob.mouse("mousePressed", x, y)
    for k in range(1, 9):
        lt.ob.mouse("mouseMoved", x + dx * k / 8, y + (ty - y) * k / 8)
        time.sleep(0.05)
        if k % 2 == 0:
            shot(120)
    shot(500)
    lt.ob.mouse("mouseReleased", x + dx, ty)
    time.sleep(0.8)


try:
    lt.ob.js("""document.querySelectorAll(".modal-container").forEach(m => { m.dataset.tcHidden = "1"; m.style.visibility = "hidden"; });""")
    lt.open_note("demo", NOTE)
    time.sleep(0.5)
    shot(1600)
    lt.click_checkbox("Call grandma")
    shot(1400)
    lt.click_checkbox("Coffee beans")
    shot(1800)
    drag_recorded("Water the plants", 0, target="Groceries", lower=False)
    shot(1400)
    drag_recorded("Book train tickets", 70)
    shot(2200)
finally:
    lt.ob.js(lt.PRELUDE + """
    for (const l of app.workspace.getLeavesOfType("markdown")) if (l.view.file?.path?.startsWith(FOLDER + "/")) l.detach();
    const folder = app.vault.getAbstractFileByPath(FOLDER);
    if (folder) await app.vault.trash(folder, true);
    document.querySelectorAll(".modal-container[data-tc-hidden]").forEach(m => { m.style.visibility = ""; delete m.dataset.tcHidden; });
    """)

OUT.parent.mkdir(exist_ok=True)
size = frames[0][0].size
images = [f.resize(size) for f, _ in frames]
images[0].save(OUT, save_all=True, append_images=images[1:], duration=[ms for _, ms in frames], loop=0, optimize=True)
print(f"saved {OUT} ({len(frames)} frames, {OUT.stat().st_size // 1024} KB)")
