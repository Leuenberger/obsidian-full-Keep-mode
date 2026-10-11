#!/usr/bin/env python3
"""
Live tests for Tidy Checklists, run against a real, running Obsidian.

Start Obsidian with its debugging port open (close it first):
    Windows:  "%LOCALAPPDATA%\\Programs\\Obsidian\\Obsidian.exe" --remote-debugging-port=9222
    macOS:    open -a Obsidian --args --remote-debugging-port=9222
Then, with the plugin enabled in the open vault:
    pip install websocket-client
    python tests/live_test.py

The tests only use temporary notes (created in a "Tidy Checklists tests" folder
and moved to the trash afterwards). Open pop-ups are hidden while they run.
Mouse drags use real input events, so keep the Obsidian window visible.
"""
import itertools
import json
import sys
import time
import urllib.request

import websocket

PORT = 9222
FOLDER = "Tidy Checklists tests"


class Obsidian:
    def __init__(self):
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list"))
        page = next(p for p in pages if p["type"] == "page" and p["url"].startswith("app://obsidian.md"))
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
    const plugin = app.plugins.plugins["tidy-checklists"];
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
    g = ob.js(line_el(label) + """
    const g = el.querySelector(".tc-grip").getBoundingClientRect();
    return { x: g.left + g.width / 2, y: g.top + g.height / 2 };
    """)
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


def undo():
    ob.js(PRELUDE + "window.__tcLeaf.view.editor.undo(); await wait(400);")


HEAD = "Test list:\n\n\n"

# ----- the tests -----------------------------------------------------------------------------

def main():

    try:
        ob.js("""document.querySelectorAll(".modal-container").forEach(m => { m.dataset.tcHidden = "1"; m.style.visibility = "hidden"; });""")
        info = ob.js("""const p = app.plugins.plugins["tidy-checklists"]; return { loaded: !!p, version: app.plugins.manifests["tidy-checklists"]?.version };""")
        print(f"Tidy Checklists {info['version']}")
        check("plugin is loaded", info["loaded"])

        print("Ticking")
        start = "- [ ] A\n- [ ] B\n\t- [ ] B1\n- [ ] C"
        open_note("ticking", HEAD + start)
        click_checkbox("A")
        check("ticked item moves below the others", body() == "- [ ] B\n→- [ ] B1\n- [ ] C\n- [x] A", body())
        section = ob.js("return [...window.__tcLeaf.view.editor.cm.contentDOM.querySelectorAll('.tc-ticked-label')].map(e => e.textContent);")
        check("divider shows \"1 ticked item\"", section == ["1 ticked item"], section)
        undo()
        check("one undo restores the list exactly", body() == start.replace("\t", "→"), body())
        click_checkbox("B")
        check("ticking a parent ticks its sub-items and moves them along", body() == "- [ ] A\n- [ ] C\n- [x] B\n→- [x] B1", body())

        print("Ghost parents")
        open_note("ghosts", HEAD + "- [ ] P\n\t- [ ] P1\n\t- [ ] P2\n- [ ] Q")
        click_checkbox("P2")
        ghost = ob.js("""const s = window.__tcLeaf.view.editor.cm.contentDOM.querySelector('.tc-ticked-section');
                         return s ? s.innerText.replace(/\\n+/g, ' | ') : null;""")
        check("ticked sub-item shows under a ghost parent", ghost == "1 ticked item | P | P2", ghost)
        check("…while the note keeps it under its parent", body() == "- [ ] P\n→- [ ] P1\n→- [x] P2\n- [ ] Q", body())
        ob.js(PRELUDE + """const box = window.__tcLeaf.view.editor.cm.contentDOM.querySelector('.tc-ghost-child input'); box.click(); await wait(700);""")
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

        print("Settings and opt-out")
        open_note("no sinking", HEAD + "- [ ] A\n- [ ] B", settings={"sinkTicked": False})
        click_checkbox("A")
        check("with \"Move ticked items down\" off, a ticked item stays", body() == "- [x] A\n- [ ] B", body())
        open_note("opted out", "---\ntidy-checklists: false\n---\n" + HEAD + "- [ ] A\n- [ ] B", settings={"sinkTicked": True})
        time.sleep(1)
        click_checkbox("A")
        grips = ob.js("return window.__tcLeaf.view.editor.cm.contentDOM.querySelectorAll('.tc-grip').length;")
        check("a note with tidy-checklists: false is left alone", body() == "- [x] A\n- [ ] B" and grips == 0, (body(), grips))

        print("Command and header buttons")
        open_note("command", HEAD + "- [x] A\n- [ ] B\n- [x] C\n- [ ] D")
        ob.js(PRELUDE + "app.commands.executeCommandById('tidy-checklists:sort-ticked-items'); await wait(500);")
        check("\"Move ticked items down in this note\" sorts an existing list", body() == "- [ ] B\n- [ ] D\n- [x] A\n- [x] C", body())
        labels = ob.js("return [...window.__tcLeaf.view.containerEl.querySelectorAll('.view-actions .clickable-icon')].map(b => b.getAttribute('aria-label'));")
        check("Undo and Redo buttons in the note's top bar", "Undo" in labels and "Redo" in labels, labels)
        ob.js(PRELUDE + "window.__tcLeaf.view.containerEl.querySelector('.tc-undo-button').click(); await wait(400);")
        check("the Undo button undoes", body() == "- [x] A\n- [ ] B\n- [x] C\n- [ ] D", body())

    finally:
        ob.js(PRELUDE + """
        const plugin = app.plugins.plugins["tidy-checklists"];
        if (window.__tcSaved) { Object.assign(plugin.settings, JSON.parse(window.__tcSaved)); delete window.__tcSaved; plugin.refreshEditors(); }
        for (const l of app.workspace.getLeavesOfType("markdown")) if (l.view.file?.path?.startsWith(FOLDER + "/")) l.detach();
        const folder = app.vault.getAbstractFileByPath(FOLDER);
        if (folder) await app.vault.trash(folder, true);
        document.querySelectorAll(".modal-container[data-tc-hidden]").forEach(m => { m.style.visibility = ""; delete m.dataset.tcHidden; });
        """)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
