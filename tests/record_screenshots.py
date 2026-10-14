#!/usr/bin/env python3
"""
Screenshots for the plugin's page: five on a computer and five on a phone, with
made-up notes, in a running Obsidian (debugging port 9222, see live_test.py).
The demo notes get a folder of their own and are removed afterwards; other tabs,
the status bar and the vault's own labels stay out of the pictures.

    pip install websocket-client pillow
    python tests/record_screenshots.py [output folder]     (default: ../screenshots)
"""
import base64
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import live_test as lt  # noqa: E402  (reuses its Obsidian connection)
from demo_notes import NOTES  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "screenshots"
FOLDER = "Keep demo"
DESKTOP = dict(width=1440, height=900, deviceScaleFactor=2, mobile=False)
PHONE = dict(width=390, height=844, deviceScaleFactor=3, mobile=True)

tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
notes = dict(NOTES)
# A checklist with ticked sub-items (shown under a faded copy of their parent) and a reminder.
notes["Moving house"] = ("orange", 860, False, ["Home"],
                         "- [ ] Give notice to the landlord\n- [ ] Boxes\n\t- [ ] Kitchen\n\t- [x] Books\n\t- [ ] Clothes\n"
                         "- [ ] Change address\n\t- [ ] Bank\n\t- [x] Insurance\n\t- [ ] Post office\n"
                         "- [ ] Internet at the new flat\n- [ ] Book the van\n- [ ] Ask friends to help\n"
                         "- [x] Sign the contract\n- [x] Measure the rooms\n")
REMINDERS = {"Groceries": f"{tomorrow}T08:00", "Birthday presents": f"{tomorrow}T18:30"}

BOARD = f"""filters:
  and:
    - 'file.ext == "md"'
    - file.inFolder("{FOLDER}")
views:
  - type: keep-board
    name: Board
"""

PRELUDE = "const wait = ms => new Promise(r => setTimeout(r, ms));\nconst F = " + json.dumps(FOLDER) + ";\n"


def js(code):
    return lt.ob.js(PRELUDE + code)


def wake():
    """Keep a covered window drawing and its timers running while we work."""
    try:
        js("""const wc = require("@electron/remote").getCurrentWebContents();
            wc.setBackgroundThrottling(false); wc.invalidate(); try { await wc.capturePage(); } catch {}""")
    except RuntimeError:
        pass


def setup():
    files = {}
    for name, (color, order, pinned, tags, body) in notes.items():
        fm = [f"keep_order: {order}"]
        if color:
            fm.append(f"keep_color: {color}")
        if pinned:
            fm.append("keep_pinned: true")
        if name in REMINDERS:
            fm.append(f"keep_reminder: {REMINDERS[name]}")
        if tags:
            fm.append("tags:\n" + "\n".join(f"  - {t}" for t in tags))
        files[name] = "---\n" + "\n".join(fm) + "\n---\n" + body
    js(f"""
    if (!app.vault.getAbstractFileByPath(F)) await app.vault.createFolder(F);
    for (const [name, text] of Object.entries({json.dumps(files)})) {{
        const p = F + "/" + name + ".md";
        const f = app.vault.getAbstractFileByPath(p);
        if (f) await app.vault.modify(f, text); else await app.vault.create(p, text);
    }}
    const bp = F + "/Notes.base";
    if (!app.vault.getAbstractFileByPath(bp)) await app.vault.create(bp, {json.dumps(BOARD)});
    """)


def stage(dark):
    """The demo board in front, nothing of the vault around it."""
    js(f"""
    const p = app.plugins.plugins["full-keep-mode"];
    document.body.removeClass("theme-light", "theme-dark");
    document.body.addClass({json.dumps("theme-dark" if dark else "theme-light")});
    if (!document.getElementById("fkm-shot-style")) {{
        const style = document.head.createEl("style", {{ attr: {{ id: "fkm-shot-style" }} }});
        style.textContent = `.workspace-tab-header-container .workspace-tab-header:not(.is-active) {{ display: none !important; }}
            .status-bar, .workspace-sidedock-vault-profile, .workspace-drawer-header-left {{ display: none !important; }}`;
    }}
    // English dates, whatever the computer's language.
    window.__shotLocale ??= moment.locale();
    moment.locale("en");
    // The side menu shows the demo labels only.
    p.__shotAllLabels ??= p.allLabels;
    p.allLabels = () => [...new Set(app.vault.getMarkdownFiles().filter(f => f.path.startsWith(F + "/")).flatMap(f => p.labelsOf(f)))]
        .filter(l => l.toLowerCase() !== "archived").sort((a, b) => a.localeCompare(b));
    document.querySelectorAll(".modal-container").forEach(m => m.remove());
    await p.setFilter({{ text: "", tag: null, reminders: false }});
    p.activeLabel = "notes";
    app.workspace.leftSplit.collapse();
    app.workspace.rightSplit?.collapse?.();
    const base = app.vault.getAbstractFileByPath(F + "/Notes.base");
    let leaf = app.workspace.getLeavesOfType("bases").find(l => l.view.file?.path === base.path);
    if (!leaf) {{ leaf = app.workspace.getLeaf(app.isMobile ? false : "tab"); await leaf.openFile(base); }}
    app.workspace.setActiveLeaf(leaf, {{ focus: true }});
    window.__shotBoard = leaf;
    await wait(1800);
    leaf.view.containerEl.querySelectorAll(".fkm-board, .view-content").forEach(e => e.scrollTop = 0);
    p.labelsView()?.render();
    await wait(400);
    """)


def shot(name):
    time.sleep(0.6)
    data = lt.ob.call("Page.captureScreenshot", format="png")["data"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.png").write_bytes(base64.b64decode(data))
    print("  saved", name)


def center(selector, note=None):
    return js(f"""const root = window.__shotBoard.view.containerEl;
        const all = [...document.querySelectorAll({json.dumps(selector)})].filter(e => e.getBoundingClientRect().width);
        const el = {f"all.find(e => (e.closest('[data-path]')?.dataset.path ?? '').endsWith('/{note}.md'))" if note else "all[0]"};
        const r = el.getBoundingClientRect(); return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }};""")


def mouse_to(p):
    lt.ob.mouse("mouseMoved", p["x"], p["y"], 0)
    time.sleep(0.4)


def click(p):
    mouse_to(p)
    lt.ob.mouse("mousePressed", p["x"], p["y"])
    lt.ob.mouse("mouseReleased", p["x"], p["y"], 0)


def open_card(note):
    js(f"""const card = [...window.__shotBoard.view.containerEl.querySelectorAll('.fkm-card')].find(c => c.dataset.path.endsWith('/{note}.md'));
        card.querySelector('.fkm-card-title').click();""")
    for _ in range(20):
        time.sleep(0.3)
        if js("return !!document.querySelector('.fkm-note-modal .cm-line');"):
            break
    js("document.activeElement?.blur();")
    time.sleep(1.2)


def close_popups():
    js("document.querySelectorAll('.menu').forEach(m => m.remove()); document.querySelectorAll('.modal-container').forEach(m => m.remove());")
    time.sleep(0.5)


def desktop():
    lt.ob.call("Emulation.setDeviceMetricsOverride", **DESKTOP)
    lt.ob.call("Emulation.setLocaleOverride", locale="en-US")
    wake()
    stage(dark=False)
    mouse_to({"x": 1400, "y": 880})
    shot("desktop-1-board")

    open_card("Moving house")
    shot("desktop-2-checklist")
    close_popups()

    # Hover a card for Keep's buttons, and open its colours.
    js("""const card = [...window.__shotBoard.view.containerEl.querySelectorAll('.fkm-card')].find(c => c.dataset.path.endsWith('/Ideas for the garden.md'));
        card.scrollIntoView({ block: "center" }); await wait(500);""")
    mouse_to(center(".fkm-card .fkm-card-title", "Ideas for the garden"))
    click(center(".fkm-card .fkm-card-actions [aria-label='Colour']", "Ideas for the garden"))
    time.sleep(0.8)
    shot("desktop-3-colours")
    close_popups()
    mouse_to({"x": 1400, "y": 880})

    stage(dark=True)
    js("""const p = app.plugins.plugins["full-keep-mode"]; await p.openLabelsView(true); await wait(600);
        await p.showOnBoard("label:Travel"); await wait(1200);""")
    shot("desktop-4-labels-dark")
    js("""const p = app.plugins.plugins["full-keep-mode"]; await p.showOnBoard("notes"); app.workspace.leftSplit.collapse(); await wait(800);""")

    open_card("Groceries")
    click(center(".fkm-note-modal .fkm-reminder-button"))
    time.sleep(0.8)
    shot("desktop-5-reminder-dark")
    close_popups()


def phone():
    lt.ob.call("Emulation.setDeviceMetricsOverride", **PHONE)
    try:
        js("setTimeout(() => app.emulateMobile(true), 100); return true;")
    except RuntimeError:
        pass
    for _ in range(60):
        time.sleep(1)
        try:
            if lt.ob.js("return !!app.plugins?.plugins?.['full-keep-mode'] && app.workspace.layoutReady;"):
                break
        except RuntimeError:
            pass
    time.sleep(3)
    lt.ob.call("Emulation.setDeviceMetricsOverride", **PHONE)
    lt.ob.call("Emulation.setLocaleOverride", locale="en-US")
    wake()
    assert js("return document.body.hasClass('is-phone');"), "phone layout didn't start"
    stage(dark=False)
    shot("phone-1-board")
    open_card("Moving house")
    shot("phone-2-checklist")
    close_popups()
    js("""await app.plugins.plugins["full-keep-mode"].toggleLabelsView(); await wait(1000);""")
    shot("phone-3-side-menu")
    js("app.workspace.leftSplit.collapse(); await wait(600);")
    stage(dark=True)
    shot("phone-4-board-dark")
    open_card("Trip to Lisbon")
    shot("phone-5-note-dark")
    close_popups()


def cleanup():
    try:
        js("""const p = app.plugins.plugins["full-keep-mode"];
        if (p.__shotAllLabels) { p.allLabels = p.__shotAllLabels; delete p.__shotAllLabels; }
        if (window.__shotLocale) { moment.locale(window.__shotLocale); delete window.__shotLocale; }
        document.getElementById("fkm-shot-style")?.remove();
        document.querySelectorAll(".menu, .modal-container").forEach(m => m.remove());
        await p.setFilter({ text: "", tag: null, reminders: false }); p.activeLabel = "notes";
        for (const l of app.workspace.getLeavesOfType("bases")) if (l.view.file?.path?.startsWith(F + "/")) l.detach();
        const folder = app.vault.getAbstractFileByPath(F);
        if (folder) { for (const f of [...folder.children]) await app.vault.trash(f, true); await app.vault.trash(folder, true); }
        document.body.removeClass("theme-light", "theme-dark");
        document.body.addClass(""" + json.dumps(THEME[0]) + ");")
    except RuntimeError as err:
        print("cleanup:", err)


THEME = [lt.ob.js("return document.body.hasClass('theme-dark') ? 'theme-dark' : 'theme-light';")]
try:
    setup()
    desktop()
    phone()
finally:
    cleanup()
    try:
        if lt.ob.js("return document.body.hasClass('emulate-mobile');"):
            lt.ob.js("setTimeout(() => app.emulateMobile(false), 100); return true;")
            time.sleep(12)
    except RuntimeError:
        pass
    lt.ob.call("Emulation.clearDeviceMetricsOverride")
    lt.ob.call("Emulation.setLocaleOverride")
    try:
        lt.ob.js('require("@electron/remote").getCurrentWebContents().setBackgroundThrottling(true);')
    except RuntimeError:
        pass
print("screenshots in", OUT)
