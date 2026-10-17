#!/usr/bin/env python3
"""
Live tests for Full Keep Mode, run against a real, running Obsidian.

Start Obsidian with its debugging port open (close it first):
    Windows:  "%LOCALAPPDATA%\\Programs\\Obsidian\\Obsidian.exe" --remote-debugging-port=9222
    macOS:    open -a Obsidian --args --remote-debugging-port=9222
Then, with the plugin enabled in the open vault:
    pip install websocket-client
    python tests/live_test.py

The tests only use temporary notes (created in a "Full Keep Mode tests" folder
and moved to the trash afterwards). Open pop-ups are hidden while they run.
Mouse drags use real input events, so keep the Obsidian window visible.
"""
import itertools
import json
import os
import sys
import time
import urllib.request

import websocket

PORT = 9222
FOLDER = "Full Keep Mode tests"
# The tests run in a vault of their own, never in a vault with real notes: open it in
# Obsidian next to yours (its window title names it). FKM_VAULT picks another one.
VAULT = os.environ.get("FKM_VAULT", "Full Keep Mode test vault")


class Obsidian:
    def __init__(self):
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list"))
        windows = [p for p in pages if p["type"] == "page" and p["url"].startswith("app://obsidian.md")]
        page = next((p for p in windows if f" - {VAULT} - Obsidian" in p["title"]), None)
        if page is None:
            raise SystemExit(f'The vault "{VAULT}" is not open in Obsidian (open: {[p["title"] for p in windows]}). '
                             "The tests only run in their own vault, so they can't touch real notes.")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
        self.ids = itertools.count(1)

    def call(self, method, **params):
        msg_id = next(self.ids)
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    def js(self, code):
        res = self.call("Runtime.evaluate", expression=f"(async () => {{ {code} }})()",
                        awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"]["exception"]["description"])
        return res["result"].get("value")

    def mouse(self, kind, x, y, buttons=1):
        self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left",
                  buttons=buttons if kind != "mouseReleased" else 0, clickCount=1)


ob = Obsidian()
results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"   ({detail})" if detail and not condition else ""))


# ----- helpers running inside Obsidian -------------------------------------------------------

PRELUDE = f"""
const wait = ms => new Promise(r => setTimeout(r, ms));
const FOLDER = {json.dumps(FOLDER)};
"""


def open_note(name, content, settings=None):
    """Create/overwrite a test note, open it in a tab, put the cursor at the end."""
    ob.js(PRELUDE + f"""
    const plugin = app.plugins.plugins["full-keep-mode"];
    window.__tcSaved ??= JSON.stringify(plugin.settings);
    Object.assign(plugin.settings, JSON.parse({json.dumps(json.dumps(settings or {}))}));
    plugin.refreshEditors();
    if (!app.vault.getAbstractFileByPath(FOLDER)) await app.vault.createFolder(FOLDER);
    const path = FOLDER + "/" + {json.dumps(name)} + ".md";
    for (const l of app.workspace.getLeavesOfType("markdown")) if (l.view.file?.path?.startsWith(FOLDER + "/")) l.detach();
    let f = app.vault.getAbstractFileByPath(path);
    if (f) await app.vault.modify(f, {json.dumps(content)}); else f = await app.vault.create(path, {json.dumps(content)});
    const leaf = app.workspace.getLeaf("tab");
    await leaf.openFile(f, {{ state: {{ mode: "source", source: false }} }});
    app.workspace.setActiveLeaf(leaf, {{ focus: true }});
    window.__tcLeaf = leaf;
    const cm = leaf.view.editor.cm;
    cm.dispatch({{ selection: {{ anchor: cm.state.doc.length }} }});
    await wait(1500);
    """)


def text():
    return ob.js("return window.__tcLeaf.view.editor.cm.state.doc.toString();")


def body():
    """The checklist part of the note, tabs shown as →."""
    return text().split("\n\n\n", 1)[-1].strip().replace("\t", "→")


def line_el(label):
    return f"""
    const cm = window.__tcLeaf.view.editor.cm;
    const el = [...cm.contentDOM.querySelectorAll(".cm-line")].find(e => e.textContent.trim().endsWith({json.dumps(label)}));
    """


def click_checkbox(label):
    ob.js(PRELUDE + line_el(label) + """
    el.querySelector("input.task-list-item-checkbox").click();
    await wait(700);
    cm.dispatch({ selection: { anchor: cm.state.doc.length } });
    await wait(300);
    """)


def drag(label, dx, target=None, lower=True):
    # Where the grip is once it has settled (the plugin places it a moment after drawing).
    g = None
    for _ in range(20):
        now = ob.js(line_el(label) + """
        const g = el.querySelector(".fkm-grip").getBoundingClientRect();
        return { x: g.left + g.width / 2, y: g.top + g.height / 2 };
        """)
        if now == g:
            break
        g = now
        time.sleep(0.15)
    x, y = g["x"], g["y"]
    ty = y
    if target:
        r = ob.js(line_el(target) + "const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom };")
        ty = r["bottom"] - 3 if lower else r["top"] + 3
    ob.mouse("mouseMoved", x, y, 0)
    ob.mouse("mousePressed", x, y)
    for k in range(1, 11):
        ob.mouse("mouseMoved", x + dx * k / 10, y + (ty - y) * k / 10)
        time.sleep(0.03)
    ob.mouse("mouseReleased", x + dx, ty)
    time.sleep(0.7)


def press_tab_on(label):
    ob.js(PRELUDE + f"""
    const cm = window.__tcLeaf.view.editor.cm;
    const doc = cm.state.doc;
    let n = 1; while (!doc.line(n).text.trim().endsWith({json.dumps(label)})) n++;
    cm.focus();
    cm.dispatch({{ selection: {{ anchor: doc.line(n).to }} }});
    cm.contentDOM.dispatchEvent(new KeyboardEvent("keydown", {{ key: "Tab", code: "Tab", keyCode: 9, bubbles: true, cancelable: true }}));
    await wait(400);
    cm.dispatch({{ selection: {{ anchor: cm.state.doc.length }} }});
    await wait(300);
    """)


def key(name, vk, modifiers=0):
    """A real key press in the focused editor (modifiers: 2 = Ctrl)."""
    code = name if len(name) > 1 else f"Key{name.upper()}"
    for kind in ("rawKeyDown", "keyUp"):
        ob.call("Input.dispatchKeyEvent", type=kind, key=name, code=code, windowsVirtualKeyCode=vk, modifiers=modifiers)
    time.sleep(0.4)


def undo():
    ob.js(PRELUDE + "window.__tcLeaf.view.editor.undo(); await wait(400);")


HEAD = "Test list:\n\n\n"


# ----- board helpers (needs the Keep Bases View plugin) ---------------------------------------

BOARD = f"""filters:
  and:
    - 'file.ext == "md"'
    - file.inFolder("{FOLDER}")
    - file.name.startsWith("Card ")
formulas:
  board_order: 'if(keep_order, keep_order, number(file.ctime))'
views:
  - type: keep-board
    name: Board
    sort:
      - property: keep_pinned
        direction: DESC
      - property: formula.board_order
        direction: DESC
"""


def open_board(cards):
    """Create test cards {name: keep_order} and a board showing only them."""
    notes = {name: f"---\nkeep_order: {order}\n---\nText of {name}\n" for name, order in cards.items()}
    ob.js(PRELUDE + f"""
    if (!app.vault.getAbstractFileByPath(FOLDER)) await app.vault.createFolder(FOLDER);
    for (const [name, text] of Object.entries({json.dumps(notes)})) {{
        const p = FOLDER + "/" + name + ".md";
        const f = app.vault.getAbstractFileByPath(p);
        if (f) await app.vault.modify(f, text); else await app.vault.create(p, text);
    }}
    const bp = FOLDER + "/board.base";
    let b = app.vault.getAbstractFileByPath(bp);
    if (b) await app.vault.modify(b, {json.dumps(BOARD)}); else b = await app.vault.create(bp, {json.dumps(BOARD)});
    const leaf = app.workspace.getLeaf("tab");
    await leaf.openFile(b);
    app.workspace.setActiveLeaf(leaf, {{ focus: true }});
    window.__fkmBoard = leaf;
    await wait(2500);
    """)


def card_order():
    """Cards as they appear on screen: top to bottom, then left to right."""
    return ob.js("""return [...window.__fkmBoard.view.containerEl.querySelectorAll('.fkm-card[data-path]')]
                    .map(c => ({ r: c.getBoundingClientRect(), name: c.getAttribute('data-path').split('/').pop().replace('.md', '') }))
                    .sort((a, b) => Math.round(a.r.top / 20) - Math.round(b.r.top / 20) || a.r.left - b.r.left)
                    .map(c => c.name);""")


def press_escape():
    """Real Escape keys until the topmost (test) pop-up is closed. The first one may
    only end editing the title; at most three."""
    before = modal_open()
    for _ in range(3):
        ob.call("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        ob.call("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        time.sleep(0.8)
        if modal_open() < before:
            break
    time.sleep(0.6)


def card_center(name):
    return ob.js(f"""const c = [...window.__fkmBoard.view.containerEl.querySelectorAll('.fkm-card[data-path]')]
                     .find(c => c.getAttribute('data-path').endsWith('/{name}.md'));
                     const r = c.getBoundingClientRect(); return {{ x: r.left + r.width / 2, y: r.top + 20 }};""")


def frontmatter(name):
    return ob.js(f"""const f = app.vault.getAbstractFileByPath(FOLDER_PATH + '/{name}.md');
                     return app.metadataCache.getFileCache(f)?.frontmatter ?? {{}};""".replace("FOLDER_PATH", json.dumps(FOLDER)))


def modal_open():
    return ob.js("return [...document.querySelectorAll('.modal-container .fkm-note-modal')].filter(m => !m.closest('[data-tc-hidden]')).length;")

def scroll_check():
    open_note("scrolling", "".join(f"Line {i}\n" for i in range(80)) + "\n- [ ] A\n- [ ] B\n- [ ] C\n")
    ob.js(PRELUDE + "window.__tcLeaf.view.editor.cm.scrollDOM.scrollTop = 1e6; await wait(400);")
    before = ob.js(PRELUDE + line_el("B") + "el.scrollIntoView({ block: 'center' }); await wait(400); return cm.scrollDOM.scrollTop;")
    drag("B", 40)
    after = ob.js("return window.__tcLeaf.view.editor.cm.scrollDOM.scrollTop;")
    check("dragging an item keeps the note where it is (no jump to the top)",
          before > 100 and abs(after - before) < 5 and text().endswith("- [ ] A\n\t- [ ] B\n- [ ] C\n"), (before, after, text()[-30:]))


# ----- the tests -----------------------------------------------------------------------------

def main():

    try:
        # Leftovers of an earlier run that couldn't clean up (e.g. Obsidian stopped answering).
        ob.js(PRELUDE + """const old = app.vault.getAbstractFileByPath(FOLDER);
            if (old) { for (const f of [...old.children]) await app.vault.trash(f, true); await app.vault.trash(old, true); }""")
        ob.js("""document.querySelectorAll(".modal-container").forEach(m => { m.dataset.tcHidden = "1"; m.style.visibility = "hidden"; });""")
        info = ob.js("""const p = app.plugins.plugins["full-keep-mode"]; return { loaded: !!p, version: app.plugins.manifests["full-keep-mode"]?.version };""")
        print(f"Full Keep Mode {info['version']}")
        check("plugin is loaded", info["loaded"])

        print("Ticking")
        start = "- [ ] A\n- [ ] B\n\t- [ ] B1\n- [ ] C"
        open_note("ticking", HEAD + start)
        click_checkbox("A")
        check("ticked item moves below the others", body() == "- [ ] B\n→- [ ] B1\n- [ ] C\n- [x] A", body())
        section = ob.js("return [...window.__tcLeaf.view.editor.cm.contentDOM.querySelectorAll('.fkm-ticked-label')].map(e => e.textContent);")
        check("divider shows \"1 ticked item\"", section == ["1 ticked item"], section)
        undo()
        check("one undo restores the list exactly", body() == start.replace("\t", "→"), body())
        click_checkbox("B")
        check("ticking a parent ticks its sub-items and moves them along", body() == "- [ ] A\n- [ ] C\n- [x] B\n→- [x] B1", body())
        open_note("untick place", HEAD + "- [ ] A\n- [ ] B\n- [ ] C\n- [ ] D")
        click_checkbox("B")
        moved_down = body()
        click_checkbox("B")
        check("unticking an item puts it back where it was, like Keep", (moved_down, body()) == ("- [ ] A\n- [ ] C\n- [ ] D\n- [x] B", "- [ ] A\n- [ ] B\n- [ ] C\n- [ ] D"), (moved_down, body()))
        click_checkbox("A")
        click_checkbox("A")
        check("…also the first item (back to the top)", body() == "- [ ] A\n- [ ] B\n- [ ] C\n- [ ] D", body())

        print("Ghost parents")
        open_note("ghosts", HEAD + "- [ ] P\n\t- [ ] P1\n\t- [ ] P2\n- [ ] Q")
        click_checkbox("P2")
        ghost = ob.js("""const s = window.__tcLeaf.view.editor.cm.contentDOM.querySelector('.fkm-ticked-section');
                         return s ? s.innerText.replace(/\\n+/g, ' | ') : null;""")
        check("ticked sub-item shows under a ghost parent", ghost == "1 ticked item | P | P2", ghost)
        check("…while the note keeps it under its parent", body() == "- [ ] P\n→- [ ] P1\n→- [x] P2\n- [ ] Q", body())
        ob.js(PRELUDE + """const box = window.__tcLeaf.view.editor.cm.contentDOM.querySelector('.fkm-ghost-child input'); box.click(); await wait(700);""")
        check("unticking it in the ghost section brings it back", body() == "- [ ] P\n→- [ ] P1\n→- [ ] P2\n- [ ] Q", body())

        print("Drag and drop (real mouse events)")
        open_note("dragging", HEAD + "- [ ] P\n\t- [ ] P1\n\t- [ ] P2\n\t- [x] P3\n- [ ] Q\n\t- [ ] Q1\n- [ ] R")
        drag("P2", -70)
        check("sub-item moved out in place takes the sub-items below it",
              body() == "- [ ] P\n→- [ ] P1\n- [ ] P2\n→- [x] P3\n- [ ] Q\n→- [ ] Q1\n- [ ] R", body())
        drag("P2", +70)
        check("moving it back in makes both sub-items of P again",
              body() == "- [ ] P\n→- [ ] P1\n→- [ ] P2\n→- [x] P3\n- [ ] Q\n→- [ ] Q1\n- [ ] R", body())
        drag("P", 0, target="Q1")
        check("item dropped below another lands after that item's sub-items, with its own",
              body() == "- [ ] Q\n→- [ ] Q1\n- [ ] P\n→- [ ] P1\n→- [ ] P2\n→- [x] P3\n- [ ] R", body())
        undo()
        check("one undo reverts a drag", body().startswith("- [ ] P\n→- [ ] P1"), body())

        print("Indenting (two levels)")
        open_note("indenting", HEAD + "- [ ] A\n\t- [ ] A1\n- [ ] B\n\t- [ ] B1\n- [ ] C")
        before = body()
        press_tab_on("A1")
        check("Tab on an indented item does nothing", body() == before, body())
        press_tab_on("A")
        check("Tab on the first item does nothing", body() == before, body())
        press_tab_on("B")
        check("Tab on an item with sub-items indents both one level (no third level)",
              body() == "- [ ] A\n→- [ ] A1\n→- [ ] B\n→- [ ] B1\n- [ ] C", body())
        drag("C", +140)
        check("dragging far right still indents only one level",
              body() == "- [ ] A\n→- [ ] A1\n→- [ ] B\n→- [ ] B1\n→- [ ] C", body())

        # Dragging an item to the bottom edge scrolls the note, like Keep, also while the
        # pointer rests there; the item lands further down than was visible at first.
        open_note("autoscroll", "".join(f"- [ ] Item {n}\n" for n in range(1, 81)))
        start = ob.js(PRELUDE + """const cm = window.__tcLeaf.view.editor.cm;
            cm.contentDOM.blur(); cm.scrollDOM.scrollTop = 0; await wait(400);
            const l = [...cm.contentDOM.querySelectorAll('.cm-line')].find(l => /(^|\\D)Item 1$/.test(l.textContent.trim()));
            const g = l.querySelector('.fkm-grip').getBoundingClientRect();
            const box = cm.scrollDOM.getBoundingClientRect();
            const visible = [...cm.contentDOM.querySelectorAll('.cm-line')].filter(l => l.getBoundingClientRect().bottom <= box.bottom).length;
            return { x: g.left + g.width / 2, y: g.top + g.height / 2, bottom: Math.min(box.bottom, innerHeight), visible };""")
        ob.mouse("mouseMoved", start["x"], start["y"], 0)
        ob.mouse("mousePressed", start["x"], start["y"])
        edge_y = start["bottom"] - 15
        for k in range(1, 11):
            ob.mouse("mouseMoved", start["x"], start["y"] + (edge_y - start["y"]) * k / 10)
            time.sleep(0.03)
        time.sleep(1.2)  # resting at the edge
        ob.mouse("mouseReleased", start["x"], edge_y, 0)
        time.sleep(0.8)
        after = ob.js("""const cm = window.__tcLeaf.view.editor.cm;
            return { scrolled: cm.scrollDOM.scrollTop, line: cm.state.doc.toString().split('\\n').indexOf('- [ ] Item 1') + 1 };""")
        check("dragging an item to the bottom edge scrolls the note, and it lands further down",
              after["scrolled"] > 200 and after["line"] > start["visible"] + 5, (start, after))

        # The indent button of the phone toolbar runs Obsidian's "Indent list" command.
        open_note("indent button", "- [ ] A\n- [ ] B\n")
        indent_cmd = """const cm = window.__tcLeaf.view.editor.cm; const d = cm.state.doc;
            cm.dispatch({ selection: { anchor: d.line(2).to } });
            app.commands.executeCommandById('editor:indent-list'); await wait(400);"""
        ob.js(PRELUDE + indent_cmd)
        ob.js(PRELUDE + indent_cmd)
        check("the toolbar's indent button follows the same rules (two levels)", text() == "- [ ] A\n\t- [ ] B\n", repr(text()))

        print("Multi-line items")
        long = "word " * 40
        open_note("multiline", HEAD + f"- [ ] First line\n\t\tsecond line\n\t\tthird line {long}\n- [ ] Next {long}")
        xs = ob.js("""
        const cm = window.__tcLeaf.view.editor.cm;
        const firstLetterXs = el => {
            const out = []; const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let t;
            while ((t = w.nextNode())) for (let i = 0; i < t.length; i++) {
                if (!/\\S/.test(t.textContent[i])) continue;
                const g = document.createRange(); g.setStart(t, i); g.setEnd(t, i + 1); const r = g.getBoundingClientRect();
                if (!out.length || r.top > out[out.length - 1].top + 5) out.push({ top: r.top, x: Math.round(r.left) });
            }
            return out.map(o => o.x);
        };
        const els = [...cm.contentDOM.querySelectorAll('.cm-line')];
        const at = t => firstLetterXs(els.find(e => e.textContent.includes(t)));
        return { first: at('First line'), second: at('second line'), third: at('third line'), next: at('Next') };
        """)
        all_x = xs["first"] + xs["second"] + xs["third"] + xs["next"]
        check("extra lines and wrapped lines start under the item's text", len(set(all_x)) == 1, xs)

        # Shift+Enter: a new line inside the item, lined up, no indentation lines, and
        # Backspace at its start joins it back.
        open_note("shift enter", "- [ ] A\n\t- [ ] B\n- [ ] C\n")
        ob.js(PRELUDE + "const cm = window.__tcLeaf.view.editor.cm; cm.focus(); cm.dispatch({ selection: { anchor: cm.state.doc.line(2).to } }); await wait(200);")
        ob.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, modifiers=8, text="\r", unmodifiedText="\r")
        ob.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13, modifiers=8)
        time.sleep(0.5)
        empty_line = ob.js(PRELUDE + """await wait(300); const l = [...window.__tcLeaf.view.editor.cm.contentDOM.querySelectorAll('.cm-line')][2];
            const g = l.querySelector('.cm-indent'); return { extra: l.classList.contains('fkm-extra'), guide: g ? getComputedStyle(g, '::before').display : 'none' };""")
        check("Shift+Enter starts a line inside the item, without indentation lines",
              text() == "- [ ] A\n\t- [ ] B\n\t\t\n- [ ] C\n" and empty_line == {"extra": True, "guide": "none"}, (repr(text()), empty_line))
        ob.call("Input.insertText", text="second")
        time.sleep(0.4)
        xs = ob.js(r"""const ls = [...window.__tcLeaf.view.editor.cm.contentDOM.querySelectorAll('.cm-line')];
            const xOf = (l, word) => { const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT); let n;
                while ((n = w.nextNode())) { const i = n.textContent.indexOf(word); if (i >= 0) { const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1); return Math.round(r.getBoundingClientRect().left); } } return null; };
            return [xOf(ls[1], 'B'), xOf(ls[2], 'second')];""")
        check("…typed text starts right under the item's text", xs[0] is not None and xs[0] == xs[1], xs)
        key("Home", 36)
        key("Backspace", 8)
        check("…and Backspace at its start joins it back to the item", text() == "- [ ] A\n\t- [ ] Bsecond\n- [ ] C\n", repr(text()))

        # Enter at the end of an item with sub-items: a new first sub-item, like Keep.
        def enter_at_end_of(line_no):
            ob.js(PRELUDE + f"const cm = window.__tcLeaf.view.editor.cm; cm.focus(); cm.dispatch({{ selection: {{ anchor: cm.state.doc.line({line_no}).to }} }}); await wait(200);")
            ob.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, text="\r", unmodifiedText="\r")
            ob.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
            time.sleep(0.4)
            ob.call("Input.insertText", text="New")
            time.sleep(0.4)
            return text()
        open_note("enter parent", "- [ ] A\n\t- [ ] B\n- [ ] C\n")
        after = enter_at_end_of(1)
        check("Enter at the end of an item with sub-items starts a new first sub-item", after == "- [ ] A\n\t- [ ] New\n\t- [ ] B\n- [ ] C\n", repr(after))
        open_note("enter plain", "- [ ] A\n\t- [ ] B\n- [ ] C\n")
        after = enter_at_end_of(3)
        check("…and at the end of one without, a new item as usual", after == "- [ ] A\n\t- [ ] B\n- [ ] C\n- [ ] New\n", repr(after))

        # Enter follows Keep's rules everywhere in a checklist, never Obsidian's list rules.
        enter_notes = iter(range(1, 100))
        def enters(note, at, presses, typed="X", at_start=False):
            open_note(f"enter keys {next(enter_notes)}", note)
            ob.js(PRELUDE + f"""const cm = window.__tcLeaf.view.editor.cm; cm.focus(); const d = cm.state.doc.toString();
                const i = d.indexOf({json.dumps(at)}); cm.dispatch({{ selection: {{ anchor: i + ({0 if at_start else len(at)}) }} }}); await wait(200);""")
            for _ in range(presses):
                ob.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, text="\r", unmodifiedText="\r")
                ob.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
                time.sleep(0.3)
            if typed:
                ob.call("Input.insertText", text=typed)
                time.sleep(0.3)
            return text()
        got = enters("- [ ] A\n\t- [ ] B\n- [ ] C\n", "A", 3)
        check("Enter three times at the end of an item with sub-items: three new sub-items, nothing moves out or loses its checkbox",
              got == "- [ ] A\n\t- [ ] \n\t- [ ] \n\t- [ ] X\n\t- [ ] B\n- [ ] C\n", repr(got))
        got = enters("- [ ] A\n- [ ] \n- [ ] C\n", "- [ ] \n- [ ] C", 1, at_start=True)
        check("Enter on an empty item: another empty item (no end of the list)", got == "- [ ] A\n- [ ] \n- [ ] X\n- [ ] C\n", repr(got))
        got = enters("- [ ] Apple pie\n- [ ] C\n", "Apple", 1)
        check("Enter in the middle of an item's text splits it", got == "- [ ] Apple\n- [ ] X pie\n- [ ] C\n", repr(got))
        got = enters("- [ ] A\n- [ ] Banana\n", "Banana", 1, at_start=True)
        check("Enter at the start of an item's text: a new empty item above", got == "- [ ] A\n- [ ] \n- [ ] XBanana\n", repr(got))

        # Keep's x: on the item being edited, deletes it with its sub-items; Undo brings it back.
        open_note("delete x", "- [ ] A\n- [ ] B\n\t- [ ] B1\n\t\tmore of B1\n- [ ] C\n")
        x = ob.js(PRELUDE + """const cm = window.__tcLeaf.view.editor.cm; cm.focus();
            const d = cm.state.doc.toString(); cm.dispatch({ selection: { anchor: d.indexOf('B\\n') } }); await wait(300);
            const shown = [...cm.contentDOM.querySelectorAll('.fkm-delete')].filter(e => getComputedStyle(e).visibility === 'visible')
                .map(e => e.closest('.cm-line').textContent.trim());
            const el = [...cm.contentDOM.querySelectorAll('.cm-line')].find(l => l.textContent.trim().endsWith('B')).querySelector('.fkm-delete');
            const r = el.getBoundingClientRect(); return { shown, x: r.left + r.width / 2, y: r.top + r.height / 2 };""")
        check("the x shows on the item being edited only", x["shown"] == ["B"], x["shown"])
        ob.mouse("mouseMoved", x["x"], x["y"], 0)
        ob.mouse("mousePressed", x["x"], x["y"])
        ob.mouse("mouseReleased", x["x"], x["y"], 0)
        time.sleep(0.6)
        after = ob.js(PRELUDE + """const cm = window.__tcLeaf.view.editor.cm; const h = cm.state.selection.main.head;
            return { text: cm.state.doc.toString(), at: cm.state.doc.sliceString(h - 1, h), focused: cm.hasFocus };""")
        check("…tapping it deletes the item with its sub-items, the cursor goes to the item above",
              after["text"] == "- [ ] A\n- [ ] C\n" and after["at"] == "A" and after["focused"], after)
        undo()
        check("…and Undo brings it back", text() == "- [ ] A\n- [ ] B\n\t- [ ] B1\n\t\tmore of B1\n- [ ] C\n", repr(text()))

        # A ticked item with a Shift+Enter line: both lines struck through.
        open_note("ticked lines", "- [ ] A\n- [x] Done\n\tmore of done\n")
        deco = ob.js("""const ls = [...window.__tcLeaf.view.editor.cm.contentDOM.querySelectorAll('.cm-line')];
            const of = t => getComputedStyle(ls.find(l => l.textContent.includes(t))).textDecorationLine;
            const inner = t => { const l = ls.find(l => l.textContent.includes(t)); const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT); let n;
                while ((n = w.nextNode())) if (n.textContent.includes(t)) return getComputedStyle(n.parentElement).textDecorationLine + '|' + of(t); };
            return { first: inner('Done'), extra: of('more of done') };""")
        check("a ticked item's Shift+Enter lines are struck through too", "line-through" in deco["extra"] and "line-through" in deco["first"], deco)

        # The drop line while dragging: midway between the two items.
        open_note("drop line", "- [ ] A\n- [ ] B\n- [ ] C\n- [ ] D\n")
        g = ob.js(line_el("A") + "const r = el.querySelector('.fkm-grip').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 };")
        tgt = ob.js(line_el("C") + "const r = el.getBoundingClientRect(); return { y: r.top + 4 };")
        ob.mouse("mouseMoved", g["x"], g["y"], 0)
        ob.mouse("mousePressed", g["x"], g["y"])
        for k in range(1, 9):
            ob.mouse("mouseMoved", g["x"], g["y"] + (tgt["y"] - g["y"]) * k / 8)
            time.sleep(0.03)
        mid = ob.js("""const cm = window.__tcLeaf.view.editor.cm;
            const textBox = t => { const l = [...cm.contentDOM.querySelectorAll('.cm-line')].find(l => l.textContent.trim().endsWith(t));
                const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT); let n; while ((n = w.nextNode())) if (n.textContent.includes(t)) { const r = document.createRange(); r.selectNodeContents(n); return r.getBoundingClientRect(); } };
            const ind = document.querySelector('.fkm-drop-indicator').getBoundingClientRect();
            return { line: ind.top + ind.height / 2, midway: (textBox('B').bottom + textBox('C').top) / 2 };""")
        ob.mouse("mouseMoved", g["x"], g["y"])
        ob.mouse("mouseReleased", g["x"], g["y"], 0)
        time.sleep(0.6)
        check("the drop line is midway between the items (within a pixel)", abs(mid["line"] - mid["midway"]) <= 1.0, mid)

        # The note's properties: no text to type in. Enter at the very start of the note,
        # Backspace there, or a cursor put in front of them changes nothing up there.
        open_note("properties closed", "---\nkeep_color: blue\n---\n- [ ] A\n")
        prop = ob.js(PRELUDE + """const cm = window.__tcLeaf.view.editor.cm; cm.focus();
            cm.dispatch({ selection: { anchor: 0 } }); await wait(200);
            return cm.state.selection.main.head === cm.state.doc.toString().indexOf('- [ ] A') || cm.state.doc.sliceString(cm.state.selection.main.head - 1, cm.state.selection.main.head + 1);""")
        key("Home", 36)
        ob.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, text="\r", unmodifiedText="\r")
        ob.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
        time.sleep(0.3)
        key("Backspace", 8)
        key("Backspace", 8)
        after = text()
        check("the note's properties can't be typed into (Enter or Backspace at the start, a cursor put in front)",
              after.startswith("---\nkeep_color: blue\n---\n") and prop is not False, repr(after))

        print("Keep-style editing")
        open_note("editing", "---\ntags:\n  - Shopping\nkeep_created: 2024-11-10T02:44:02\n---\n- [ ] Alpha\n- [ ] Beta\n→- [x] Gamma\n".replace("→", "\t"))
        boxes = ob.js(PRELUDE + """const cm = window.__tcLeaf.view.editor.cm; const d = cm.state.doc;
            const out = [];
            for (const sel of [{ anchor: d.line(7).from }, { anchor: d.line(6).from + 3, head: d.line(8).to }]) {
                cm.dispatch({ selection: sel }); await wait(250);
                out.push([...cm.contentDOM.querySelectorAll('.cm-line.HyperMD-task-line')].map(l => l.querySelectorAll('input').length));
            }
            return out;""")
        check("checkboxes stay checkboxes under the cursor and a selection (no raw \"- [ ]\")",
              boxes == [[1, 1], [1, 1]], boxes)  # (the ticked Gamma is in the ticked section)
        where = ob.js("""const cm = window.__tcLeaf.view.editor.cm; const l = cm.state.doc.line(7);
            cm.dispatch({ selection: { anchor: l.from + 1 } }); return cm.state.selection.main.head - l.from;""")
        check("the cursor can't go into \"- [ ]\": it goes to the item's text", where == 6, where)
        ob.js("const cm = window.__tcLeaf.view.editor.cm; cm.focus(); cm.dispatch({ selection: { anchor: cm.state.doc.line(7).from + 6 } });")
        key("ArrowLeft", 37)
        pos = ob.js("const cm = window.__tcLeaf.view.editor.cm; const h = cm.state.selection.main.head; const l = cm.state.doc.lineAt(h); return [l.number, h - l.from];")
        check("Left at the start of an item goes to the end of the item above", pos == [6, 11], pos)
        ob.js("const cm = window.__tcLeaf.view.editor.cm; cm.dispatch({ selection: { anchor: cm.state.doc.line(7).from + 6 } });")
        key("Backspace", 8)
        check("Backspace at the start of an item joins it to the item above", text().endswith("- [ ] AlphaBeta\n\t- [x] Gamma\n"), repr(text()))
        undo()
        ob.js("const cm = window.__tcLeaf.view.editor.cm; cm.focus(); cm.dispatch({ selection: { anchor: cm.state.doc.line(6).to } });")
        key("Delete", 46)
        check("Delete at the end of an item joins the next item's text", text().endswith("- [ ] AlphaBeta\n\t- [x] Gamma\n"), repr(text()))
        undo()
        key("a", 65, 2)
        sel = ob.js("const cm = window.__tcLeaf.view.editor.cm; const s = cm.state.selection.main; return cm.state.sliceDoc(s.from, s.to);")
        check("Ctrl+A selects the note's text, not its properties", sel == "- [ ] Alpha\n- [ ] Beta\n\t- [x] Gamma\n", repr(sel))
        foot = ob.js("""const el = window.__tcLeaf.view.contentEl;
            const mc = el.querySelector('.metadata-container');
            return { props: mc ? getComputedStyle(mc).display : 'none', footer: el.querySelector('.fkm-note-footer')?.innerText ?? null,
                     created: el.querySelector('.fkm-edited')?.getAttribute('aria-label') };""")
        check("properties are hidden; labels and \"Edited\" are shown below the note",
              foot["props"] == "none" and foot["footer"] and foot["footer"].startswith("Shopping") and "Edited" in foot["footer"]
              and foot["created"] == "Created 10 Nov 2024".replace("Nov", ob.js("return moment('2024-11-10').format('MMM');")), foot)
        ob.js(PRELUDE + """window.__tcLeaf.view.contentEl.querySelector('.fkm-label-add').click(); await wait(400);
            const input = document.querySelector('.fkm-label-modal .fkm-label-input');
            input.value = 'Errands'; input.dispatchEvent(new Event('input'));
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); await wait(800);""")
        ob.js(PRELUDE + "document.querySelector('.fkm-label-modal .modal-header-button, .fkm-label-modal .modal-close-button')?.click(); await wait(400);")
        check("the label button below the note adds a new label", frontmatter("editing").get("tags") == ["Shopping", "Errands"], frontmatter("editing"))
        bars = ob.js(PRELUDE + """const bar = window.__tcLeaf.view.containerEl.querySelector('.fkm-bottom-bar');
            const buttons = [...bar.querySelectorAll('.fkm-bottom-button')].map(b => b.getAttribute('aria-label'));
            bar.querySelector('[aria-label="Add"]').click(); await wait(300);
            const add = [...document.querySelectorAll('.menu .menu-item')].map(i => i.innerText.trim());
            document.querySelector('.menu')?.remove();
            bar.querySelector('[aria-label="More"]').click(); await wait(300);
            const more = [...document.querySelectorAll('.menu .menu-item')].map(i => i.innerText.trim());
            document.querySelector('.menu')?.remove();
            return { buttons, add, more };""")
        check("Keep's bottom bar (phones): +, colour, undo, redo, ⋮ with Keep's menus",
              bars["buttons"] == ["Add", "Colour", "Undo", "Redo", "More"] and bars["add"][0] == "Hide checkboxes"
              and bars["more"][:3] == ["Delete", "Make a copy", "Labels"], bars)
        open_note("grips", "- [ ] Parent\n\t- [ ] Child\n")
        grips = ob.js(PRELUDE + """const cm = window.__tcLeaf.view.editor.cm;
            cm.dispatch({ selection: { anchor: cm.state.doc.length } }); await wait(400);
            const lines = [...cm.contentDOM.querySelectorAll('.cm-line.fkm-task')];
            const mid = el => { const r = el.getBoundingClientRect(); return r.left + r.width / 2; };
            const parent = lines.find(l => l.classList.contains('fkm-depth-0'));
            const child = lines.find(l => l.classList.contains('fkm-depth-1'));
            if (!parent || !child) return [...cm.contentDOM.querySelectorAll('.cm-line')].map(l => l.className + ' | ' + l.textContent).join(' // ');
            return Math.round(mid(child.querySelector('.fkm-grip')) - mid(parent.querySelector('input'))) || 0; /* no -0: it cannot be sent back */""")
        check("like Keep, a sub-item's grip is right below its parent's checkbox", isinstance(grips, (int, float)) and abs(grips) <= 2, repr(grips))

        # Dragging must not scroll the note (on phones it jumped to the top).
        if ob.js("return document.visibilityState === 'hidden';"):
            print("  skipped: the scrolling check (the Obsidian window is hidden)")
        else:
            scroll_check()

        open_note("plain", "Milk\nBread\n")
        ob.js(PRELUDE + "await app.plugins.plugins['full-keep-mode'].setCheckboxes(window.__tcLeaf.view.file, true); await wait(500);")
        on = text()
        ob.js(PRELUDE + "await app.plugins.plugins['full-keep-mode'].setCheckboxes(window.__tcLeaf.view.file, false); await wait(500);")
        check("\"Show checkboxes\" turns lines into a checklist, \"Hide checkboxes\" back",
              on == "- [ ] Milk\n- [ ] Bread\n" and text() == "Milk\nBread\n", (on, text()))

        # A Keep title the file name can't hold ("A/B" is saved as "AB").
        open_note("AB list", "---\nkeep_title: A/B list\n---\n- [ ] One\n")
        shown = ob.js(PRELUDE + """await wait(500); const el = window.__tcLeaf.view.contentEl;
            return { title: el.querySelector('.fkm-title')?.textContent ?? null,
                     inline: getComputedStyle(el.querySelector('.inline-title:not(.fkm-title)')).display };""")
        check("an imported note shows its Keep title (\"A/B list\"), not the file name", shown == {"title": "A/B list", "inline": "none"}, shown)
        renamed = ob.js(PRELUDE + """const el = window.__tcLeaf.view.contentEl.querySelector('.fkm-title');
            el.focus(); el.textContent = 'C/D list'; el.blur(); await wait(1200);
            const f = window.__tcLeaf.view.file;
            return { file: f.basename, title: app.metadataCache.getFileCache(f)?.frontmatter?.keep_title };""")
        check("editing the title updates keep_title and renames the note", renamed == {"file": "CD list", "title": "C/D list"}, renamed)

        print("Import from Google Keep")
        export = {
            "format": "full-keep-mode-export", "version": 1,
            "notes": [
                {"id": "a", "serverId": "srvA", "type": "list", "title": "Packing", "text": "", "order": 300,
                 "items": [
                     {"text": "Parent", "checked": False, "children": [
                         {"text": "Child 1", "checked": False, "children": [{"text": "Grandchild", "checked": False, "children": []}]},
                         {"text": "Child 2", "checked": True, "children": []}]},
                     {"text": "Done", "checked": True, "children": []},
                     {"text": "Two lines\nsecond line", "checked": False, "children": []}],
                 "color": "CERULEAN", "pinned": True, "archived": False, "trashed": False,
                 "labels": ["Book club"], "created": "2024-11-10T02:44:02.000Z", "edited": "2024-11-11T03:05:16.000Z",
                 "links": [], "media": []},
                {"id": "b", "type": "note", "title": "Links", "text": "See https://keep.google.com/u/0/#NOTE/srvA please",
                 "items": [], "order": 200, "color": "GRAY", "pinned": False, "archived": True, "trashed": False,
                 "labels": [], "created": None, "edited": None, "links": [], "media": []},
                {"id": "c", "type": "note", "title": "", "text": "Buy milk\nand bread", "items": [], "order": 100,
                 "color": "DEFAULT", "pinned": False, "archived": False, "trashed": False, "labels": [],
                 "created": None, "edited": None, "links": [], "media": []},
                {"id": "d", "type": "note", "title": "Old", "text": "gone", "items": [], "order": 50, "color": "DEFAULT",
                 "pinned": False, "archived": False, "trashed": True, "labels": [], "created": None, "edited": None,
                 "links": [], "media": []},
            ]}
        imported = ob.js(PRELUDE + f"""
            const p = app.plugins.plugins['full-keep-mode'];
            const json = {json.dumps(json.dumps(export))};
            const importedBefore = p.settings.importedAt;
            const r = await p.importKeep({{ files: [{{ path: 'keep-export/notes.json', name: 'notes.json', text: async () => json, bytes: async () => new ArrayBuffer(0) }}] }}, FOLDER + '/import');
            await wait(1500);
            const read = n => app.vault.read(app.vault.getAbstractFileByPath(FOLDER + '/import/' + n + '.md'));
            const fm = n => app.metadataCache.getFileCache(app.vault.getAbstractFileByPath(FOLDER + '/import/' + n + '.md'))?.frontmatter ?? {{}};
            return {{ r, packing: await read('Packing'), links: await read('Links'), milk: await read('Buy milk'),
                      packingFm: fm('Packing'), linksFm: fm('Links'),
                      packingMtime: app.vault.getAbstractFileByPath(FOLDER + '/import/Packing.md').stat.mtime,
                      importedAt: await (async () => {{ const t = p.settings.importedAt; p.settings.importedAt = importedBefore; await p.saveSharedSettings(); return t; }})(),
                      milkTitle: p.titleOf(app.vault.getAbstractFileByPath(FOLDER + '/import/Buy milk.md')) }};""")
        r = imported["r"]
        check("all notes come in (Keep's trash is left out)", r["imported"] == 3 and r["skipped"] == 1, r)
        check("…and the import time is kept (for asking for a star a week later)", abs(imported["importedAt"] - time.time() * 1000) < 120000, imported["importedAt"])
        packing = imported["packing"].split("---\n")[-1]
        check("checklists keep their order, sub-items and ticks (two levels, like Keep)",
              packing == "- [ ] Parent\n\t- [ ] Child 1\n\t- [ ] Grandchild\n\t- [x] Child 2\n- [ ] Two lines\n\tsecond line\n- [x] Done\n", repr(packing))
        fm = imported["packingFm"]
        check("the board order, pin, colour, labels and dates come along",
              fm.get("keep_order") == 300 and fm.get("keep_pinned") is True and fm.get("keep_color") == "cerulean"
              and fm.get("tags") == ["Book-club"] and fm.get("keep_created") == "2024-11-10T02:44:02", fm)
        check("…and the note's last edit is Keep's", imported["packingMtime"] == 1731294316000, imported["packingMtime"])
        check("archived and grey notes too", imported["linksFm"].get("keep_archived") is True and imported["linksFm"].get("keep_color") == "gray", imported["linksFm"])
        check("links to other Keep notes become Obsidian links", "See [[Packing]] please" in imported["links"], imported["links"])
        check("an untitled Keep note shows no title", imported["milkTitle"] == "" and "Buy milk" in imported["milk"], imported)

        # Pasting several lines into an item: plain lines become lines of the item, pasted
        # items stay items, whatever indentation they had before.
        def paste_into(name, note, line_no, text):
            open_note(name, note)
            ob.js(PRELUDE + f"""const cm = window.__tcLeaf.view.editor.cm; const l = cm.state.doc.line({line_no});
                cm.focus(); cm.dispatch({{ selection: {{ anchor: l.to }} }}); await wait(150);
                const dt = new DataTransfer(); dt.setData('text/plain', {json.dumps(text)});
                cm.contentDOM.dispatchEvent(new ClipboardEvent('paste', {{ clipboardData: dt, bubbles: true, cancelable: true }})); await wait(500);""")
            return text_now()
        def text_now():
            return text()
        pasted = paste_into("paste one", "- [ ] A\n- [ ] B\n", 1, "line1\n\t\tline2\n- [ ] C\n\t- [ ] D\n  more")
        check("pasting lines into an item keeps them in the checklist, lined up",
              pasted == "- [ ] Aline1\n\tline2\n- [ ] C\n\t- [ ] D\n\t\tmore\n- [ ] B\n", repr(pasted))
        pasted = paste_into("paste two", "- [ ] A\n- [ ] \n- [ ] B\n", 2, "\t- [ ] X\n\t\tsecond\n\t\tthird")
        check("…and a copied item with its lines lands at this level", pasted == "- [ ] A\n- [ ] X\n\tsecond\n\tthird\n- [ ] B\n", repr(pasted))

        # Asking for a GitHub star: once, a week after an import or after two weeks of use.
        star = ob.js(PRELUDE + """const p = app.plugins.plugins['full-keep-mode'];
            const saved = { firstUsed: p.settings.firstUsed, importedAt: p.settings.importedAt, starAsked: p.settings.starAsked };
            const notices = () => [...document.querySelectorAll('.notice')].filter(n => n.textContent.includes('Star on GitHub'));
            notices().forEach(n => n.remove());
            const day = 24 * 60 * 60 * 1000, now = Date.now();
            Object.assign(p.settings, { firstUsed: 0, importedAt: 0, starAsked: false });
            const first = await p.maybeAskForStar(now);
            const started = p.settings.firstUsed === now;
            const early = await p.maybeAskForStar(now + 13 * day);
            const asked = await p.maybeAskForStar(now + 15 * day);
            const shown = notices().length;
            const links = [...(notices()[0]?.querySelectorAll('a') ?? [])].map(l => l.textContent + ' ' + l.getAttribute('href'));
            notices()[0]?.querySelector('.fkm-star-no')?.click(); await wait(500);
            const gone = notices().length === 0;
            const again = await p.maybeAskForStar(now + 30 * day);
            // With an import: a week after it.
            Object.assign(p.settings, { firstUsed: now, importedAt: now + day, starAsked: false });
            const beforeWeek = await p.maybeAskForStar(now + 7 * day);
            const afterWeek = await p.maybeAskForStar(now + 8.5 * day);
            notices().forEach(n => n.remove());
            Object.assign(p.settings, saved); await p.saveSharedSettings();
            return { first, started, early, asked, shown, links, gone, again, beforeWeek, afterWeek };""")
        check("asks once for a GitHub star, after two weeks of use; \"No thanks\" closes it for good",
              {k: star[k] for k in ("first", "started", "early", "asked", "shown", "gone", "again")}
              == {"first": False, "started": True, "early": False, "asked": True, "shown": 1, "gone": True, "again": False}, star)
        check("…with a star and a coffee link", star["links"] == ["Star on GitHub https://github.com/Leuenberger/obsidian-full-Keep-mode", "Buy me a coffee https://ko-fi.com/gabrielleuenberger", "No thanks #"], star["links"])
        check("…or a week after importing from Keep", (star["beforeWeek"], star["afterWeek"]) == (False, True), star)

        print("Settings and opt-out")
        open_note("no sinking", HEAD + "- [ ] A\n- [ ] B", settings={"sinkTicked": False})
        click_checkbox("A")
        check("with \"Move ticked items down\" off, a ticked item stays", body() == "- [x] A\n- [ ] B", body())
        open_note("opted out", "---\nfull-keep-mode: false\n---\n" + HEAD + "- [ ] A\n- [ ] B", settings={"sinkTicked": True})
        time.sleep(1)
        click_checkbox("A")
        grips = ob.js("return window.__tcLeaf.view.editor.cm.contentDOM.querySelectorAll('.fkm-grip').length;")
        check("a note with full-keep-mode: false is left alone", body() == "- [x] A\n- [ ] B" and grips == 0, (body(), grips))

        print("Board")
        has_board = ob.js("return typeof app.plugins.plugins['full-keep-mode'].registerBasesView === 'function';")
        hidden = ob.js("return document.visibilityState === 'hidden';")
        if not has_board:
            print("  skipped: this Obsidian has no Bases (1.10 or later needed)")
        elif hidden:
            # A hidden window (minimised, covered, screen off) doesn't draw, so the board
            # never lays out its cards and mouse drags stall.
            print("  skipped: the Obsidian window is hidden; keep it visible to test the board")
        else:
            open_board({"Card A": 300, "Card B": 200, "Card C": 100})
            bar = ob.js("""const el = window.__fkmBoard.view.containerEl;
                return { inBoard: !!el.querySelector('.fkm-take-note'), boards: el.querySelectorAll('.fkm-board').length,
                         anywhere: document.querySelectorAll('.fkm-take-note').length };""")
            check("the board has a \"Take a note…\" bar", bar["inBoard"], bar)
            check("cards are in board order", card_order() == ["Card A", "Card B", "Card C"], card_order())
            a, c = card_center("Card A"), card_center("Card C")
            ob.mouse("mouseMoved", c["x"], c["y"], 0)
            ob.mouse("mousePressed", c["x"], c["y"])
            for k in range(1, 11):
                ob.mouse("mouseMoved", c["x"] + (a["x"] - c["x"]) * k / 10, c["y"] + (a["y"] - c["y"]) * k / 10)
                time.sleep(0.04)
            ob.mouse("mouseReleased", a["x"], a["y"])
            time.sleep(2)
            check("dragging a card onto another puts it in that card's place", card_order() == ["Card C", "Card A", "Card B"], card_order())
            check("…without opening the note", modal_open() == 0)

            b = card_center("Card B")
            ob.mouse("mouseMoved", b["x"], b["y"], 0)
            ob.mouse("mousePressed", b["x"], b["y"])
            ob.mouse("mouseReleased", b["x"], b["y"])
            time.sleep(1.5)
            check("clicking a card still opens it in the pop-up", modal_open() == 1)
            labels = ob.js("return [...document.querySelectorAll('.fkm-note-modal .view-actions .clickable-icon')].map(b => b.getAttribute('aria-label').split('\\n')[0]);")
            check("the pop-up's top bar has Undo, Redo, Pin and Colour", all(x in labels for x in ("Undo", "Redo", "Pin", "Colour")), labels)
            ob.js(PRELUDE + "document.querySelector('.fkm-note-modal .fkm-pin-button').click(); await wait(800);")
            check("the Pin button pins the note", frontmatter("Card B").get("keep_pinned") is True, frontmatter("Card B"))
            orders = ob.js(PRELUDE + """return app.vault.getMarkdownFiles().filter(f => f.path.startsWith(FOLDER + '/Card')).map(f => [f.basename, app.metadataCache.getFileCache(f)?.frontmatter?.keep_order]);""")
            top_b = dict(orders)["Card B"]
            check("…and moves it to the top of the pinned notes, like Keep", all(top_b > o for n, o in orders if n != "Card B" and o is not None), orders)
            ob.js(PRELUDE + """document.querySelector('.fkm-note-modal .fkm-color-button').click(); await wait(400);
                const item = [...document.querySelectorAll('.menu .menu-item')].find(i => i.textContent.trim() === 'Fog');
                item.click(); await wait(800);""")
            check("the Colour button sets the colour", frontmatter("Card B").get("keep_color") == "blue", frontmatter("Card B"))
            colored = ob.js(PRELUDE + "await wait(500); return [...document.querySelectorAll('.fkm-note-modal')].pop()?.classList.contains('fkm-color-blue');")
            check("…and the open pop-up takes the colour, like in Keep", colored, colored)
            press_escape()
            time.sleep(1)
            check("a pinned note moves to the top of the board", card_order()[0] == "Card B", card_order())

            # Cards like Keep's: unticked items, "+ N ticked items"; ticking on a card works.
            ob.js(PRELUDE + """const f = app.vault.getAbstractFileByPath(FOLDER + '/Card A.md');
                await app.vault.modify(f, '---\\nkeep_order: 300\\n---\\n- [ ] Milk\\n- [x] Eggs\\n- [ ] Bread\\n'); await wait(1500);""")
            card = ob.js("""const c = [...document.querySelectorAll('.fkm-card')].find(c => c.dataset.path.endsWith('/Card A.md'));
                return { items: [...c.querySelectorAll('.fkm-card-item-text')].map(e => e.textContent), ticked: c.querySelector('.fkm-card-ticked')?.textContent };""")
            check("a card shows the unticked items and \"+ 1 ticked item\"", card == {"items": ["Milk", "Bread"], "ticked": "+ 1 ticked item"}, card)
            ob.js(PRELUDE + """const c = [...document.querySelectorAll('.fkm-card')].find(c => c.dataset.path.endsWith('/Card A.md'));
                c.querySelector('.fkm-card-check').click(); await wait(1500);""")
            ticked = ob.js(PRELUDE + "return await app.vault.read(app.vault.getAbstractFileByPath(FOLDER + '/Card A.md'));")
            check("ticking on a card ticks the item and moves it down, like in the note", ticked.endswith("- [ ] Bread\n- [x] Milk\n- [x] Eggs\n"), repr(ticked))
            check("…and doesn't open the note", modal_open() == 0)

            # Keep's exact colours, and the open note's top bar takes the colour too.
            colours = ob.js(PRELUDE + """const card = [...window.__fkmBoard.view.containerEl.querySelectorAll('.fkm-card')].find(c => c.dataset.path.endsWith('/Card B.md'));
                document.body.classList.contains('theme-light');
                return { card: getComputedStyle(card).backgroundColor, cls: card.className, light: document.body.classList.contains('theme-light') };""")
            check("cards have Keep's colours (Fog for blue)", not colours["light"] or colours["card"] == "rgb(203, 240, 248)", colours)

            # A pop-up stays with its board's tab while another tab is in front.
            ob.js(PRELUDE + """const f = app.vault.getAbstractFileByPath(FOLDER + '/Card A.md');
                window.__otherTab = app.workspace.getLeaf('tab'); await window.__otherTab.openFile(app.vault.getAbstractFileByPath(FOLDER + '/Card C.md'));
                app.workspace.setActiveLeaf(window.__fkmBoard, { focus: true }); await wait(600);
                [...window.__fkmBoard.view.containerEl.querySelectorAll('.fkm-card')].find(c => c.dataset.path.endsWith('/Card B.md')).querySelector('.fkm-card-title').click();
                await wait(1200);""")
            header = ob.js("""const m = [...document.querySelectorAll('.fkm-note-modal')].pop(); const h = m?.querySelector('.view-header'); return h ? getComputedStyle(h).backgroundColor : null;""")
            check("the open note's top bar has the note's colour", header == "rgb(203, 240, 248)" or not colours["light"], header)
            def tab_click(js):
                r = ob.js(js)
                ob.mouse("mouseMoved", r["x"], r["y"], 0); ob.mouse("mousePressed", r["x"], r["y"]); ob.mouse("mouseReleased", r["x"], r["y"], 0)
                time.sleep(1)
            def popup_state():
                return ob.js("""const m = [...document.querySelectorAll('.fkm-note-modal')].pop(); return m ? (m.closest('.modal-container').classList.contains('fkm-hidden') ? 'hidden' : 'shown') : 'closed';""")
            tab_click("const r = window.__otherTab.tabHeaderEl.getBoundingClientRect(); return { x: r.left + 30, y: r.top + r.height / 2 };")
            away = popup_state()
            tab_click("const r = window.__fkmBoard.tabHeaderEl.getBoundingClientRect(); return { x: r.left + 30, y: r.top + r.height / 2 };")
            back = popup_state()
            check("another tab can be opened while a note is popped up; back on the board it's still there", (away, back) == ("hidden", "shown"), (away, back))
            press_escape()
            ob.js("window.__otherTab.detach();")
            # A reminder's "Open" shows the note over its board.
            opened = ob.js(PRELUDE + """const p = app.plugins.plugins['full-keep-mode'];
                const note = app.workspace.getLeaf('tab'); await note.openFile(app.vault.getAbstractFileByPath(FOLDER + '/Card C.md'));
                app.workspace.setActiveLeaf(note, { focus: true }); await wait(400);
                const f = app.vault.getAbstractFileByPath(FOLDER + '/Card A.md');
                p.showReminder(f, moment(), false); await wait(200);
                [...document.querySelectorAll('.notice a')].filter(a => a.textContent === 'Open').pop().click(); await wait(1800);
                const active = app.workspace.getMostRecentLeaf()?.view?.getViewType();
                document.querySelectorAll('.notice').forEach(n => { if (n.textContent.includes('Card A')) n.remove(); });
                note.detach();
                return { active, popup: !!document.querySelector('.fkm-note-modal') };""")
            check("a reminder's \"Open\" shows the note popped up over the board", opened == {"active": "bases", "popup": True}, opened)
            press_escape()

            # A link in a pop-up opens the linked note in the pop-up (not in the board's tab
            # behind it); back returns to the first note, then to the board.
            ob.js(PRELUDE + """const f = app.vault.getAbstractFileByPath(FOLDER + '/Card B.md');
                await app.vault.modify(f, (await app.vault.read(f)) + '\\nSee [[Card C]] too\\n'); await wait(800);
                app.workspace.setActiveLeaf(window.__fkmBoard, { focus: true }); await wait(300);
                // The moment the pop-up appears, its note is already there (it never slides in empty).
                window.__appeared = null;
                const watch = new MutationObserver(() => { const m = document.querySelector('.fkm-note-modal');
                    if (m && window.__appeared === null) window.__appeared = m.querySelectorAll('.cm-line').length; });
                watch.observe(document.body, { childList: true, subtree: true }); window.__watch = watch;
                [...window.__fkmBoard.view.containerEl.querySelectorAll('.fkm-card')].find(c => c.dataset.path.endsWith('/Card B.md')).querySelector('.fkm-card-title').click();
                await wait(1500); watch.disconnect();""")
            appeared = ob.js("return window.__appeared;")
            check("a note's pop-up appears with the note already in it (never empty)", isinstance(appeared, int) and appeared > 0, appeared)
            link = ob.js("""const m = [...document.querySelectorAll('.fkm-note-modal')].pop();
                const el = [...m.querySelectorAll('.cm-hmd-internal-link, .internal-link')].find(e => e.textContent.includes('Card C'));
                if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 };""")
            if link:
                ob.mouse("mouseMoved", link["x"], link["y"], 0)
                ob.mouse("mousePressed", link["x"], link["y"])
                ob.mouse("mouseReleased", link["x"], link["y"], 0)
                time.sleep(1.5)
            where = lambda: ob.js("""const m = [...(app.plugins.plugins['full-keep-mode'].openNotes ?? [])].pop();
                return { popup: m ? m.leaf.view.file.basename : null, board: window.__fkmBoard.view.getViewType() };""")
            followed = where()
            check("a link in a pop-up opens the linked note in the pop-up; the board stays", link is not None and followed == {"popup": "Card C", "board": "bases"}, (link, followed))
            def escape_once():
                ob.call("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
                ob.call("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
                time.sleep(1)
            escape_once()
            back = where()
            escape_once()
            closed = where()
            check("…back returns to the note with the link, then to the board", (back, closed) == ({"popup": "Card B", "board": "bases"}, {"popup": None, "board": "bases"}), (back, closed))
            ob.js(PRELUDE + "app.workspace.revealLeaf(window.__fkmBoard); app.workspace.setActiveLeaf(window.__fkmBoard, { focus: true }); await wait(800);")

            # "Take a note…": like Keep, an empty "Title" and "Note", the cursor ready in the
            # note; a title can have any characters; untouched, the note is thrown away.
            # (The new note is the one in the open "new note" pop-up - never "the newest file",
            # which could be one of the user's.)
            new_note = """const m = [...(app.plugins.plugins['full-keep-mode'].openNotes ?? [])].find(m => m.isNew);"""
            ob.js(PRELUDE + "window.__fkmBoard.view.containerEl.querySelector('.fkm-take-note').click(); await wait(1500);")
            fresh = ob.js(PRELUDE + new_note + """ if (!m) return null; await wait(300);
                const el = m.modalEl; const cm = m.leaf.view.editor.cm; const title = el.querySelector('.fkm-title');
                const obsidianTitle = el.querySelector('.inline-title:not(.fkm-title)');
                return { path: m.file.path, title: title?.textContent, placeholder: title && getComputedStyle(title, '::before').content,
                    obsidianTitle: obsidianTitle ? getComputedStyle(obsidianTitle).display : 'none',
                    note: el.querySelector('.fkm-placeholder')?.textContent ?? null, focused: cm.hasFocus };""")
            check("\"Take a note…\" opens a new note in the pop-up: empty \"Title\" and \"Note\", the cursor ready",
                  fresh is not None and fresh["title"] == "" and fresh["placeholder"] == '"Title"' and fresh["obsidianTitle"] == "none"
                  and fresh["note"] == "Note" and fresh["focused"] is True, fresh)
            press_escape()
            gone = ob.js(f"return !app.vault.getAbstractFileByPath({json.dumps(fresh and fresh['path'])});")
            check("…which is thrown away when closed untouched", gone, fresh)
            ob.js(PRELUDE + "window.__fkmBoard.view.containerEl.querySelector('.fkm-take-note').click(); await wait(1500);")
            box = ob.js(PRELUDE + new_note + """ const r = m.modalEl.querySelector('.fkm-title').getBoundingClientRect();
                return { x: r.left + 20, y: r.top + r.height / 2, path: m.file.path };""")
            ob.mouse("mouseMoved", box["x"], box["y"], 0)
            ob.mouse("mousePressed", box["x"], box["y"])
            ob.mouse("mouseReleased", box["x"], box["y"], 0)
            time.sleep(0.3)
            ob.call("Input.insertText", text="Sept/Oct: 50%?")
            time.sleep(0.3)
            ob.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, text="\r", unmodifiedText="\r")
            ob.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
            time.sleep(1.2)
            ob.call("Input.insertText", text="Milk")
            time.sleep(1)
            named = ob.js(PRELUDE + new_note + """ await wait(300); return { path: m.file.path, title: app.metadataCache.getFileCache(m.file)?.frontmatter?.keep_title,
                text: m.leaf.view.editor.getValue() };""")
            check("…a title with any characters (it's kept as written; the file name leaves out what it can't have)",
                  named["title"] == "Sept/Oct: 50%?" and named["path"].endswith("SeptOct 50%.md"), named)
            check("…Enter in the title goes on to the note's text", named["text"].endswith("Milk"), named)
            press_escape()
            kept = ob.js(f"const f = app.vault.getAbstractFileByPath({json.dumps(named['path'])}); return f ? await app.vault.read(f) : null;")
            check("…and a note with text is kept", kept is not None and kept.endswith("Milk"), kept)
            ob.js(f"const f = app.vault.getAbstractFileByPath({json.dumps(named['path'])}); if (f) await app.vault.trash(f, true);")

            # Search bar, labels and "New list".
            order = ob.js("""const el = window.__fkmBoard.view.containerEl;
                return [...el.querySelectorAll('.fkm-board .fkm-search, .fkm-board .fkm-take-note')].map(e => e.className);""")
            check("an always-visible search bar above \"Take a note…\"", order == ["fkm-search", "fkm-take-note"], order)
            ob.js(PRELUDE + """const f = app.vault.getAbstractFileByPath(FOLDER + '/Card C.md');
                await app.vault.modify(f, (await app.vault.read(f)) + 'A zebra crossing\\n'); await wait(800);
                const input = window.__fkmBoard.view.containerEl.querySelector('.fkm-search input');
                input.value = 'zebra'; input.dispatchEvent(new Event('input')); await wait(500);""")
            for _ in range(10):  # the search reads all notes; give it time on a big vault
                if card_order() == ["Card C"]:
                    break
                time.sleep(0.5)
            check("searching finds notes by their text", card_order() == ["Card C"], (card_order(), ob.js("""const p = app.plugins.plugins['full-keep-mode']; return { text: p.boardFilter.text, n: p.boardFilter.matches?.size, input: window.__fkmBoard.view.containerEl.querySelector('.fkm-search input')?.value, inputs: document.querySelectorAll('.fkm-search input').length, boards: p.boards.size ?? p.boards.length, modals: document.querySelectorAll('.fkm-note-modal').length, leaves: app.workspace.getLeavesOfType('bases').map(l => l.view.file?.path) };""")))
            ob.js(PRELUDE + "window.__fkmBoard.view.containerEl.querySelector('.fkm-search-clear').click(); await wait(1500);")
            check("…and clearing the search shows all again", len(card_order()) == 3, card_order())
            ob.js(PRELUDE + """const p = app.plugins.plugins['full-keep-mode'];
                await p.setLabel(app.vault.getAbstractFileByPath(FOLDER + '/Card A.md'), 'Fruit', true); await wait(800);
                app.workspace.setActiveLeaf(window.__fkmBoard, { focus: true });
                await p.showOnBoard('label:Fruit'); await wait(1500);""")
            chip = ob.js("return window.__fkmBoard.view.containerEl.querySelector('.fkm-search-chip')?.innerText ?? null;")
            check("a label shows only its notes, named in the search bar", card_order() == ["Card A"] and chip == "Fruit", (card_order(), chip))
            ob.js(PRELUDE + "window.__fkmBoard.view.containerEl.querySelector('.fkm-take-note-list').click(); await wait(1500);")
            new_text = ob.js("""const f = app.vault.getMarkdownFiles().sort((a, b) => b.stat.ctime - a.stat.ctime)[0];
                return await app.vault.read(f);""")
            boxes = ob.js("return document.querySelectorAll('.fkm-new-note-modal input.task-list-item-checkbox').length;")
            check("\"New list\" starts a checklist, with the label shown", new_text == '---\ntags:\n  - "Fruit"\n---\n- [ ] ' and boxes == 1, (new_text, boxes))
            press_escape()
            ob.js(PRELUDE + "await app.plugins.plugins['full-keep-mode'].showOnBoard('notes'); await wait(1200);")
            check("\"Notes\" shows all notes again", len(card_order()) == 3, card_order())

            # Keep's "Edit labels" (side menu): rename a label in all its notes, or delete it.
            # Names no real note has: renaming changes every note in the vault with the label.
            ob.js(PRELUDE + """const p = app.plugins.plugins['full-keep-mode'];
                for (const [name, label] of [['Card A', 'fkm-test-fruit'], ['Card B', 'fkm-test-fruit'], ['Card C', 'fkm-test-veg']])
                    await p.setLabel(app.vault.getAbstractFileByPath(FOLDER + '/' + name + '.md'), label, true);
                await wait(1200);
                app.workspace.setActiveLeaf(window.__fkmBoard, { focus: true });
                await p.showOnBoard('label:fkm-test-fruit'); await wait(800);
                await p.openLabelsView(true); await wait(800);
                document.querySelector('.fkm-labels-edit').click(); await wait(600);""")
            def label_row_js(name, action):
                return PRELUDE + f"""const row = [...document.querySelectorAll('.fkm-edit-labels-row')].find(r => r.dataset.label === {json.dumps(name)});
                    const input = row.querySelector('input'); {action}"""
            def rename_label(name, to):
                return ob.js(label_row_js(name, f"""input.focus(); input.value = {json.dumps(to)};
                    input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true, cancelable: true }})); await wait(1800);
                    return [...document.querySelectorAll('.fkm-edit-labels-error')].map(e => e.textContent).filter(Boolean);"""))
            errors = rename_label("fkm-test-fruit", "fkm-test-veg")
            check("Edit labels: renaming to a label that exists says so", errors == ["Label already exists"], errors)
            rename_label("fkm-test-fruit", "fkm test fruits")
            tags = [frontmatter(n).get("tags") for n in ("Card A", "Card B", "Card C")]
            check("Edit labels: renaming changes the label in all its notes", tags == [["Fruit", "fkm-test-fruits"], ["fkm-test-fruits"], ["fkm-test-veg"]], tags)
            time.sleep(0.5)
            chip = ob.js("return window.__fkmBoard.view.containerEl.querySelector('.fkm-search-chip')?.innerText ?? null;")
            check("…and the board showing it follows the new name", chip == "fkm-test-fruits" and sorted(card_order()) == ["Card A", "Card B"], (chip, card_order()))
            ob.js(label_row_js("fkm-test-fruits", """row.querySelector('.fkm-edit-labels-delete').click(); await wait(400);
                const text = document.querySelector('.fkm-confirm-modal p').textContent; window.__confirmText = text;
                [...document.querySelectorAll('.fkm-confirm-modal button')].find(b => b.textContent === 'Delete').click(); await wait(1800);"""))
            confirm_text = ob.js("return window.__confirmText;")
            check("Edit labels: deleting asks first, saying the notes stay", "2 notes" in confirm_text and "won't be deleted" in confirm_text, confirm_text)
            tags = [frontmatter(n).get("tags") for n in ("Card A", "Card B", "Card C")]
            exist = ob.js(PRELUDE + "return ['Card A', 'Card B', 'Card C'].every(n => app.vault.getAbstractFileByPath(FOLDER + '/' + n + '.md'));")
            check("…then removes the label from its notes, which stay", tags == [["Fruit"], None, ["fkm-test-veg"]] and exist, (tags, exist))
            rows = ob.js("return [...document.querySelectorAll('.fkm-edit-labels-row input')].map(i => i.value).filter(v => v.startsWith('fkm-test'));")
            check("…and from the list", rows == ["fkm-test-veg"], rows)
            ob.js(PRELUDE + "[...document.querySelectorAll('.fkm-edit-labels-modal button')].find(b => b.textContent === 'Done').click(); await wait(300);")
            time.sleep(0.5)
            check("…and the board shows all notes again", len(card_order()) == 3, card_order())
            ob.js("window.__fkmBoard.detach();")

        print("Archive and reminders")
        # An imported archived note: Keep Importer writes the tag on a line of its own.
        open_note("archive", "Some text\n\n #archived\n\nmore")
        labels = ob.js("return [...window.__tcLeaf.view.containerEl.querySelectorAll('.view-actions .clickable-icon')].map(b => b.getAttribute('aria-label'));")
        order = [l for l in labels if l in ("Undo", "Redo", "Pin", "Unpin", "Remind me", "Colour", "Archive", "Unarchive")]
        check("top bar: Undo, Redo, Pin, Remind me, Colour, Archive (the tag counts as archived)",
              order == ["Undo", "Redo", "Pin", "Remind me", "Colour", "Unarchive"], labels)
        click_archive = PRELUDE + "window.__tcLeaf.view.containerEl.querySelector('.fkm-archive-button').click(); await wait(700);"
        ob.js(click_archive)
        check("unarchiving removes the #archived line", text() == "Some text\n\n\nmore", repr(text()))
        ob.js(click_archive)
        check("archiving sets keep_archived", frontmatter("archive").get("keep_archived") is True, frontmatter("archive"))
        undo_link = ob.js(PRELUDE + """
            const a = [...document.querySelectorAll('.notice a')].filter(a => a.textContent === 'Undo').pop();
            if (!a) return false; a.click(); await wait(700); return true;""")
        check("…and \"Undo\" in the notice unarchives it", undo_link and "keep_archived" not in frontmatter("archive"), frontmatter("archive"))

        ob.js(PRELUDE + "window.__tcLeaf.view.containerEl.querySelector('.fkm-reminder-button').click(); await wait(400);")
        picks = ob.js("return [...document.querySelectorAll('.fkm-reminder-modal .fkm-reminder-pick span:first-child')].map(s => s.textContent);")
        check("the bell opens Keep's quick picks", "Tomorrow" in picks and "Next week" in picks, picks)
        ob.js(PRELUDE + """
            [...document.querySelectorAll('.fkm-reminder-modal .fkm-reminder-pick')].find(b => b.textContent.startsWith('Tomorrow')).click();
            await wait(700);""")
        tomorrow = ob.js("return moment().add(1, 'day').format('YYYY-MM-DD') + 'T08:00';")
        check("\"Tomorrow\" sets the reminder to 8:00 tomorrow", frontmatter("archive").get("keep_reminder") == tomorrow, frontmatter("archive"))
        check("…and the bell shows it", ob.js("return window.__tcLeaf.view.containerEl.querySelector('.fkm-reminder-button').classList.contains('has-reminder');"))

        fired = ob.js(PRELUDE + """
            const plugin = app.plugins.plugins["full-keep-mode"];
            const shown = [];
            const RealNotification = window.Notification;
            window.Notification = class { constructor(title, o) { shown.push(title + ': ' + o.body); } static permission = 'granted'; };
            try {
                const f = app.vault.getAbstractFileByPath(FOLDER + '/archive.md');
                await app.fileManager.processFrontMatter(f, fm => { fm.keep_reminder = moment().subtract(1, 'minute').format('YYYY-MM-DDTHH:mm'); });
                await wait(500);
                // The plugin's own check (every 20 s) may have fired it meanwhile: start clean.
                shown.length = 0;
                document.querySelectorAll('.notice').forEach(n => { if (n.textContent.includes('archive')) n.remove(); });
                delete plugin.settings.firedReminders[f.path];
                const notices = () => [...document.querySelectorAll('.notice')].filter(n => n.textContent.includes('Reminder') && n.textContent.includes('archive')).length;
                const before = notices();
                await plugin.checkReminders();
                const first = notices() - before;
                await plugin.checkReminders();
                const second = notices() - before;
                document.querySelectorAll('.notice').forEach(n => { if (n.textContent.includes('archive')) n.remove(); });
                await plugin.setReminder(f, null);
                return { first, second, shown };
            } finally { window.Notification = RealNotification; }""")
        check("a due reminder pops up once, with a system notification", fired["first"] == 1 and fired["second"] == 1 and fired["shown"] == ["Reminder: archive"], fired)

        print("Command and header buttons")
        open_note("command", HEAD + "- [x] A\n- [ ] B\n- [x] C\n- [ ] D")
        ob.js(PRELUDE + "app.commands.executeCommandById('full-keep-mode:sort-ticked-items'); await wait(500);")
        check("\"Move ticked items down in this note\" sorts an existing list", body() == "- [ ] B\n- [ ] D\n- [x] A\n- [x] C", body())
        labels = ob.js("return [...window.__tcLeaf.view.containerEl.querySelectorAll('.view-actions .clickable-icon')].map(b => b.getAttribute('aria-label'));")
        check("Undo and Redo buttons in the note's top bar", "Undo" in labels and "Redo" in labels, labels)
        ob.js(PRELUDE + "window.__tcLeaf.view.containerEl.querySelector('.fkm-undo-button').click(); await wait(400);")
        check("the Undo button undoes", body() == "- [x] A\n- [ ] B\n- [x] C\n- [ ] D", body())

    finally:
        ob.js(PRELUDE + """
        const plugin = app.plugins.plugins["full-keep-mode"];
        if (window.__tcSaved) { Object.assign(plugin.settings, JSON.parse(window.__tcSaved)); delete window.__tcSaved; plugin.refreshEditors(); }
        for (const l of app.workspace.getLeavesOfType("markdown")) if (l.view.file?.path?.startsWith(FOLDER + "/")) l.detach();
        const folder = app.vault.getAbstractFileByPath(FOLDER);
        // Trash the notes one by one first: Bases misses notes trashed along with their folder
        // and would keep showing them on the board.
        if (folder) {
            for (const f of [...folder.children]) await app.vault.trash(f, true);
            await app.vault.trash(folder, true);
        }
        document.querySelectorAll(".modal-container[data-tc-hidden]").forEach(m => { m.style.visibility = ""; delete m.dataset.tcHidden; });
        """)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
