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
NOTE = """---
keep_color: yellow
---
Weekend:

- [ ] Groceries
\t- [ ] Bread
\t- [ ] Coffee beans
\t- [ ] Apples
\t- [ ] Tomatoes
\t- [ ] Parmesan
- [ ] Call grandma
- [ ] Book train tickets
- [ ] Birthday present for Sam
\t\tA book or a nice tea,
\t\tmaybe both
- [ ] Clean the bikes
\t- [ ] Pump the tyres
\t- [ ] Oil the chains
- [ ] Farmers market
- [ ] Return the library books
- [ ] Plan next week's meals
- [ ] Pay the electricity bill
- [ ] Water the plants"""

frames = []

# A drawn mouse pointer (screenshots don't include the real one): it follows every mouse event.
_mouse = lt.ob.mouse


def mouse(kind, x, y, buttons=1):
    _mouse(kind, x, y, buttons)
    lt.ob.js(f"const c = document.getElementById('fkm-demo-cursor'); if (c) {{ c.style.left = '{x}px'; c.style.top = '{y}px'; }}")


lt.ob.mouse = mouse
CURSOR = """const cursor = document.body.createDiv({ attr: { id: "fkm-demo-cursor" } });
cursor.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2 L3 19 L8 14.5 L11.5 22 L14.5 20.7 L11 13.5 L18 13.5 Z" fill="black" stroke="white" stroke-width="1.5" stroke-linejoin="round"/></svg>';
Object.assign(cursor.style, { position: "fixed", left: "-40px", top: "0px", zIndex: 99999, pointerEvents: "none" });"""


def tick(label):
    """Move the pointer to an item's checkbox and click it."""
    b = lt.ob.js(lt.line_el(label) + "const r = el.querySelector('input').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 };")
    lt.ob.mouse("mouseMoved", b["x"] + 60, b["y"] + 40, 0)
    for k in range(1, 5):
        lt.ob.mouse("mouseMoved", b["x"] + 60 * (1 - k / 4), b["y"] + 40 * (1 - k / 4), 0)
        time.sleep(0.03)
    shot(450)
    lt.ob.mouse("mousePressed", b["x"], b["y"])
    lt.ob.mouse("mouseReleased", b["x"], b["y"], 0)
    time.sleep(0.9)


def clip():
    return lt.ob.js("""
    const r = window.__tcLeaf.view.contentEl.querySelector('.cm-scroller').getBoundingClientRect();
    const c = window.__tcLeaf.view.editor.cm.contentDOM.getBoundingClientRect();
    return { x: Math.max(r.left, c.left - 40), y: r.top + 60, width: Math.min(620, c.width + 60), height: 600 };
    """)


def shot(ms, hover=None):
    # Park the text cursor at the end of "Weekend:", out of the way of the items.
    lt.ob.js("""const cm = window.__tcLeaf.view.editor.cm; const d = cm.state.doc;
        let n = 1; while (n < d.lines && d.line(n).text !== 'Weekend:') n++;
        if (cm.state.selection.main.head !== d.line(n).to) cm.dispatch({ selection: { anchor: d.line(n).to } });
        await new Promise(r => setTimeout(r, 150));""")
    if hover:
        g = lt.ob.js(lt.line_el(hover) + "const r = el.getBoundingClientRect(); return { x: r.left + 120, y: r.top + r.height / 2 };")
        lt.ob.mouse("mouseMoved", g["x"], g["y"], 0)
        time.sleep(0.15)
    c = clip()
    # The whole window, cropped here: a clipped capture resizes the page for a moment,
    # which cancels a drag in progress.
    data = lt.ob.call("Page.captureScreenshot", format="png")["data"]
    image = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
    ratio = image.width / lt.ob.js("return innerWidth;")
    box = tuple(round(v * ratio) for v in (c["x"], c["y"], c["x"] + c["width"], c["y"] + c["height"]))
    frames.append((image.crop(box), ms))


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
    lt.ob.js(CURSOR + """
const style = document.head.createEl("style", { attr: { id: "fkm-demo-style" } });
style.textContent = ".fkm-grip { opacity: 0.6 !important; }";""")
    time.sleep(0.5)
    shot(1600)
    tick("Call grandma")
    shot(1400)
    tick("Coffee beans")
    shot(1800)
    drag_recorded("Water the plants", 0, target="Groceries", lower=False)
    shot(1400)
    drag_recorded("Book train tickets", 70)
    shot(2200)
finally:
    lt.ob.js(lt.PRELUDE + """
    document.getElementById("fkm-demo-cursor")?.remove();
    document.getElementById("fkm-demo-style")?.remove();
    for (const l of app.workspace.getLeavesOfType("markdown")) if (l.view.file?.path?.startsWith(FOLDER + "/")) l.detach();
    const folder = app.vault.getAbstractFileByPath(FOLDER);
    if (folder) {
        for (const f of [...folder.children]) await app.vault.trash(f, true);
        await app.vault.trash(folder, true);
    }
    document.querySelectorAll(".modal-container[data-tc-hidden]").forEach(m => { m.style.visibility = ""; delete m.dataset.tcHidden; });
    """)

OUT.parent.mkdir(exist_ok=True)
size = frames[0][0].size
images = [f.resize(size) for f, _ in frames]
images[0].save(OUT, save_all=True, append_images=images[1:], duration=[ms for _, ms in frames], loop=0, optimize=True)
print(f"saved {OUT} ({len(frames)} frames, {OUT.stat().st_size // 1024} KB)")
