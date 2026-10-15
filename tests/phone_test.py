#!/usr/bin/env python3
"""
Phone checks for Full Keep Mode, in a running Obsidian (debugging port 9222, see
live_test.py) switched to its phone layout: Keep's measures, the cursor, "Select All",
taps on the checkbox and next to it, and swiping items sideways.

    python tests/phone_test.py      (switches Obsidian to the phone layout and back)
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import live_test as lt  # noqa: E402  (its connection and check())

ob = lt.ob
F = "Full Keep Mode phone tests"
TEXT = "---\nkeep_color: blue\n---\n- [ ] Top one\n\t- [ ] Sub one\n\t\tsecond line\n\t- [ ] Sub two\n- [ ] Top two\n"
PRE = "const wait = ms => new Promise(r => setTimeout(r, ms));\n"
CM = PRE + "const cm = app.plugins.plugins['full-keep-mode'].popupLeaf.view.editor.cm;\n"


def js(code):
    return ob.js(code)


def phone_layout(on):
    ob.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=3, mobile=True)
    if js("return document.body.hasClass('emulate-mobile');") != on:
        js(f"setTimeout(() => app.emulateMobile({json.dumps(on)}), 100); return 1;")
    elif on:
        ob.call("Page.reload")  # the phone layout starts with a phone-sized window
    for _ in range(60):
        time.sleep(1)
        try:
            if js("return !!app.plugins?.plugins?.['full-keep-mode'] && app.workspace.layoutReady;"):
                break
        except RuntimeError:
            pass
    time.sleep(3)
    if not on:
        ob.call("Emulation.clearDeviceMetricsOverride")
    # A covered window doesn't draw and its timers slow down: keep it going.
    js("""const wc = require("@electron/remote").getCurrentWebContents(); wc.setBackgroundThrottling(!""" + json.dumps(on) + """);
        wc.invalidate(); try { await wc.capturePage(); } catch {} return 1;""")


def reset():
    js(CM + f"cm.dispatch({{ changes: {{ from: 0, to: cm.state.doc.length, insert: {json.dumps(TEXT)} }} }}); cm.contentDOM.blur(); await wait(700);")


def body():
    return js(CM + "return cm.state.doc.toString();").split("---\n")[-1]


def tap(p):
    ob.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": p["x"], "y": p["y"]}])
    ob.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    time.sleep(0.8)


def swipe(text, dx, hold=0, dy=2):
    """Touches as the phone sends them, sideways over an item."""
    return js(CM + f"""const l = [...cm.contentDOM.querySelectorAll('.cm-line')].find(l => l.textContent.includes({json.dumps(text)}));
        const r = l.getBoundingClientRect(); const x0 = r.left + r.width * 0.6, y0 = r.top + r.height - 8;
        const ev = (type, x, y) => {{ const t = new Touch({{ identifier: 1, target: l, clientX: x, clientY: y }});
            l.dispatchEvent(new TouchEvent(type, {{ touches: type === 'touchend' ? [] : [t], changedTouches: [t], bubbles: true, cancelable: true }})); }};
        ev('touchstart', x0, y0);
        if ({hold}) await wait({hold});
        for (let k = 1; k <= 6; k++) {{ ev('touchmove', x0 + {dx} * k / 6, y0 + {dy} * k / 6); await wait(20); }}
        ev('touchend', x0 + {dx}, y0 + {dy}); await wait(400);
        return cm.state.doc.toString().split('---\\n').pop();""")


def main():
    phone_layout(True)
    try:
        js(PRE + f"""const F = {json.dumps(F)};
            if (!app.vault.getAbstractFileByPath(F)) await app.vault.createFolder(F);
            const p = F + "/Phone.md"; let f = app.vault.getAbstractFileByPath(p);
            if (f) await app.vault.modify(f, {json.dumps(TEXT)}); else f = await app.vault.create(p, {json.dumps(TEXT)});
            document.querySelectorAll(".modal-container").forEach(m => m.remove());
            await app.plugins.plugins["full-keep-mode"].openNoteOnBoard(f); await wait(2500);""")
        lt.check("the note opens in the phone pop-up", js("return document.body.hasClass('is-phone') && !!document.querySelector('.fkm-note-modal .cm-line');"))
        reset()

        print("Keep's measures")
        m = js(CM + """const modal = document.querySelector('.fkm-note-modal');
            const T = modal.querySelector('.fkm-title, .inline-title:not([style*="none"])').getBoundingClientRect().left;
            const textX = l => { const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT); let n;
                while ((n = w.nextNode())) { if (n.parentElement.closest('.fkm-prefix')) continue; const r = document.createRange(); r.setStart(n, 0); r.setEnd(n, 1); return r.getBoundingClientRect(); } };
            const r1 = n => Math.round(n);
            return [...cm.contentDOM.querySelectorAll('.cm-line.fkm-task, .cm-line.fkm-extra')].map(l => {
                const b = l.querySelector('input')?.getBoundingClientRect(); const g = l.querySelector('.fkm-grip svg')?.getBoundingClientRect(); const x = textX(l);
                return { box: b ? r1(b.left - T) : null, size: b ? r1(b.width) : null, grip: g ? r1(g.left + g.width / 2 - T) : null, text: r1(x.left - T), top: x.top }; });""")
        lt.check("checkbox 18 px at 35, text at 76, grip at 14, like Keep's iPhone app",
                 (m[0]["box"], m[0]["size"], m[0]["text"], m[0]["grip"]) == (35, 18, 76, 14), m[0])
        lt.check("a sub-item 30 px further in, its grip below the parent's checkbox",
                 (m[1]["box"], m[1]["text"], m[1]["grip"]) == (65, 106, 44), m[1])
        lt.check("a sub-item's second line starts under its text", m[2]["text"] == m[1]["text"], m[2])
        lt.check("items 35 px apart", round(m[4]["top"] - m[3]["top"]) == 35, (m[3]["top"], m[4]["top"]))

        print("Cursor and selecting")
        r = js(CM + """const out = {};
            out.textFirst = [...cm.contentDOM.querySelectorAll('.cm-line.fkm-task, .cm-line.fkm-extra')].every(l => {
                const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT); let n;
                while ((n = w.nextNode())) { if (n.parentElement.closest('.fkm-prefix, .fkm-extra-spacer')) continue; return /\\S/.test(n.textContent[0]); } return true; });
            out.editable = [...cm.contentDOM.querySelectorAll('.fkm-prefix')].some(p => p.isContentEditable);
            const d = cm.state.doc.toString(); const sub = cm.state.doc.line(d.split('\\n').indexOf('\\t- [ ] Sub one') + 1);
            out.cursor = [0, 1, 3, 6, 7].map(o => { cm.dispatch({ selection: { anchor: sub.from + o } }); const h = cm.state.selection.main.head; return d.slice(h, h + 3); });
            return out;""")
        lt.check("nothing in front of an item's text is text (indent, grip, checkbox)", r["textFirst"] and not r["editable"], r)
        lt.check("a cursor anywhere in front of an item's text goes to its text", r["cursor"] == ["Sub"] * 5, r["cursor"])

        def select_all(how, at="Sub one"):
            return js(CM + f"""cm.focus(); const d = cm.state.doc.toString();
                cm.dispatch({{ selection: {{ anchor: d.indexOf({json.dumps(at)}) + 2 }} }}); await wait(300);
                {how} await wait(400);
                const s = cm.state.selection.main; return cm.state.doc.sliceString(s.from, s.to);""")
        reset()
        lt.check("\"Select All\" in a sub-item selects its text (the page's own Select All)",
                 select_all("document.execCommand('selectAll');") == "Sub one\n\t\tsecond line")
        again = js(CM + "document.execCommand('selectAll'); await wait(400); const s = cm.state.selection.main; return cm.state.doc.sliceString(s.from, s.to);")
        lt.check("…also when the phone applies it again right after", again == "Sub one\n\t\tsecond line", repr(again))
        reset()
        untagged = select_all("cm.dispatch({ selection: { anchor: 0, head: cm.state.doc.length } });")
        lt.check("…and when it comes without saying where from (Obsidian's own)", untagged == "Sub one\n\t\tsecond line", repr(untagged))
        reset()
        lt.check("…and in a top-level item, its text", select_all("document.execCommand('selectAll');", "Top two") == "Top two")
        reset()
        made = js(CM + """const d = cm.state.doc.toString();
            cm.dispatch({ selection: { anchor: d.indexOf('Sub one') + 2, head: d.indexOf('Top two') + 3 } });
            const s = cm.state.selection.main; return [s.from, s.to, d.indexOf('Sub one') + 2, d.indexOf('Top two') + 3];""")
        lt.check("a selection being made is left as it is", made[:2] == made[2:], made)

        # A long note: the editor draws only the part around the screen, and the phone's
        # Select All selects what's drawn (seen in a recording from an iPhone).
        long = "---\nkeep_color: blue\n---\n" + "".join(f"- [ ] Item {n}\n\t- [ ] Sub {n}\n\t\tsecond line {n}\n" for n in range(1, 301))
        r = js(CM + f"""cm.dispatch({{ changes: {{ from: 0, to: cm.state.doc.length, insert: {json.dumps(long)} }} }}); await wait(600);
            cm.focus(); const d = cm.state.doc.toString(); const at = d.indexOf("Sub 150") + 2;
            cm.dispatch({{ selection: {{ anchor: at }}, scrollIntoView: true }}); await wait(800);
            const drawn = !!cm.contentDOM.querySelector('.cm-gap') && cm.viewport.to < cm.state.doc.length;
            // As recorded on an iPhone: the selection the editor got from the phone's Select All
            // runs from the first drawn line to the end of the drawn part (Chrome reads the same
            // page selection as the whole note, so it's given as the editor received it).
            const first = cm.state.doc.lineAt(cm.viewport.from).from, last = cm.state.doc.lineAt(cm.viewport.to).to;
            cm.dispatch({{ selection: {{ anchor: first, head: last }}, userEvent: "select" }}); await wait(500);
            const s = cm.state.selection.main; return {{ drawn, text: cm.state.doc.sliceString(s.from, s.to) }};""")
        lt.check("…also in a long note, where only part of it is drawn", r["drawn"] and r["text"] == "Sub 150\n\t\tsecond line 150", r)
        reset()

        # Dragging a selection's handle down to the next lines is a swipe down too: it
        # mustn't put the keyboard away (that ends the selection).
        def drag_down(selected):
            return js(CM + f"""cm.focus(); const d = cm.state.doc.toString();
                cm.dispatch({{ selection: {json.dumps(selected)} ? {{ anchor: d.indexOf('Sub one'), head: d.indexOf('Sub one') + 3 }} : {{ anchor: d.indexOf('Sub one') + 2 }} }}); await wait(300);
                const l = [...cm.contentDOM.querySelectorAll('.cm-line')].find(l => l.textContent.includes('Sub one'));
                const r = l.getBoundingClientRect(); const x0 = r.left + 120, y0 = r.top + 10;
                const ev = (type, y) => {{ const t = new Touch({{ identifier: 2, target: l, clientX: x0 + 3, clientY: y }});
                    l.dispatchEvent(new TouchEvent(type, {{ touches: type === 'touchend' ? [] : [t], changedTouches: [t], bubbles: true, cancelable: true }})); }};
                ev('touchstart', y0);
                for (let k = 1; k <= 6; k++) {{ ev('touchmove', y0 + 12 * k); await wait(30); }}
                ev('touchend', y0 + 72); await wait(300);
                return {{ focused: cm.hasFocus, selected: !cm.state.selection.main.empty }};""")
        r = drag_down(True)
        lt.check("dragging a selection down doesn't put the keyboard away or end the selection", r == {"focused": True, "selected": True}, r)
        r = drag_down(False)
        lt.check("…while a swipe down without a selection does put the keyboard away", r["focused"] is False, r)
        reset()

        print("Taps")
        reset()
        def point(which):
            return js(CM + f"""const l = [...cm.contentDOM.querySelectorAll('.cm-line')].find(l => l.textContent.includes('Sub one'));
                const box = l.querySelector('input').getBoundingClientRect();
                const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT); let n, x = null;
                while ((n = w.nextNode())) {{ if (n.parentElement.closest('.fkm-prefix')) continue; const r = document.createRange(); r.setStart(n, 0); r.setEnd(n, 1); x = r.getBoundingClientRect().left; break; }}
                return {json.dumps(which)} === 'gap' ? {{ x: (box.right + x) / 2, y: box.top + box.height / 2 }} : {{ x: box.left + box.width / 2, y: box.top + box.height / 2 }};""")
        tap(point("gap"))
        lt.check("a tap between the checkbox and the text doesn't tick the item", "- [ ] Sub one" in body(), body())
        tap(point("box"))
        lt.check("a tap on the checkbox ticks it", "- [x] Sub one" in body(), body())

        print("Swiping")
        base = "- [ ] Top one\n\t- [ ] Sub one\n\t\tsecond line\n\t- [ ] Sub two\n- [ ] Top two\n"
        reset()
        lt.check("swiping an item right indents it", swipe("Top two", 90) == "- [ ] Top one\n\t- [ ] Sub one\n\t\tsecond line\n\t- [ ] Sub two\n\t- [ ] Top two\n")
        reset()
        lt.check("swiping a sub-item left outdents it", swipe("Sub two", -90) == "- [ ] Top one\n\t- [ ] Sub one\n\t\tsecond line\n- [ ] Sub two\n- [ ] Top two\n")
        reset()
        lt.check("not after a long press (that selects text)", swipe("Top two", 90, hold=600) == base)
        reset()
        lt.check("not up or down (scrolling)", swipe("Top two", 5, dy=120) == base)
        reset()
        js(CM + "const d = cm.state.doc.toString(); cm.dispatch({ selection: { anchor: d.indexOf('Top two'), head: d.indexOf('Top two') + 3 } });")
        lt.check("not while text is selected (moving a selection's handles)", swipe("Top two", 90) == base)
    finally:
        js(PRE + f"""document.querySelectorAll('.modal-container').forEach(m => m.remove());
            const f = app.vault.getAbstractFileByPath({json.dumps(F)}); if (f) await app.vault.delete(f, true); return 1;""")
        phone_layout(False)
    failed = [r for r in lt.results if not r[1]]
    print(f"\n{len(lt.results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
