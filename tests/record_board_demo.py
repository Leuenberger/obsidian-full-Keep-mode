#!/usr/bin/env python3
"""
Record docs/board.gif: a short tour of the Keep board with made-up notes, in a
running Obsidian (debugging port 9222, see live_test.py). A drawn mouse pointer
shows where the clicks go (screenshots don't include the real one).

    pip install websocket-client pillow
    python tests/record_board_demo.py      (keep the Obsidian window visible)
    python tests/record_board_demo.py --dark   (docs/board-dark.gif, in dark mode)
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

DARK = "--dark" in sys.argv
OUT = Path(__file__).resolve().parent.parent / "docs" / ("board-dark.gif" if DARK else "board.gif")
FOLDER = lt.FOLDER

NOTES = {
    'Groceries': ('yellow', 1000, True, ['Shopping'], '- [ ] Milk\n- [ ] Bread\n- [ ] Coffee beans\n- [ ] Apples\n- [ ] Tomatoes\n- [ ] Pasta\n- [ ] Parmesan\n- [ ] Olive oil\n- [ ] Yoghurt\n- [ ] Bananas\n- [ ] Dish soap\n- [ ] Toothpaste\n- [x] Eggs\n- [x] Butter\n- [x] Rice\n'),
    'Trip to Lisbon': ('blue', 990, True, ['Travel'], 'Flights Friday 08:40, back Monday 19:15.\nHotel near Alfama.\n\n- [ ] Book tram tour\n- [ ] Pack\n\t- [ ] Camera and charger\n\t- [ ] Sunglasses\n\t- [ ] Comfortable shoes\n\t- [ ] Adapter\n- [ ] Restaurants\n\t- [ ] Time Out Market\n\t- [ ] Pastéis de Belém\n- [ ] Ask Ana about the fado bar\n- [x] Renew passport\n'),
    'Ideas for the garden': ('green', 900, False, ['Home'], 'Tomatoes along the fence, herbs by the kitchen door. A bench under the apple tree?\n\nAsk the neighbours which roses survive the winter here. Maybe a small pond for the frogs, and a rain barrel next to the shed.\n'),
    'Birthday presents': ('pink', 890, False, ['Family'], '- [ ] Sam: a book or nice tea\n- [ ] Mia: watercolours\n\t- [ ] the big set\n\t- [ ] brushes\n- [ ] Dad: concert tickets\n- [ ] Grandma: photo album\n- [x] Leo: football\n'),
    'Books to read': (None, 880, False, ['Reading'], '- [ ] The Overstory\n- [ ] Piranesi\n- [ ] Klara and the Sun\n- [ ] Educated\n- [ ] The Remains of the Day\n- [ ] Sapiens\n- [ ] A Gentleman in Moscow\n- [x] Project Hail Mary\n- [x] Circe\n'),
    'Quote': ('purple', 870, False, [], '"Simplicity is the ultimate sophistication."\n'),
    'Moving house': ('orange', 860, False, ['Home'], '- [ ] Give notice to the landlord\n- [ ] Boxes\n\t- [ ] Kitchen\n\t- [ ] Books\n\t- [ ] Clothes\n- [ ] Change address\n\t- [ ] Bank\n\t- [ ] Insurance\n\t- [ ] Post office\n- [ ] Internet at the new flat\n- [ ] Book the van\n- [ ] Ask friends to help\n- [x] Sign the contract\n- [x] Measure the rooms\n'),
    'Workout': ('orange', 850, False, ['Health'], 'Mon: run 5k\nTue: rest\nWed: yoga\nThu: weights\nFri: swim\nSat: long walk\n'),
    'Team meeting': (None, 840, False, ['Work'], 'Q3 planning. Launch moved to October; design review next Tuesday.\n\nAction items: Anna updates the roadmap, Tom checks the budget, I write the summary.\n'),
    'Movies to watch': ('cyan', 830, False, ['Fun'], '- [ ] Past Lives\n- [ ] Perfect Days\n- [ ] The Holdovers\n- [ ] Dune: Part Two\n- [ ] Anatomy of a Fall\n- [x] Oppenheimer\n'),
    'Lasagne': ('yellow', 820, False, ['Recipes'], '- [ ] 500 g minced beef\n- [ ] 1 onion, 2 garlic cloves\n- [ ] 2 cans of tomatoes\n- [ ] Lasagne sheets\n- [ ] Béchamel\n- [ ] Mozzarella\n\nFry onion and garlic, brown the meat, add tomatoes and simmer 30 min. Layer, top with cheese, 40 min at 180°.\n'),
    'Call the plumber': (None, 810, False, ['Home'], 'Kitchen tap drips. Ask about Thursday.\n'),
    'Camping packing list': ('green', 800, False, ['Travel'], '- [ ] Tent\n- [ ] Sleeping bags\n- [ ] Mats\n- [ ] Stove and gas\n- [ ] Head torches\n- [ ] First aid kit\n- [ ] Rain jackets\n- [ ] Pocket knife\n- [ ] Water filter\n- [x] Map\n'),
    'Podcasts': (None, 790, False, ['Fun'], 'Hardcore History\nThe Rest Is History\nRadiolab\n99% Invisible\n'),
    'Spanish words': ('blue', 780, False, ['Learning'], 'la ventana = window\nel cuchillo = knife\ntodavía = still, yet\naprovechar = make the most of\n'),
    'Car': (None, 770, False, [], 'Service due in November. Winter tyres!\n'),
    'Weekend': ('pink', 760, False, ['Family'], '- [ ] Farmers market\n- [ ] Clean the bikes\n- [ ] Call grandma\n- [x] Laundry\n'),
    'Wifi at the cabin': (None, 750, False, [], 'Network: Pinewood\nCheck-in after 3 pm, key under the blue pot.\n'),
    'Gift ideas': ('purple', 740, False, ['Family'], '- [ ] Board game for the kids\n- [ ] Plant for Ana\n- [ ] Scarf\n'),
    'Doctor': (None, 730, False, ['Health'], 'Annual check-up. Bring vaccination card.\n'),
}

BOARD = f"""filters:
  and:
    - 'file.ext == "md"'
    - file.inFolder("{FOLDER}")
views:
  - type: keep-board
    name: Board
"""

frames = []


def setup():
    notes = {}
    for name, (color, order, pinned, tags, body) in NOTES.items():
        fm = [f"keep_order: {order}"]
        if color:
            fm.append(f"keep_color: {color}")
        if pinned:
            fm.append("keep_pinned: true")
        if tags:
            fm.append("tags:\n" + "\n".join(f"  - {t}" for t in tags))
        notes[name] = "---\n" + "\n".join(fm) + "\n---\n" + body
    lt.ob.js(lt.PRELUDE + f"""
    // Dark mode for this recording only (Obsidian's own setting stays as it is).
    window.__demoTheme = document.body.hasClass("theme-dark") ? "theme-dark" : "theme-light";
    if ({json.dumps(DARK)}) {{ document.body.removeClass("theme-light"); document.body.addClass("theme-dark"); }}
    document.querySelectorAll(".modal-container").forEach(m => {{ m.dataset.tcHidden = "1"; m.style.visibility = "hidden"; }});
    if (!app.vault.getAbstractFileByPath(FOLDER)) await app.vault.createFolder(FOLDER);
    for (const [name, text] of Object.entries({json.dumps(notes)})) {{
        const p = FOLDER + "/" + name + ".md";
        const f = app.vault.getAbstractFileByPath(p);
        if (f) await app.vault.modify(f, text); else await app.vault.create(p, text);
    }}
    const bp = FOLDER + "/board.base";
    let b = app.vault.getAbstractFileByPath(bp);
    if (b) await app.vault.modify(b, {json.dumps(BOARD)}); else b = await app.vault.create(bp, {json.dumps(BOARD)});
    window.__demoLeftOpen = !app.workspace.leftSplit.collapsed;
    window.__demoRightOpen = !app.workspace.rightSplit.collapsed;
    app.workspace.leftSplit.collapse();
    app.workspace.rightSplit.collapse();
    const leaf = app.workspace.getLeaf("tab");
    await leaf.openFile(b);
    app.workspace.setActiveLeaf(leaf, {{ focus: true }});
    window.__fkmBoard = leaf;
    await wait(1500);
    // A board about as wide as a laptop browser window, for a compact GIF.
    const board = leaf.view.containerEl.querySelector(".fkm-board");
    Object.assign(board.style, {{ maxWidth: "1040px", marginInline: "auto" }});
    await wait(1500);
    // A drawn mouse pointer.
    const cursor = document.body.createDiv({{ attr: {{ id: "fkm-demo-cursor" }} }});
    cursor.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2 L3 19 L8 14.5 L11.5 22 L14.5 20.7 L11 13.5 L18 13.5 Z" fill="black" stroke="white" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    Object.assign(cursor.style, {{ position: "fixed", left: "0px", top: "0px", zIndex: 99999, pointerEvents: "none" }});
    """)


pointer = {"x": 0, "y": 0}


def move(x, y, steps=8, shots=0, buttons=0):
    """Glide the (real and drawn) pointer to x, y."""
    x0, y0 = pointer["x"], pointer["y"]
    for k in range(1, steps + 1):
        px, py = x0 + (x - x0) * k / steps, y0 + (y - y0) * k / steps
        lt.ob.mouse("mouseMoved", px, py, buttons)
        lt.ob.js(f"const c = document.getElementById('fkm-demo-cursor'); c.style.left = '{px}px'; c.style.top = '{py}px';")
        time.sleep(0.02)
        if shots and k % max(1, steps // shots) == 0:
            shot(90)
    pointer.update(x=x, y=y)


def click(x, y):
    move(x, y)
    time.sleep(0.15)
    lt.ob.mouse("mousePressed", x, y)
    lt.ob.mouse("mouseReleased", x, y, 0)


def box():
    """The area around the cards and the search bar (and the pop-up, when open)."""
    return lt.ob.js("""const board = window.__fkmBoard.view.containerEl.querySelector('.fkm-board');
        const r = board.getBoundingClientRect();
        const parts = [...board.querySelectorAll('.fkm-board-column, .fkm-search')].map(e => e.getBoundingClientRect()).filter(b => b.width);
        const modal = document.querySelector('.fkm-note-modal');
        if (modal) parts.push(modal.getBoundingClientRect());
        let left = Math.min(...parts.map(b => b.left)) - 24, right = Math.max(...parts.map(b => b.right)) + 24;
        left = Math.max(r.left, left); right = Math.min(r.right, right);
        return { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(Math.min(r.bottom, innerHeight) - r.top) };""")


CLIP = {}


def shot(ms):
    c = CLIP or box()
    # The whole window, cropped here: a clipped capture resizes the page for a moment,
    # which cancels a drag in progress.
    data = lt.ob.call("Page.captureScreenshot", format="png")["data"]
    image = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
    ratio = image.width / lt.ob.js("return innerWidth;")
    box = tuple(round(v * ratio) for v in (c["x"], c["y"], c["x"] + c["width"], c["y"] + c["height"]))
    frames.append((image.crop(box), ms))


def center(selector, name=None):
    js = f"""const root = window.__fkmBoard.view.containerEl;
        const all = [...root.querySelectorAll({json.dumps(selector)})].filter(e => e.getBoundingClientRect().width);
        const el = {f"all.find(e => (e.closest('[data-path]')?.dataset.path ?? '').endsWith('/{name}.md'))" if name else "all[0]"};
        const r = el.getBoundingClientRect(); return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }};"""
    return lt.ob.js(js)


try:
    setup()
    b = box()
    CLIP.update(b)
    pointer.update(x=b["x"] + b["width"] - 60, y=b["y"] + b["height"] - 40)
    move(pointer["x"], pointer["y"], steps=1)
    shot(1800)

    # Hover a card: the pin and Keep's buttons appear.
    c = center(".fkm-card .fkm-card-title", "Ideas for the garden")
    move(c["x"], c["y"] + 30, shots=2)
    shot(1200)
    # Pin it: it moves up to Pinned.
    p = center(".fkm-card .fkm-card-pin", "Ideas for the garden")
    click(p["x"], p["y"])
    time.sleep(1.2)
    shot(1600)

    # Search.
    s = center(".fkm-search input")
    click(s["x"], s["y"])
    for i, ch in enumerate("milk"):
        lt.ob.call("Input.insertText", text=ch)
        time.sleep(0.12)
        if i in (1, 3):
            time.sleep(0.5)
            shot(400)
    time.sleep(1)
    shot(1500)
    x = center(".fkm-search .fkm-search-clear")
    click(x["x"], x["y"])
    time.sleep(1.2)
    shot(800)

    # Tick an item right on a card.
    t = lt.ob.js("""const card = [...window.__fkmBoard.view.containerEl.querySelectorAll('.fkm-card')].find(c => c.dataset.path.endsWith('/Books to read.md'));
        const box = [...card.querySelectorAll('.fkm-card-item')].find(r => r.textContent.includes('Piranesi')).querySelector('input').getBoundingClientRect();
        return { x: box.left + box.width / 2, y: box.top + box.height / 2 };""")
    move(t["x"], t["y"], shots=1)
    shot(500)
    click(t["x"], t["y"])
    time.sleep(1.4)
    shot(1600)

    # Open a note in the pop-up and tick an item there.
    o = center(".fkm-card .fkm-card-title", "Groceries")
    click(o["x"], o["y"])
    for attempt in range(20):
        time.sleep(0.3)
        if lt.ob.js("return !!document.querySelector('.fkm-note-modal .cm-line');"):
            break
        if attempt == 8:
            print("  (clicking the card again)")
            click(o["x"], o["y"])
    time.sleep(1.2)
    shot(1500)
    m = lt.ob.js("""const m = document.querySelector('.fkm-note-modal');
        const line = [...m.querySelectorAll('.cm-line')].find(l => l.textContent.includes('Bread'));
        const r = line.querySelector('input').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 };""")
    move(m["x"], m["y"], shots=1)
    shot(500)
    click(m["x"], m["y"])
    time.sleep(1.2)
    shot(1800)
    lt.press_escape()
    time.sleep(1)
    shot(800)

    # Drag a card onto another.
    a = center(".fkm-card .fkm-card-title", "Quote")
    z = center(".fkm-card .fkm-card-title", "Birthday presents")
    move(a["x"], a["y"])
    shot(500)
    lt.ob.mouse("mousePressed", a["x"], a["y"])
    move(z["x"], z["y"] + 20, steps=12, shots=4, buttons=1)
    lt.ob.mouse("mouseReleased", z["x"], z["y"] + 20, 0)
    time.sleep(2.5)
    shot(2400)
finally:
    lt.ob.js(lt.PRELUDE + """
    document.getElementById("fkm-demo-cursor")?.remove();
    window.__fkmBoard?.detach();
    for (const l of app.workspace.getLeavesOfType("markdown")) if (l.view.file?.path?.startsWith(FOLDER + "/")) l.detach();
    const folder = app.vault.getAbstractFileByPath(FOLDER);
    if (folder) {
        for (const f of [...folder.children]) await app.vault.trash(f, true);
        await app.vault.trash(folder, true);
    }
    if (window.__demoLeftOpen) app.workspace.leftSplit.expand();
    if (window.__demoRightOpen) app.workspace.rightSplit.expand();
    document.querySelectorAll(".modal-container[data-tc-hidden]").forEach(m => { m.style.visibility = ""; delete m.dataset.tcHidden; });
    if (window.__demoTheme) { document.body.removeClass("theme-light", "theme-dark"); document.body.addClass(window.__demoTheme); }
    """)

OUT.parent.mkdir(exist_ok=True)
size = frames[0][0].size
images = [f.resize(size) for f, _ in frames]
images[0].save(OUT, save_all=True, append_images=images[1:], duration=[ms for _, ms in frames], loop=0, optimize=True)
print(f"saved {OUT} ({len(frames)} frames, {OUT.stat().st_size // 1024} KB)")
