#!/usr/bin/env python3
"""
Finds the plugin's CSS that has no effect because something else wins: for every rule
in styles.css and the elements it matches (a note, the board, the pop-up; with --phone
in the phone layout), the browser's own cascade says which declaration wins each
property. Reports every property where the plugin's declaration loses to Obsidian's
or to an inline style, with a different value.

    python tests/css_audit.py [--phone]
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import live_test as lt  # noqa: E402

ob = lt.ob
PHONE = "--phone" in sys.argv
CSS = (Path(__file__).resolve().parent.parent / "styles.css").read_text(encoding="utf-8")
F = "Full Keep Mode css audit"
PRE = "const wait = ms => new Promise(r => setTimeout(r, ms)); const F = " + json.dumps(F) + ";\n"
NOTE = ("---\nkeep_color: blue\n---\n- [ ] Top one with a long text that wraps onto a second line when the window is narrow\n"
        "\t- [ ] Sub one\n\t\tsecond line of sub\n\t- [x] Sub done\n- [ ] \n- [ ] Top two\n- [x] Done one\n\tmore of done\n")
BOARD = f'filters:\n  and:\n    - \'file.ext == "md"\'\n    - file.inFolder("{F}")\nviews:\n  - type: keep-board\n    name: Board\n'

selectors = []
for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
    for part in m.group(1).split(","):
        part = " ".join(part.split())
        if part and "::" not in part and ":hover" not in part and part not in selectors:
            selectors.append(part)


def setup():
    ob.js(PRE + f"""if (!app.vault.getAbstractFileByPath(F)) await app.vault.createFolder(F);
        for (const [n, t] of [["Check.md", {json.dumps(NOTE)}], ["Board.base", {json.dumps(BOARD)}]]) {{
            const f = app.vault.getAbstractFileByPath(F + "/" + n); if (f) await app.vault.modify(f, t); else await app.vault.create(F + "/" + n, t); }}
        await wait(800); return 1;""")


def same(value):
    """A value as compared: without !important, any zero length as 0."""
    value = value.replace("!important", "").strip()
    return "0" if re.fullmatch(r"-?0(\.0+)?(px|em|rem|%)?", value) else value


def audit(name):
    ob.call("DOM.enable")
    ob.call("CSS.enable")
    root = ob.call("DOM.getDocument", depth=-1)["root"]["nodeId"]
    ours = None
    found = {}
    for sel in selectors:
        try:
            ids = ob.call("DOM.querySelectorAll", nodeId=root, selector=sel)["nodeIds"][:3]
        except RuntimeError:
            continue
        for nid in ids:
            try:
                m = ob.call("CSS.getMatchedStylesForNode", nodeId=nid)
            except RuntimeError:
                continue
            rules = m.get("matchedCSSRules", [])
            if ours is None:
                for r in rules:
                    if "fkm" in r["rule"]["selectorList"]["text"] and r["rule"].get("origin") == "regular":
                        text = ob.call("CSS.getStyleSheetText", styleSheetId=r["rule"]["styleSheetId"])["text"]
                        if text.startswith("/* Full Keep Mode */"):
                            ours = r["rule"]["styleSheetId"]
                            break
            if ours is None:
                continue
            winners = {}  # property -> (important, origin, selector, value)
            for r in rules:
                rule = r["rule"]
                for p in rule["style"]["cssProperties"]:
                    if "value" not in p or p.get("disabled") or p.get("parsedOk") is False:
                        continue
                    important = bool(p.get("important"))
                    prev = winners.get(p["name"])
                    if prev is None or important or not prev[0]:
                        winners[p["name"]] = (important, rule.get("styleSheetId"), rule["selectorList"]["text"], p["value"])
            for p in (m.get("inlineStyle") or {}).get("cssProperties", []):
                if "value" in p and p.get("value") and not p.get("disabled"):
                    prev = winners.get(p["name"])
                    if prev is None or not prev[0] or p.get("important"):
                        winners[p["name"]] = (bool(p.get("important")), "inline", "(inline style)", p["value"])
            for r in rules:
                rule = r["rule"]
                if rule.get("styleSheetId") != ours:
                    continue
                for p in rule["style"]["cssProperties"]:
                    if "value" not in p or p["name"].startswith("--"):
                        continue
                    w = winners.get(p["name"])
                    if w and w[1] != ours and same(w[3]) != same(p["value"]):
                        key = (rule["selectorList"]["text"][:90], p["name"])
                        found.setdefault(key, f"{p['value']}  loses to  {w[2][:70]} = {w[3]}")
    print(f"{name}: {len(found)} of the plugin's declarations have no effect")
    for (sel, prop), why in sorted(found.items()):
        print(f"   {sel}  |  {prop}: {why}")
    return found


def main():
    # A covered Obsidian window slows its timers down and stops drawing: keep it going.
    ob.js("""const wc = require("@electron/remote").getCurrentWebContents(); wc.setBackgroundThrottling(false);
        wc.invalidate(); try { await wc.capturePage(); } catch {} return 1;""")
    if PHONE:
        import phone_test as pt
        pt.phone_layout(True)
    setup()
    try:
        ob.js(PRE + """document.querySelectorAll(".modal-container").forEach(m => m.remove());
            const leaf = app.workspace.getLeaf(app.isMobile ? false : "tab"); await leaf.openFile(app.vault.getAbstractFileByPath(F + "/Check.md"), { state: { mode: "source", source: false } });
            app.workspace.setActiveLeaf(leaf, { focus: true }); window.__auditLeaf = leaf; await wait(1500);
            const cm = leaf.view.editor.cm; cm.focus(); cm.dispatch({ selection: { anchor: cm.state.doc.toString().indexOf("Sub one") } }); await wait(400); return 1;""")
        audit("note")
        ob.js(PRE + """const leaf = window.__auditLeaf; await leaf.openFile(app.vault.getAbstractFileByPath(F + "/Board.base")); await wait(1800); return 1;""")
        audit("board")
        ob.js(PRE + """window.__auditLeaf.view.containerEl.querySelector('.fkm-card .fkm-card-title, .fkm-card').click(); await wait(1800);
            const cm = app.plugins.plugins["full-keep-mode"].popupLeaf.view.editor.cm; cm.focus(); await wait(300); return 1;""")
        audit("pop-up")
    finally:
        ob.js(PRE + """document.querySelectorAll(".modal-container").forEach(m => m.remove()); window.__auditLeaf?.detach();
            const f = app.vault.getAbstractFileByPath(F); if (f) await app.vault.delete(f, true); return 1;""")
        if PHONE:
            pt.phone_layout(False)
        ob.js('require("@electron/remote").getCurrentWebContents().setBackgroundThrottling(true); return 1;')


if __name__ == "__main__":
    main()
