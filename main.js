/*
 * Full Keep Mode - the Google Keep experience in Obsidian.
 *
 * Notes and the board (with the Keep Bases View plugin, which draws the cards):
 *  - Pin and colour buttons in every note's top bar (also in the Keep pop-up).
 *  - A "Take a note…" bar on the board; the new note opens in the Keep pop-up and
 *    is thrown away if it's closed untouched.
 *  - Drag cards to reorder them - with the mouse, or hold and drag on a phone.
 *  - A command that sets up a ready-made Keep board.
 *
 * Checklists that behave like Google Keep's:
 *  - Ticked items drop below a "N ticked items" divider; unticking moves them back.
 *  - A ticked sub-item of an unticked item is shown in the ticked section under a
 *    faded "ghost" copy of its parent (the note itself keeps it under the parent).
 *  - Ticking an item ticks its sub-items too.
 *  - Drag the grip in front of an item to reorder it, or sideways to indent or
 *    outdent it - with a mouse or a finger. Two levels, like Keep (configurable).
 *  - Items that span several lines are lined up with the item's text.
 *  - Undo / redo buttons in the note's top bar.
 *
 * Works in the editor (Live Preview and Source mode), not in Reading view.
 * Plain JavaScript (CommonJS), no build step.
 */
"use strict";

const obsidian = require("obsidian");
const { EditorView, Decoration, WidgetType, ViewPlugin, keymap } = require("@codemirror/view");
const { StateField, StateEffect, Annotation, Prec } = require("@codemirror/state");

const DEFAULT_SETTINGS = {
	sinkTicked: true, // move ticked items below the divider
	ghostParents: true, // ticked sub-items of unticked items go to the ticked section
	tickSubItems: true, // ticking an item ticks its sub-items
	dragHandles: true,
	maxIndent: 1, // levels of indentation below the top level (1 = like Keep, 0 = unlimited)
	alignExtraLines: true,
	undoButtons: true,
	// notes and board
	pinButton: true,
	colorButton: true,
	archiveButton: true,
	reminders: true,
	takeANote: true,
	dragCards: true,
	firedReminders: {}, // path -> reminder time already shown (so each one fires once)
};

// A note can opt out of the checklist features with this property set to false.
const OPT_OUT_PROPERTY = "full-keep-mode";

// Note properties, shared with the Keep Bases View plugin (which draws the board).
const PIN_PROPERTY = "keep_pinned";
const COLOR_PROPERTY = "keep_color";
const ORDER_PROPERTY = "keep_order"; // position on the board; higher = further up
const ARCHIVE_PROPERTY = "keep_archived"; // true = archived (the tag #archived counts too)
const REMINDER_PROPERTY = "keep_reminder"; // local date and time, "YYYY-MM-DDTHH:mm"
const ARCHIVE_TAG = "archived";
const KEEP_VIEW_PLUGIN = "keep-bases-view";
const COLORS = [
	{ id: null, name: "Default" },
	{ id: "red", name: "Red", hex: "#f28b82" },
	{ id: "orange", name: "Orange", hex: "#fbbc04" },
	{ id: "yellow", name: "Yellow", hex: "#fff475" },
	{ id: "green", name: "Green", hex: "#ccff90" },
	{ id: "cyan", name: "Teal", hex: "#a8f0e0" },
	{ id: "blue", name: "Blue", hex: "#aecbfa" },
	{ id: "purple", name: "Purple", hex: "#d7aefb" },
	{ id: "pink", name: "Pink", hex: "#fdcfe8" },
];

// The board the "Create a Keep board" command sets up. Newest notes come first;
// a note dragged to a new place gets a keep_order between its neighbours'.
// A second view shows the archive.
const BOARD_BASE = `filters:
  and:
    - 'file.ext == "md"'
formulas:
  board_order: 'if(${ORDER_PROPERTY}, ${ORDER_PROPERTY}, number(file.ctime))'
views:
  - type: keep-grid-view
    name: Board
    filters:
      not:
        - file.hasTag("${ARCHIVE_TAG}")
        - '${ARCHIVE_PROPERTY} == true'
    order:
      - file.name
      - file.tags
      - note.${REMINDER_PROPERTY}
    sort:
      - property: ${PIN_PROPERTY}
        direction: DESC
      - property: formula.board_order
        direction: DESC
  - type: keep-grid-view
    name: Archive
    filters:
      or:
        - file.hasTag("${ARCHIVE_TAG}")
        - '${ARCHIVE_PROPERTY} == true'
    order:
      - file.name
      - file.tags
    sort:
      - property: file.mtime
        direction: DESC
`;
const INDENT_STEP = 28; // px of sideways drag per indent level
const MAX_STYLED_DEPTH = 5; // indent levels with alignment styles (deeper ones use level 5's)

// ----- reading checklists -----------------------------------------------------------------

// A checklist item: indentation, bullet, "[ ]" or "[x]" (any mark counts as ticked), text.
const TASK_RE = /^([ \t]*)([-*+]) \[(.)\](?: (.*))?$/;
// Unindented lines that end a checklist: headings, rules, other lists, quotes, code, tables.
const HARD_BREAK_RE = /^(?:#{1,6}(?:\s|$)|(?:---|\*\*\*|___)\s*$|[-*+]\s|\d+[.)]\s|>|```|~~~|\|)/;
const isBlank = text => !text.trim();
const isIndented = text => /^[ \t]/.test(text);

function indentUnit(app) {
	const useTab = app.vault.getConfig("useTab") !== false;
	const tabSize = Number(app.vault.getConfig("tabSize")) || 4;
	return { useTab, tabSize, text: useTab ? "\t" : " ".repeat(tabSize) };
}

function depthOf(indent, unit) {
	const tabs = (indent.match(/\t/g) || []).length;
	const spaces = indent.length - tabs;
	return tabs + Math.ceil(spaces / unit.tabSize);
}

function parseTask(line, unit) {
	const m = TASK_RE.exec(line);
	if (!m) return null;
	return {
		indent: m[1],
		depth: depthOf(m[1], unit),
		bullet: m[2],
		mark: m[3],
		checked: m[3] !== " ",
		text: m[4] ?? "",
	};
}

// Index of the item's text in its line ("- [ ] " and the indentation before it).
function textOffset(lineText) {
	const m = TASK_RE.exec(lineText);
	return m ? m[0].length - (m[4] ?? "").length : 0;
}

// All checklists of a document. Lines under an item belong to it (its "extra"
// lines): indented text, and blank lines followed by more indented text.
// Unindented plain text right under an item belongs to it too.
function findBlocks(doc, unit) {
	const blocks = [];
	let block = null;
	const close = () => {
		if (block) blocks.push(block);
		block = null;
	};
	for (let n = 1; n <= doc.lines; n++) {
		const text = doc.line(n).text;
		const task = parseTask(text, unit);
		if (task) {
			if (!block) block = { fromLine: n, toLine: n, items: [] };
			block.items.push({ ...task, origDepth: task.depth, line: n, extra: [] });
			block.toLine = n;
			continue;
		}
		if (!block) continue;
		if (isBlank(text)) {
			let next = n + 1;
			while (next <= doc.lines && isBlank(doc.line(next).text)) next++;
			const following = next <= doc.lines ? doc.line(next).text : null;
			if (following !== null && isIndented(following) && !parseTask(following, unit)) {
				for (let k = n; k < next; k++) block.items[block.items.length - 1].extra.push(doc.line(k).text);
				n = next - 1;
				continue;
			}
			close();
			continue;
		}
		if (!isIndented(text) && HARD_BREAK_RE.test(text)) {
			close();
			continue;
		}
		block.items[block.items.length - 1].extra.push(text);
		block.toLine = n;
	}
	close();
	return blocks;
}

function findBlock(doc, lineNo, unit) {
	return findBlocks(doc, unit).find(b => b.fromLine <= lineNo && lineNo <= b.toLine) ?? null;
}

// Index just past item `index` and everything indented under it.
function descendantsEnd(items, index) {
	let end = index + 1;
	while (end < items.length && items[end].depth > items[index].depth) end++;
	return end;
}

const baseDepth = items => Math.min(...items.map(item => item.depth));

// ----- writing checklists -----------------------------------------------------------------

function renderItem(item, unit) {
	const indent = depth => (unit.useTab ? "\t".repeat(depth) : " ".repeat(unit.tabSize * depth));
	// Keep the item's own indentation characters unless its level changed.
	const lead = item.depth === item.origDepth ? item.indent : indent(item.depth);
	const head = `${lead}${item.bullet} [${item.mark}] ${item.text}`;
	if (item.depth === item.origDepth) return [head, ...item.extra].join("\n");
	// Extra lines follow the item in or out by the same number of levels.
	const oldIndent = indent(item.origDepth + 1);
	const newIndent = indent(item.depth + 1);
	const extra = item.extra.map(line => (line.startsWith(oldIndent) ? newIndent + line.slice(oldIndent.length) : line));
	return [head, ...extra].join("\n");
}

// Like Keep: unticked items first, ticked after, on every level; sub-items travel
// with their parent. Otherwise the order is kept.
function sinkItems(items) {
	if (!items.length) return [];
	const base = baseDepth(items);
	const groups = [];
	for (const item of items) {
		if (item.depth === base || !groups.length) groups.push({ head: item, rest: [] });
		else groups[groups.length - 1].rest.push(item);
	}
	const ordered = [...groups.filter(g => !g.head.checked), ...groups.filter(g => g.head.checked)];
	return ordered.flatMap(g => [g.head, ...sinkItems(g.rest)]);
}

const ownEdit = Annotation.define(); // our own edits must not trigger sorting again
const refreshEffect = StateEffect.define();

function writeItems(view, block, items, unit) {
	const doc = view.state.doc;
	const from = doc.line(block.fromLine).from;
	const to = doc.line(block.toLine).to;
	const insert = items.map(item => renderItem(item, unit)).join("\n");
	if (insert === doc.sliceString(from, to)) return false;
	// No user event: right after a tick, undo history merges this with the tick
	// itself, so one undo restores the list exactly.
	view.dispatch({ changes: { from, to, insert }, annotations: ownEdit.of(true) });
	return true;
}

// ----- the editor extension -----------------------------------------------------------------

function checklistExtension(plugin) {
	const app = plugin.app;
	const settings = () => plugin.settings;

	const fileOf = state => (obsidian.editorInfoField ? state.field(obsidian.editorInfoField, false)?.file : null);
	const enabledFor = state => {
		const file = fileOf(state);
		if (!file) return true;
		return app.metadataCache.getFileCache(file)?.frontmatter?.[OPT_OUT_PROPERTY] !== false;
	};

	// Item text without link syntax, for the ghost rows.
	const plainText = md => md
		.replace(/\[\[([^\]|]*)\|([^\]]*)\]\]/g, "$2")
		.replace(/\[\[([^\]]*)\]\]/g, "$1")
		.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1");

	// Untick a sub-item shown in the ticked section; it then returns to its parent.
	const untick = (view, child) => {
		const doc = view.state.doc;
		if (child.line > doc.lines) return;
		const line = doc.line(child.line);
		const m = TASK_RE.exec(line.text);
		if (!m || m[3] === " " || (m[4] ?? "") !== child.text) return;
		const pos = line.from + m[1].length + 3;
		view.dispatch({ changes: { from: pos, to: pos + 1, insert: " " }, userEvent: "input" });
	};

	class GripWidget extends WidgetType {
		eq() {
			return true;
		}
		toDOM(view) {
			// No aria-label: Obsidian would show it as a tooltip right over the list while dragging.
			const el = createSpan({ cls: "fkm-grip" });
			obsidian.setIcon(el, "grip-vertical");
			el.addEventListener("pointerdown", event => plugin.startItemDrag(view, el, event));
			return el;
		}
		ignoreEvent() {
			return true;
		}
	}

	// Stands in for the leading whitespace of an item's extra line beyond the
	// item's own indentation; its width puts the text under the item's text.
	class SpacerWidget extends WidgetType {
		constructor(depth) {
			super();
			this.depth = depth;
		}
		eq(other) {
			return other.depth === this.depth;
		}
		toDOM() {
			return createSpan({ cls: `fkm-extra-spacer fkm-depth-${this.depth}` });
		}
		ignoreEvent() {
			return false;
		}
	}

	// The "N ticked items" divider, with ghost parents and their ticked sub-items.
	class TickedSection extends WidgetType {
		constructor(count, ghosts) {
			super();
			this.count = count;
			this.ghosts = ghosts;
			this.key = JSON.stringify([count, ghosts]);
		}
		eq(other) {
			return other.key === this.key;
		}
		toDOM(view) {
			const el = createDiv({ cls: "fkm-ticked-section" });
			el.createDiv({ cls: "fkm-ticked-label", text: `${this.count} ticked item${this.count === 1 ? "" : "s"}` });
			for (const ghost of this.ghosts) {
				const group = el.createDiv({ cls: "fkm-ghost-group" });
				const parent = group.createDiv({ cls: "fkm-ghost-item fkm-ghost-parent" });
				parent.createEl("input", { type: "checkbox", cls: "task-list-item-checkbox" }).disabled = true;
				parent.createSpan({ cls: "fkm-ghost-text", text: plainText(ghost.parent) });
				for (const child of ghost.children) {
					const row = group.createDiv({ cls: "fkm-ghost-item fkm-ghost-child" });
					const box = row.createEl("input", { type: "checkbox", cls: "task-list-item-checkbox" });
					box.checked = true;
					box.setAttribute("aria-label", "Untick");
					box.addEventListener("click", event => {
						event.preventDefault();
						untick(view, child);
					});
					row.createSpan({ cls: "fkm-ghost-text", text: plainText(child.text) });
				}
			}
			el.addEventListener("mousedown", event => event.preventDefault());
			return el;
		}
		ignoreEvent() {
			return true;
		}
	}

	const build = state => {
		const s = settings();
		if (!enabledFor(state)) return Decoration.none;
		const unit = indentUnit(app);
		const doc = state.doc;
		const decos = [];
		for (const block of findBlocks(doc, unit)) {
			const { items } = block;
			const base = baseDepth(items);
			const lastLineOf = i => {
				const end = descendantsEnd(items, i);
				return end < items.length ? items[end].line - 1 : block.toLine;
			};
			// The trailing run of ticked top-level items is the "ticked items" section.
			let start = -1;
			if (s.sinkTicked) {
				for (let i = items.length - 1; i >= 0; i--) {
					if (items[i].depth !== base) continue;
					if (!items[i].checked) break;
					start = i;
				}
			}
			// Ticked sub-items of unticked items: hidden under their parent and shown
			// in the ticked section instead, under a ghost of the parent.
			const ghosts = [];
			const hidden = new Set();
			const hiddenRanges = [];
			if (s.sinkTicked && s.ghostParents) {
				const topEnd = start >= 0 ? start : items.length;
				for (let i = 0; i < topEnd; i++) {
					if (items[i].depth !== base || items[i].checked) continue;
					const children = [];
					for (let c = i + 1; c < descendantsEnd(items, i); c++) {
						if (items[c].depth !== base + 1 || !items[c].checked) continue;
						for (let k = c; k < descendantsEnd(items, c); k++) hidden.add(k);
						const last = hiddenRanges[hiddenRanges.length - 1];
						if (last && last[1] === items[c].line - 1) last[1] = lastLineOf(c);
						else hiddenRanges.push([items[c].line, lastLineOf(c)]);
						children.push({ line: items[c].line, text: items[c].text });
					}
					if (children.length) ghosts.push({ parent: items[i].text, children });
				}
			}
			for (const [first, last] of hiddenRanges) {
				decos.push(Decoration.replace({ block: true }).range(doc.line(first).from, doc.line(last).to));
			}
			items.forEach((item, i) => {
				if (hidden.has(i)) return;
				const depth = Math.min(item.depth, MAX_STYLED_DEPTH);
				const head = doc.line(item.line);
				if (s.dragHandles) {
					// After the indentation, so the grip floats right next to the checkbox.
					decos.push(Decoration.widget({ widget: new GripWidget(), side: -1 }).range(head.from + item.indent.length));
				}
				if (!s.alignExtraLines) return;
				// Wrapped lines of the item hang exactly under its text.
				decos.push(Decoration.line({ class: `fkm-task fkm-depth-${depth}` }).range(head.from));
				// Extra lines: keep the item's own indentation (and its guide line),
				// replace the rest of the leading whitespace by a spacer.
				for (let k = 1; k <= item.extra.length; k++) {
					const line = doc.line(item.line + k);
					if (isBlank(line.text)) continue;
					const lead = line.text.match(/^[ \t]*/)[0];
					const keep = Math.min(item.indent.length, lead.length);
					const keepOk = lead.slice(0, keep) === item.indent.slice(0, keep);
					const from = line.from + (keepOk ? keep : 0);
					decos.push(Decoration.line({ class: `fkm-extra fkm-depth-${depth}` }).range(line.from));
					const spacer = new SpacerWidget(depth);
					if (line.from + lead.length > from) {
						decos.push(Decoration.replace({ widget: spacer }).range(from, line.from + lead.length));
					} else {
						decos.push(Decoration.widget({ widget: spacer, side: 1 }).range(from));
					}
				}
			});
			const ghostCount = ghosts.reduce((sum, g) => sum + g.children.length, 0);
			const count = (start >= 0 ? items.length - start : 0) + ghostCount;
			if (count) {
				const section = new TickedSection(count, ghosts);
				if (start >= 0) {
					decos.push(Decoration.widget({ widget: section, block: true, side: -1 }).range(doc.line(items[start].line).from));
				} else {
					decos.push(Decoration.widget({ widget: section, block: true, side: 1 }).range(doc.line(block.toLine).to));
				}
			}
		}
		return Decoration.set(decos, true);
	};

	const decorations = StateField.define({
		create: state => build(state),
		update: (decos, tr) => (tr.docChanged || tr.effects.some(e => e.is(refreshEffect)) ? build(tr.state) : decos),
		provide: field => EditorView.decorations.from(field),
	});

	// Ticking or unticking an item (same line, only the tick changed): tick its
	// sub-items along, and move it to its place - like Keep.
	const onTick = EditorView.updateListener.of(update => {
		if (!update.docChanged) return;
		const s = settings();
		if (!s.sinkTicked && !s.tickSubItems) return;
		if (update.transactions.some(tr => tr.annotation(ownEdit) || tr.isUserEvent("undo") || tr.isUserEvent("redo"))) return;
		if (!enabledFor(update.state)) return;
		const unit = indentUnit(app);
		let toggled = null;
		update.changes.iterChanges((fromA, toA, fromB, toB) => {
			if (toggled !== null) return;
			const oldLine = update.startState.doc.lineAt(fromA);
			const newLine = update.state.doc.lineAt(fromB);
			if (toA > oldLine.to || toB > newLine.to) return;
			const before = parseTask(oldLine.text, unit);
			const after = parseTask(newLine.text, unit);
			if (before && after && before.checked !== after.checked && before.text === after.text && before.depth === after.depth) {
				toggled = newLine.from;
			}
		});
		if (toggled === null) return;
		const view = update.view;
		setTimeout(() => {
			if (!view.dom.isConnected || toggled > view.state.doc.length) return;
			const lineNo = view.state.doc.lineAt(toggled).number;
			const block = findBlock(view.state.doc, lineNo, unit);
			if (!block) return;
			const items = block.items.map(item => ({ ...item }));
			const index = items.findIndex(item => item.line === lineNo);
			if (index < 0) return;
			if (s.tickSubItems) {
				for (let i = index + 1; i < descendantsEnd(items, index); i++) {
					items[i].checked = items[index].checked;
					items[i].mark = items[index].checked ? (items[i].checked && items[i].mark !== " " ? items[i].mark : "x") : " ";
				}
			}
			writeItems(view, block, s.sinkTicked ? sinkItems(items) : items, unit);
		}, 0);
	});

	// Measure, per indent level, where item text starts (H) and where the spacer
	// of extra lines starts, and set CSS variables on the editor:
	// --fkm-hang-N (padding / hanging indent) and --fkm-spacer-N (spacer width).
	// Only item lines are used to measure H, and a spacer's start doesn't depend on
	// its own width, so nothing can drift. Items under the cursor or selection are
	// skipped (Obsidian shows their raw "- [ ]" then), so nothing jumps.
	const hangMeasure = ViewPlugin.fromClass(class {
		constructor(view) {
			this.values = {};
			this.measure(view);
			// Obsidian finishes drawing checkboxes a little later; measure again then.
			this.timers = [250, 1000].map(ms => setTimeout(() => this.measure(view), ms));
		}
		update(update) {
			if (update.docChanged || update.viewportChanged || update.geometryChanged || update.selectionSet
				|| update.transactions.some(tr => tr.effects.some(e => e.is(refreshEffect)))) {
				this.measure(update.view);
			}
		}
		destroy() {
			this.timers.forEach(clearTimeout);
		}
		measure(view) {
			if (!settings().alignExtraLines) return;
			view.requestMeasure({
				key: this,
				read: v => this.read(v),
				write: (found, v) => {
					for (const [depth, { hang, spacer }] of Object.entries(found)) {
						const old = this.values[depth] ?? {};
						if (old.hang !== hang) v.dom.style.setProperty(`--fkm-hang-${depth}`, `${hang}px`);
						if (spacer !== null && old.spacer !== spacer) v.dom.style.setProperty(`--fkm-spacer-${depth}`, `${spacer}px`);
						this.values[depth] = { hang, spacer: spacer ?? old.spacer };
					}
				},
			});
		}
		read(v) {
			const unit = indentUnit(app);
			const doc = v.state.doc;
			const ranges = v.state.selection.ranges;
			const touched = line => ranges.some(r => r.from <= line.to && r.to >= line.from);
			const lineElAt = pos => {
				const at = v.domAtPos(pos);
				return (at.node.nodeType === 3 ? at.node.parentElement : at.node)?.closest?.(".cm-line") ?? null;
			};
			// x of the first visible letter at or after `pos`, relative to its line box
			const letterX = (pos, lineEl) => {
				const at = v.domAtPos(pos);
				let node = at.node;
				let offset = at.offset;
				const walker = document.createTreeWalker(lineEl, NodeFilter.SHOW_TEXT);
				if (node.nodeType !== 3) {
					const start = node.childNodes[offset] ?? null;
					walker.currentNode = start ?? lineEl;
					node = start?.nodeType === 3 ? start : walker.nextNode();
					offset = 0;
				}
				while (node) {
					const i = node.textContent.slice(offset).search(/\S/);
					if (i >= 0) {
						const range = document.createRange();
						range.setStart(node, offset + i);
						range.setEnd(node, offset + i + 1);
						return range.getBoundingClientRect().left - lineEl.getBoundingClientRect().left;
					}
					walker.currentNode = node;
					node = walker.nextNode();
					offset = 0;
				}
				return null;
			};
			const hangs = {};
			const spacerStarts = {};
			for (const block of findBlocks(doc, unit)) {
				for (const item of block.items) {
					const depth = Math.min(item.depth, MAX_STYLED_DEPTH);
					const head = doc.line(item.line);
					if (head.to < v.viewport.from || head.from > v.viewport.to) continue;
					if (hangs[depth] === undefined && !touched(head) && item.text.trim()) {
						const headEl = lineElAt(head.from);
						const x = headEl && letterX(head.from + textOffset(head.text), headEl);
						if (typeof x === "number") hangs[depth] = Math.round(x);
					}
					if (spacerStarts[depth] === undefined) {
						for (let k = 1; k <= item.extra.length; k++) {
							const lineEl = lineElAt(doc.line(item.line + k).from);
							const spacer = lineEl?.querySelector(".fkm-extra-spacer");
							if (!spacer) continue;
							spacerStarts[depth] = spacer.getBoundingClientRect().left - lineEl.getBoundingClientRect().left;
							break;
						}
					}
				}
			}
			const found = {};
			for (const [depth, hang] of Object.entries(hangs)) {
				const start = spacerStarts[depth];
				found[depth] = { hang, spacer: start === undefined ? null : Math.max(0, Math.round(hang - start)) };
			}
			return found;
		}
	});

	// Tab indents an item once under the item above it, taking its sub-items
	// along; with two levels (like Keep) they all become sub-items.
	const tabKey = Prec.highest(keymap.of([{
		key: "Tab",
		run: view => {
			if (!enabledFor(view.state)) return false;
			const unit = indentUnit(app);
			const sel = view.state.selection;
			const doc = view.state.doc;
			const n = doc.lineAt(sel.main.head).number;
			const block = findBlock(doc, n, unit);
			if (!block) return false; // not a checklist: Obsidian's usual Tab
			if (sel.ranges.length > 1 || doc.lineAt(sel.main.from).number !== doc.lineAt(sel.main.to).number) {
				return settings().maxIndent > 0; // several lines: leave alone in two-level mode
			}
			const index = block.items.findIndex(item => item.line === n);
			if (index < 0) return true; // an extra line of an item
			const items = block.items.map(item => ({ ...item }));
			const base = baseDepth(items);
			const prev = items[index - 1];
			const limit = plugin.maxDepth(base, prev);
			if (!prev || items[index].depth >= limit) return true;
			const shift = 1;
			for (let i = index; i < descendantsEnd(items, index); i++) {
				items[i].depth = Math.min(items[i].depth + shift, plugin.depthCap(base));
			}
			writeItems(view, block, settings().sinkTicked ? sinkItems(items) : items, unit);
			return true;
		},
	}]));

	// Undo, redo, pin and colour buttons in the note's top bar (also in pop-up editors).
	const headerButtons = ViewPlugin.fromClass(class {
		constructor(view) {
			const info = obsidian.editorInfoField ? view.state.field(obsidian.editorInfoField, false) : null;
			if (info instanceof obsidian.MarkdownView) plugin.addHeaderButtons(info);
		}
	});

	return [decorations, onTick, hangMeasure, tabKey, headerButtons];
}

// ----- settings tab -------------------------------------------------------------------------

class FullKeepModeSettingTab extends obsidian.PluginSettingTab {
	constructor(app, plugin) {
		super(app, plugin);
		this.plugin = plugin;
	}

	display() {
		const { containerEl } = this;
		containerEl.empty();
		const toggle = (name, desc, key) => new obsidian.Setting(containerEl).setName(name).setDesc(desc)
			.addToggle(t => t.setValue(this.plugin.settings[key]).onChange(async value => {
				this.plugin.settings[key] = value;
				await this.plugin.saveSettings();
			}));

		containerEl.createEl("h3", { text: "Notes and board" });
		if (!this.app.plugins?.manifests?.[KEEP_VIEW_PLUGIN]) {
			containerEl.createEl("p", {
				cls: "setting-item-description",
				text: "The board needs the \"Keep Bases View\" plugin (Community plugins → Browse), which draws the cards. "
					+ "Then use the command \"Create a Keep board\".",
			});
		}
		toggle("Pin button", "A pin in each note's top bar. Pinned notes are shown first on the board.", "pinButton");
		toggle("Colour button", "A palette in each note's top bar to give the note a colour.", "colorButton");
		toggle("Archive button", `A button in each note's top bar that archives the note (property "${ARCHIVE_PROPERTY}"), with Undo. The board hides archived notes; they are in its Archive view.`, "archiveButton");
		toggle("Reminders", `A bell in each note's top bar to set a reminder (property "${REMINDER_PROPERTY}"). When it is due, a notice pops up while Obsidian is open; reminders missed while it was closed are shown when it opens.`, "reminders");
		toggle("\"Take a note…\" bar", "On the board: opens a new note in the pop-up. A new note closed without any text is thrown away, like in Keep.", "takeANote");
		toggle("Drag cards", "Drag cards on the board to reorder them. On a phone: hold a card, then drag it.", "dragCards");

		containerEl.createEl("h3", { text: "Checklists" });
		toggle("Move ticked items down", "Ticked items drop below a \"ticked items\" divider; unticking moves them back up.", "sinkTicked");
		toggle("Ticked sub-items under a ghost parent", "A ticked sub-item of an unticked item is shown in the ticked section, under a faded copy of its parent. The note keeps it under the parent.", "ghostParents");
		toggle("Tick sub-items along", "Ticking or unticking an item does the same to its sub-items.", "tickSubItems");
		toggle("Drag handles", "A grip in front of each item: drag it up or down to move the item, sideways to indent or outdent it. Works with mouse and touch.", "dragHandles");
		new obsidian.Setting(containerEl)
			.setName("Indent levels")
			.setDesc("How far items can be indented by dragging or Tab.")
			.addDropdown(d => d
				.addOption("1", "Two levels, like Google Keep")
				.addOption("2", "Three levels")
				.addOption("0", "Unlimited")
				.setValue(String(this.plugin.settings.maxIndent))
				.onChange(async value => {
					this.plugin.settings.maxIndent = Number(value);
					await this.plugin.saveSettings();
				}));
		toggle("Line up multi-line items", "Extra lines of an item (Shift+Enter) and wrapped lines start exactly under the item's text.", "alignExtraLines");
		toggle("Undo and redo buttons", "Buttons in the note's top bar.", "undoButtons");

		containerEl.createEl("p", {
			cls: "setting-item-description",
			text: `A note can opt out of the checklist features with the property "${OPT_OUT_PROPERTY}: false". `
				+ "Tip: turn off Settings → Editor → \"Fold indent\" if you don't want items to be collapsible, like in Keep. "
				+ "Changes to the top-bar buttons apply to notes opened afterwards.",
		});
	}
}

// ----- the plugin ---------------------------------------------------------------------------

module.exports = class FullKeepModePlugin extends obsidian.Plugin {
	async onload() {
		await this.loadSettings();
		this.headerButtons = new Set();
		this.pinButtons = new Map(); // MarkdownView -> its pin button
		this.archiveButtons = new Map();
		this.reminderButtons = new Map();
		this.boardListeners = []; // functions that remove the board listeners
		this.registerEditorExtension(checklistExtension(this));
		this.addSettingTab(new FullKeepModeSettingTab(this.app, this));

		this.addCommand({
			id: "sort-ticked-items",
			name: "Move ticked items down in this note",
			editorCallback: editor => this.sortNote(editor.cm),
		});
		this.addCommand({
			id: "take-a-note",
			name: "Take a note",
			callback: () => this.newNote(),
		});
		this.addCommand({
			id: "create-board",
			name: "Create a Keep board",
			callback: () => this.createBoard(),
		});

		// Keep the top-bar icons in step when a note is changed elsewhere (e.g. on the board).
		this.registerEvent(this.app.metadataCache.on("changed", file => this.renderButtons(file)));
		this.registerEvent(this.app.workspace.on("file-open", () => this.renderButtons()));

		// Reminders: check now (catching up on missed ones) and every 20 seconds.
		this.app.workspace.onLayoutReady(() => {
			void this.checkReminders(true);
			this.registerInterval(window.setInterval(() => void this.checkReminders(), 20000));
		});

		// Add the "Take a note…" bar and card dragging whenever a Keep board appears
		// or redraws its cards.
		this.app.workspace.onLayoutReady(() => {
			let queued = false;
			this.boardObserver = new MutationObserver(() => {
				if (queued) return;
				queued = true;
				requestAnimationFrame(() => {
					queued = false;
					this.enhanceBoards();
				});
			});
			this.boardObserver.observe(this.app.workspace.containerEl, { childList: true, subtree: true });
			this.enhanceBoards();
		});
	}

	onunload() {
		this.headerButtons.forEach(button => button.remove());
		this.headerButtons.clear();
		this.pinButtons.clear();
		this.archiveButtons.clear();
		this.reminderButtons.clear();
		document.querySelectorAll(".fkm-drop-indicator, .fkm-take-note, .fkm-drag-ghost").forEach(el => el.remove());
		this.boardObserver?.disconnect();
		this.boardListeners.forEach(remove => remove());
		this.boardListeners = [];
		document.querySelectorAll(".kg-container").forEach(el => delete el.fullKeepModeWired);
	}

	async loadSettings() {
		const data = await this.loadData();
		this.settings = Object.assign({}, DEFAULT_SETTINGS, data);
		this.settings.firedReminders = Object.assign({}, data?.firedReminders);
	}

	async saveSettings() {
		await this.saveData(this.settings);
		this.refreshEditors();
	}

	// Redraw all open editors after a settings change.
	refreshEditors() {
		this.app.workspace.iterateAllLeaves(leaf => {
			const cm = leaf.view instanceof obsidian.MarkdownView ? leaf.view.editor?.cm : null;
			cm?.dispatch({ effects: refreshEffect.of(null) });
		});
	}

	// Deepest level an item may have, given its list's top level and the item above it.
	maxDepth(base, prev) {
		if (!prev) return base;
		return Math.min(prev.depth + 1, this.depthCap(base));
	}

	depthCap(base) {
		return this.settings.maxIndent > 0 ? base + this.settings.maxIndent : Infinity;
	}

	// Buttons in a note's top bar: undo, redo, pin, colour (like Keep's note editor).
	addHeaderButtons(view) {
		if (view.fullKeepModeButtons) return;
		view.fullKeepModeButtons = true;
		const s = this.settings;
		const added = [];
		// addAction puts each new button in front, so add them right to left:
		// undo, redo, pin, reminder, colour, archive.
		if (s.archiveButton) {
			const archive = view.addAction("archive", "Archive", () => this.toggleArchive(view));
			archive.addClass("fkm-archive-button");
			this.archiveButtons.set(view, archive);
			this.renderArchive(view, archive);
			added.push(archive);
		}
		if (s.colorButton) {
			const color = view.addAction("palette", "Colour", event => this.showColorMenu(view, event));
			color.addClass("fkm-color-button");
			added.push(color);
		}
		if (s.reminders) {
			const bell = view.addAction("bell", "Remind me", () => {
				if (view.file) new ReminderModal(this, view.file).open();
			});
			bell.addClass("fkm-reminder-button");
			this.reminderButtons.set(view, bell);
			this.renderReminder(view, bell);
			added.push(bell);
		}
		if (s.pinButton) {
			const pin = view.addAction("pin", "Pin", () => this.togglePin(view));
			pin.addClass("fkm-pin-button");
			this.pinButtons.set(view, pin);
			this.renderPin(view, pin);
			added.push(pin);
		}
		if (s.undoButtons) {
			const redo = view.addAction("redo-2", "Redo", () => view.editor?.redo());
			const undo = view.addAction("undo-2", "Undo", () => view.editor?.undo());
			redo.addClass("fkm-redo-button");
			undo.addClass("fkm-undo-button");
			added.push(redo, undo);
		}
		added.forEach(button => this.headerButtons.add(button));
		view.register(() => {
			added.forEach(button => this.headerButtons.delete(button));
			this.pinButtons.delete(view);
			this.archiveButtons.delete(view);
			this.reminderButtons.delete(view);
			delete view.fullKeepModeButtons;
		});
	}

	// Bring all top-bar buttons of views showing `file` (or all views) up to date.
	renderButtons(file = null) {
		for (const [view, button] of this.pinButtons) if (!file || view.file === file) this.renderPin(view, button);
		for (const [view, button] of this.archiveButtons) if (!file || view.file === file) this.renderArchive(view, button);
		for (const [view, button] of this.reminderButtons) if (!file || view.file === file) this.renderReminder(view, button);
	}

	// ----- archive --------------------------------------------------------------------------

	isArchived(file) {
		if (!file) return false;
		const value = this.frontmatterOf(file)[ARCHIVE_PROPERTY];
		if (value === true || value === "true") return true;
		const tags = obsidian.getAllTags(this.app.metadataCache.getFileCache(file) ?? {}) ?? [];
		return tags.some(tag => tag.toLowerCase() === `#${ARCHIVE_TAG}`);
	}

	renderArchive(view, button) {
		const archived = this.isArchived(view.file);
		button.toggleClass("is-archived", archived);
		button.setAttribute("aria-label", archived ? "Unarchive" : "Archive");
		obsidian.setIcon(button, archived ? "archive-restore" : "archive");
	}

	// Like Keep: archive or unarchive, with "Undo" in the confirmation.
	async toggleArchive(view) {
		const file = view.file;
		if (!file || file.extension !== "md") return;
		const archive = !this.isArchived(file);
		await this.setArchived(file, archive);
		const fragment = createFragment(f => {
			f.appendText(archive ? "Note archived. " : "Note unarchived. ");
			const undo = f.createEl("a", { text: "Undo", href: "#" });
			undo.addEventListener("click", event => {
				event.preventDefault();
				void this.setArchived(file, !archive);
			});
		});
		new obsidian.Notice(fragment, 6000);
	}

	async setArchived(file, archive) {
		if (archive) {
			await this.app.fileManager.processFrontMatter(file, fm => {
				fm[ARCHIVE_PROPERTY] = true;
			});
			return;
		}
		await this.app.fileManager.processFrontMatter(file, fm => {
			delete fm[ARCHIVE_PROPERTY];
			if (Array.isArray(fm.tags)) {
				fm.tags = fm.tags.filter(tag => String(tag).replace(/^#/, "").toLowerCase() !== ARCHIVE_TAG);
				if (!fm.tags.length) delete fm.tags;
			}
		});
		// The tag may also be written in the note itself (e.g. by an import): remove it there too.
		// A line that held only the tag goes away.
		const tag = new RegExp(`(^|[ \\t])#${ARCHIVE_TAG}(?=\\s|$)`, "gi");
		await this.app.vault.process(file, text => text.split("\n").flatMap(line => {
			if (!line.match(tag)) return [line];
			const rest = line.replace(tag, "$1").trimEnd();
			return rest.trim() ? [rest] : [];
		}).join("\n"));
	}

	// ----- reminders --------------------------------------------------------------------------

	reminderOf(file) {
		const value = this.frontmatterOf(file)[REMINDER_PROPERTY];
		if (!value) return null;
		const time = obsidian.moment(String(value));
		return time.isValid() ? time : null;
	}

	renderReminder(view, button) {
		const time = this.reminderOf(view.file);
		button.toggleClass("has-reminder", !!time);
		button.setAttribute("aria-label", time ? `Reminder: ${time.format("ddd D MMM, HH:mm")}` : "Remind me");
		obsidian.setIcon(button, time ? "bell-ring" : "bell");
	}

	async setReminder(file, time) {
		await this.app.fileManager.processFrontMatter(file, fm => {
			if (time) fm[REMINDER_PROPERTY] = time.format("YYYY-MM-DDTHH:mm");
			else delete fm[REMINDER_PROPERTY];
		});
		// A changed reminder may fire again.
		delete this.settings.firedReminders[file.path];
		await this.saveData(this.settings);
	}

	// Show every reminder that is due and hasn't been shown yet. Called every
	// 20 seconds while Obsidian runs, and once at start (catching up on any that
	// fell due while Obsidian was closed).
	async checkReminders(atStart = false) {
		if (!this.settings.reminders) return;
		const now = obsidian.moment();
		const fired = this.settings.firedReminders;
		const due = [];
		for (const file of this.app.vault.getMarkdownFiles()) {
			const time = this.reminderOf(file);
			if (!time || time.isAfter(now)) continue;
			const key = time.format("YYYY-MM-DDTHH:mm");
			if (fired[file.path] === key) continue;
			fired[file.path] = key;
			due.push({ file, time });
		}
		if (!due.length) return;
		await this.saveData(this.settings);
		for (const { file, time } of due) this.showReminder(file, time, atStart || now.diff(time, "minutes") > 2);
	}

	showReminder(file, time, missed) {
		const title = file.basename;
		const fragment = createFragment(f => {
			f.createEl("b", { text: missed ? "Missed reminder" : "Reminder" });
			f.appendText(` (${time.format("ddd D MMM, HH:mm")}): ${title} `);
			const open = f.createEl("a", { text: "Open", href: "#" });
			open.addEventListener("click", event => {
				event.preventDefault();
				void this.app.workspace.getLeaf(false).openFile(file);
			});
		});
		new obsidian.Notice(fragment, 0); // stays until clicked away, like a Keep reminder
		// A system notification too, on desktop (also when Obsidian is in the background).
		if (!obsidian.Platform.isMobile && typeof Notification !== "undefined") {
			const show = () => new Notification(missed ? "Missed reminder" : "Reminder", { body: title });
			if (Notification.permission === "granted") show();
			else if (Notification.permission !== "denied") void Notification.requestPermission().then(p => p === "granted" && show());
		}
	}

	// ----- pin and colour -----------------------------------------------------------------

	frontmatterOf(file) {
		return file ? this.app.metadataCache.getFileCache(file)?.frontmatter ?? {} : {};
	}

	isPinned(file) {
		const value = this.frontmatterOf(file)[PIN_PROPERTY];
		return value === true || value === "true";
	}

	renderPin(view, button) {
		const pinned = this.isPinned(view.file);
		button.toggleClass("is-pinned", pinned);
		button.setAttribute("aria-label", pinned ? "Unpin" : "Pin");
		obsidian.setIcon(button, pinned ? "pin-off" : "pin");
	}

	async togglePin(view) {
		const file = view.file;
		if (!file || file.extension !== "md") return;
		const pinned = this.isPinned(file);
		await this.app.fileManager.processFrontMatter(file, fm => {
			if (pinned) delete fm[PIN_PROPERTY];
			else fm[PIN_PROPERTY] = true;
		});
		new obsidian.Notice(pinned ? "Unpinned" : "Pinned");
	}

	showColorMenu(view, event) {
		const file = view.file;
		if (!file || file.extension !== "md") return;
		const current = this.frontmatterOf(file)[COLOR_PROPERTY] ?? null;
		const menu = new obsidian.Menu();
		for (const color of COLORS) {
			menu.addItem(item => {
				item.setTitle(color.name)
					.setChecked(color.id === current)
					.onClick(() => this.setColor(file, color.id));
				const icon = item.dom?.querySelector?.(".menu-item-icon");
				if (icon) {
					obsidian.setIcon(icon, "circle");
					icon.addClass("fkm-color-swatch");
					if (color.hex) icon.style.setProperty("--fkm-swatch", color.hex);
				}
			});
		}
		if (event instanceof MouseEvent) menu.showAtMouseEvent(event);
		else menu.showAtPosition({ x: 0, y: 0 });
	}

	async setColor(file, colorId) {
		await this.app.fileManager.processFrontMatter(file, fm => {
			if (colorId) fm[COLOR_PROPERTY] = colorId;
			else delete fm[COLOR_PROPERTY];
		});
	}

	// One-off: move ticked items down in every checklist of the current note.
	sortNote(cm) {
		if (!cm) return;
		const unit = indentUnit(this.app);
		// Bottom-up, so earlier lists' line numbers stay valid.
		const blocks = findBlocks(cm.state.doc, unit).reverse();
		let changed = 0;
		for (const block of blocks) {
			if (writeItems(cm, block, sinkItems(block.items.map(item => ({ ...item }))), unit)) changed++;
		}
		new obsidian.Notice(changed ? `Moved ticked items down in ${changed} list${changed === 1 ? "" : "s"}.` : "Nothing to move.");
	}

	// Drag an item by its grip: up/down to move it, sideways to indent/outdent.
	// Like Keep: an item carries its sub-items along; dropped at the top level
	// below another item, it lands after that item's sub-items; moved out in
	// place, the sub-items below it become its own; indented, it and its
	// sub-items become sub-items of the item above (two levels).
	startItemDrag(view, grip, event) {
		if (event.pointerType === "mouse" && event.button !== 0) return;
		event.preventDefault();
		event.stopPropagation();
		const unit = indentUnit(this.app);
		const doc = view.state.doc;
		const line = doc.lineAt(view.posAtDOM(grip));
		const block = findBlock(doc, line.number, unit);
		if (!block) return;
		const items = block.items;
		const index = items.findIndex(item => item.line === line.number);
		if (index < 0) return;
		const unitEnd = descendantsEnd(items, index); // the item plus its sub-items
		const base = baseDepth(items);
		const rest = [...items.slice(0, index), ...items.slice(unitEnd)];
		const original = doc.sliceString(doc.line(block.fromLine).from, doc.line(block.toLine).to);
		const startX = event.clientX;
		const indicator = document.body.createDiv({ cls: "fkm-drop-indicator" });
		grip.closest(".cm-line")?.addClass("fkm-item-dragging");
		let drop = null;

		const itemAtLine = n => {
			let i = 0;
			while (i + 1 < items.length && items[i + 1].line <= n) i++;
			return i;
		};

		const onMove = e => {
			e.preventDefault();
			const state = view.state;
			const pos = view.posAtCoords({ x: e.clientX, y: e.clientY }, false);
			const n = Math.max(block.fromLine, Math.min(block.toLine, state.doc.lineAt(pos).number));
			const over = itemAtLine(n);
			const lastLine = over + 1 < items.length ? items[over + 1].line - 1 : block.toLine;
			const top = view.documentTop + view.lineBlockAt(state.doc.line(items[over].line).from).top;
			const bottom = view.documentTop + view.lineBlockAt(state.doc.line(lastLine).from).bottom;
			const after = e.clientY > (top + bottom) / 2;
			let insertAt = over + (after ? 1 : 0);
			if (insertAt > index && insertAt <= unitEnd) insertAt = index; // onto itself: indent only
			const inPlace = insertAt === index;
			const restInsert = insertAt <= index ? insertAt : insertAt - (unitEnd - index);
			const prev = rest[restInsert - 1];
			const shift = Math.round((e.clientX - startX) / INDENT_STEP);
			const depth = Math.max(base, Math.min(this.maxDepth(base, prev), items[index].depth + shift));
			// Dropped somewhere else: never take another item's sub-items away.
			let landAt = restInsert;
			if (!inPlace) while (landAt < rest.length && rest[landAt].depth > depth) landAt++;
			drop = { landAt, depth };
			let lineY = after ? bottom : top;
			if (landAt !== restInsert) {
				lineY = landAt < rest.length
					? view.documentTop + view.lineBlockAt(state.doc.line(rest[landAt].line).from).top
					: view.documentTop + view.lineBlockAt(state.doc.line(block.toLine).from).bottom;
			}
			const content = view.contentDOM.getBoundingClientRect();
			const indentPx = (depth - base) * INDENT_STEP;
			indicator.style.top = `${lineY}px`;
			indicator.style.left = `${content.left + indentPx}px`;
			indicator.style.width = `${Math.max(40, content.width - indentPx)}px`;
			indicator.addClass("is-visible");
		};

		const finish = e => {
			grip.removeEventListener("pointermove", onMove);
			grip.removeEventListener("pointerup", finish);
			grip.removeEventListener("pointercancel", finish);
			indicator.remove();
			view.dom.querySelectorAll(".fkm-item-dragging").forEach(el => el.removeClass("fkm-item-dragging"));
			if (e.type !== "pointerup" || !drop) return;
			const now = view.state.doc;
			if (block.toLine > now.lines) return;
			if (now.sliceString(now.line(block.fromLine).from, now.line(block.toLine).to) !== original) return;
			const moved = items.slice(index, unitEnd).map(item => ({ ...item }));
			const shiftBy = drop.depth - moved[0].depth;
			const cap = this.depthCap(base);
			// The item gets the new level; its sub-items stay below it, but never deeper
			// than allowed (with two levels they all become sub-items of the same item).
			moved.forEach((item, i) => {
				item.depth = i === 0 ? drop.depth : Math.min(Math.max(item.depth + shiftBy, drop.depth + 1), cap);
			});
			const others = rest.map(item => ({ ...item }));
			const next = [...others.slice(0, drop.landAt), ...moved, ...others.slice(drop.landAt)];
			writeItems(view, block, this.settings.sinkTicked ? sinkItems(next) : next, unit);
		};

		grip.setPointerCapture(event.pointerId);
		grip.addEventListener("pointermove", onMove);
		grip.addEventListener("pointerup", finish);
		grip.addEventListener("pointercancel", finish);
	}

	// ----- the board (Keep Bases View) ------------------------------------------------------

	enhanceBoards() {
		const s = this.settings;
		this.app.workspace.containerEl.querySelectorAll(".kg-container").forEach(container => {
			const bar = container.querySelector(":scope > .fkm-take-note");
			if (s.takeANote && !bar) {
				const el = createDiv({ cls: "fkm-take-note" });
				obsidian.setIcon(el.createSpan({ cls: "fkm-take-note-icon" }), "plus");
				el.createSpan({ text: "Take a note…" });
				el.addEventListener("click", () => this.newNote());
				container.prepend(el);
			} else if (!s.takeANote && bar) {
				bar.remove();
			}
			if (s.dragCards && !container.fullKeepModeWired) {
				container.fullKeepModeWired = true;
				if (obsidian.Platform.isMobile) this.wireTouchDrag(container);
				else this.wireMouseDrag(container);
			}
		});
	}

	// A board listener that is removed again when the plugin unloads.
	listenOn(el, type, handler, options) {
		el.addEventListener(type, handler, options);
		this.boardListeners.push(() => el.removeEventListener(type, handler, options));
	}

	// A card being dragged: a copy of it follows the pointer, the card under the
	// pointer is highlighted, and dropping returns that card's note.
	cardDrag(container, card, x, y) {
		const rect = card.getBoundingClientRect();
		const grab = { x: x - rect.left, y: y - rect.top };
		const ghost = card.cloneNode(true);
		ghost.removeAttribute("data-path"); // never a drop target
		ghost.removeAttribute("style"); // drop the board's own positioning
		ghost.className = card.className;
		ghost.removeClass("fkm-lifted", "fkm-dragging", "fkm-drop-target");
		ghost.addClass("fkm-drag-ghost");
		ghost.style.width = `${rect.width}px`;
		ghost.style.height = `${rect.height}px`;
		document.body.appendChild(ghost);
		document.body.addClass("fkm-card-drag-active"); // no text selection while dragging
		card.removeClass("fkm-lifted");
		card.addClass("fkm-dragging");
		let over = null;
		const EDGE = 60; // px from the board's top/bottom edge that scrolls while dragging
		const drag = {
			move: (px, py) => {
				ghost.style.transform = `translate(${px - grab.x}px, ${py - grab.y}px) rotate(2deg)`;
				const target = document.elementFromPoint(px, py)?.closest?.(".kg-card[data-path]") ?? null;
				if (target !== over) {
					over?.removeClass("fkm-drop-target");
					over = target && target !== card ? target : null;
					over?.addClass("fkm-drop-target");
				}
				const box = container.getBoundingClientRect();
				if (py < box.top + EDGE) container.scrollTop -= 12;
				else if (py > box.bottom - EDGE) container.scrollTop += 12;
			},
			end: () => {
				ghost.remove();
				document.body.removeClass("fkm-card-drag-active");
				card.removeClass("fkm-dragging");
				over?.removeClass("fkm-drop-target");
				return over?.getAttribute("data-path") ?? null;
			},
		};
		drag.move(x, y);
		return drag;
	}

	// Mouse: press on a card and move it a little to start dragging; a click
	// without moving still opens the note.
	wireMouseDrag(container) {
		const THRESHOLD = 6;
		let pressed = null; // { card, x, y }
		let drag = null;
		let swallowClick = false;
		const onMove = event => {
			if (!pressed) return;
			if (!drag) {
				if (Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) < THRESHOLD) return;
				drag = this.cardDrag(container, pressed.card, event.clientX, event.clientY);
			}
			event.preventDefault();
			drag.move(event.clientX, event.clientY);
		};
		const onUp = () => {
			document.removeEventListener("pointermove", onMove, true);
			document.removeEventListener("pointerup", onUp, true);
			if (drag) {
				const from = pressed.card.getAttribute("data-path");
				const target = drag.end();
				swallowClick = true; // the click that follows a drag must not open the note
				setTimeout(() => { swallowClick = false; }, 0);
				if (target && target !== from) void this.moveNote(from, target);
			}
			pressed = null;
			drag = null;
		};
		this.listenOn(container, "pointerdown", event => {
			if (event.pointerType !== "mouse" || event.button !== 0) return;
			const card = event.target?.closest?.(".kg-card[data-path]");
			if (!card || event.target.closest("a, button, input, .kg-card-actions, .kg-pin-btn")) return;
			pressed = { card, x: event.clientX, y: event.clientY };
			document.addEventListener("pointermove", onMove, true);
			document.addEventListener("pointerup", onUp, true);
		});
		this.listenOn(container, "click", event => {
			if (!swallowClick) return;
			event.preventDefault();
			event.stopPropagation();
		}, { capture: true });
		// Cards must not start the browser's own drag (images, selected text).
		this.listenOn(container, "dragstart", event => {
			if (pressed) event.preventDefault();
		}, { capture: true });
	}

	// Touch: hold a card, then drag it. Holding and letting go without moving opens
	// the card's menu (Pin, Change colour, Delete); a quick swipe still scrolls.
	wireTouchDrag(container) {
		const HOLD_MS = 350;
		const TOLERANCE = 10;
		let card = null;
		let start = null;
		let timer = null;
		let armed = false;
		let drag = null;
		let replayingMenu = false;
		const reset = () => {
			clearTimeout(timer);
			timer = null;
			card?.removeClass("fkm-lifted");
			drag?.end();
			drag = null;
			card = null;
			start = null;
			armed = false;
		};

		this.listenOn(container, "touchstart", event => {
			reset();
			if (event.touches.length !== 1) return;
			const touched = event.target?.closest?.(".kg-card[data-path]");
			if (!touched) return;
			card = touched;
			start = { x: event.touches[0].clientX, y: event.touches[0].clientY };
			timer = setTimeout(() => {
				armed = true;
				card?.addClass("fkm-lifted");
			}, HOLD_MS);
		}, { passive: true });

		this.listenOn(container, "touchmove", event => {
			if (!card) return;
			const touch = event.touches[0];
			if (!armed) {
				// Moved before the hold finished: it's a scroll, not a drag.
				if (Math.hypot(touch.clientX - start.x, touch.clientY - start.y) > TOLERANCE) reset();
				return;
			}
			event.preventDefault(); // stop the board scrolling under the finger
			if (!drag) drag = this.cardDrag(container, card, touch.clientX, touch.clientY);
			drag.move(touch.clientX, touch.clientY);
		}, { passive: false });

		this.listenOn(container, "touchend", event => {
			if (!card) return;
			const held = card;
			const from = held.getAttribute("data-path");
			const at = start;
			if (drag) {
				event.preventDefault(); // no tap on the card after a drag
				const target = drag.end();
				drag = null;
				reset();
				if (target && target !== from) void this.moveNote(from, target);
			} else if (armed) {
				// Held without moving: open the card's usual menu.
				event.preventDefault();
				reset();
				replayingMenu = true;
				held.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: at.x, clientY: at.y }));
				replayingMenu = false;
			} else {
				reset();
			}
		}, { passive: false });

		this.listenOn(container, "touchcancel", reset);

		// While a card is held, keep the system's own long-press menu away;
		// the card menu is shown on release instead.
		this.listenOn(container, "contextmenu", event => {
			if (replayingMenu || !card) return;
			event.preventDefault();
			event.stopPropagation();
		}, { capture: true });
	}

	// The board sorts by keep_order, or the creation time for notes without one
	// (see BOARD_BASE). A moved note gets a value between the target and the
	// target's neighbour on the far side, so it lands in the target's place.
	boardOrder(file) {
		const value = Number(this.frontmatterOf(file)[ORDER_PROPERTY]);
		return value ? value : file.stat.ctime;
	}

	async moveNote(fromPath, targetPath) {
		const from = this.app.vault.getAbstractFileByPath(fromPath);
		const target = this.app.vault.getAbstractFileByPath(targetPath);
		if (!(from instanceof obsidian.TFile) || !(target instanceof obsidian.TFile)) return;
		const pinned = this.isPinned(target);
		if (this.isPinned(from) !== pinned) {
			new obsidian.Notice("Use the pin to move a note between Pinned and Others.");
			return;
		}
		const list = this.app.vault.getMarkdownFiles()
			.filter(f => f !== from && this.isPinned(f) === pinned)
			.map(f => ({ file: f, order: this.boardOrder(f) }))
			.sort((a, b) => b.order - a.order);
		const index = list.findIndex(item => item.file === target);
		if (index < 0) return;
		const targetOrder = list[index].order;
		const movingDown = this.boardOrder(from) > targetOrder;
		const neighbour = movingDown ? list[index + 1] : list[index - 1];
		const value = neighbour ? (targetOrder + neighbour.order) / 2 : targetOrder + (movingDown ? -1000 : 1000);
		if (value === targetOrder || value === neighbour?.order) {
			new obsidian.Notice("Couldn't place the note there.");
			return;
		}
		await this.app.fileManager.processFrontMatter(from, fm => {
			fm[ORDER_PROPERTY] = value;
		});
	}

	// ----- new notes and the board command ---------------------------------------------------

	async newNote() {
		const parent = this.app.fileManager.getNewFileParent("");
		// Obsidian's own "Untitled" (in the app's language), where available.
		const file = typeof this.app.fileManager.createNewMarkdownFile === "function"
			? await this.app.fileManager.createNewMarkdownFile(parent)
			: await this.app.vault.create(obsidian.normalizePath(`${parent.path}/Untitled ${Date.now()}.md`), "");
		new NewNoteModal(this.app, file).open();
	}

	async createBoard() {
		if (!this.app.plugins?.manifests?.[KEEP_VIEW_PLUGIN]) {
			new obsidian.Notice("The board needs the \"Keep Bases View\" plugin: install it under Settings → Community plugins → Browse.", 10000);
			return;
		}
		let path = "Keep board.base";
		for (let i = 2; this.app.vault.getAbstractFileByPath(path); i++) path = `Keep board ${i}.base`;
		const file = await this.app.vault.create(path, BOARD_BASE);
		await this.app.workspace.getLeaf(false).openFile(file);
	}
};

// A new note in the same pop-up Keep Bases View opens when you click a card (it
// styles .kg-edit-modal), with the title selected so you can type it straight
// away. Closed untouched (no text, title unchanged), the note is thrown away.
class NewNoteModal extends obsidian.Modal {
	constructor(app, file) {
		super(app);
		this.file = file;
		this.createdName = file.basename;
		this.leaf = null;
	}

	async onOpen() {
		this.modalEl.addClass("kg-edit-modal", "fkm-new-note-modal");
		const width = this.app.plugins?.plugins?.[KEEP_VIEW_PLUGIN]?.settings?.popupWidth || 800;
		this.modalEl.style.setProperty("max-width", `${width}px`, "important");
		this.contentEl.empty();
		try {
			const WorkspaceLeaf = this.app.workspace.getLeaf(false).constructor;
			this.leaf = new WorkspaceLeaf(this.app);
			this.contentEl.appendChild(this.leaf.containerEl);
			await this.leaf.openFile(this.file, { state: { mode: "source" }, eState: { rename: "all" } });
		} catch (err) {
			console.error("[Full Keep Mode] Couldn't open the new note:", err);
			this.contentEl.createEl("p", { text: "Couldn't open the editor." });
		}
	}

	async onClose() {
		this.leaf?.detach();
		this.leaf = null;
		this.contentEl.empty();
		const file = this.app.vault.getAbstractFileByPath(this.file.path);
		if (file instanceof obsidian.TFile && file.basename === this.createdName) {
			const text = await this.app.vault.read(file);
			if (text.trim() === "") await this.app.fileManager.trashFile(file);
		}
	}
}

// The bell's pop-up: quick picks like Keep's, a date and time field, and "Remove".
class ReminderModal extends obsidian.Modal {
	constructor(plugin, file) {
		super(plugin.app);
		this.plugin = plugin;
		this.file = file;
	}

	onOpen() {
		const { contentEl, plugin, file } = this;
		this.modalEl.addClass("fkm-reminder-modal");
		this.titleEl.setText("Remind me");
		const current = plugin.reminderOf(file);
		const now = obsidian.moment();
		const set = async time => {
			await plugin.setReminder(file, time);
			this.close();
			new obsidian.Notice(time ? `Reminder set: ${time.format("ddd D MMM, HH:mm")}` : "Reminder removed");
		};

		const later = now.clone().hour(20).minute(0).second(0); // Keep: 8 PM
		const picks = [
			now.hour() < 19 ? ["Later today", later] : null,
			["Tomorrow", now.clone().add(1, "day").hour(8).minute(0).second(0)],
			["Next week", now.clone().add(1, "week").startOf("isoWeek").hour(8).minute(0).second(0)],
		].filter(Boolean);
		const list = contentEl.createDiv({ cls: "fkm-reminder-picks" });
		for (const [label, time] of picks) {
			const row = list.createEl("button", { cls: "fkm-reminder-pick" });
			row.createSpan({ text: label });
			row.createSpan({ cls: "fkm-reminder-pick-time", text: time.format("ddd HH:mm") });
			row.addEventListener("click", () => void set(time));
		}

		const custom = contentEl.createDiv({ cls: "fkm-reminder-custom" });
		const input = custom.createEl("input", { type: "datetime-local" });
		input.value = (current ?? now.clone().add(1, "hour").startOf("hour")).format("YYYY-MM-DDTHH:mm");
		const save = custom.createEl("button", { cls: "mod-cta", text: "Save" });
		save.addEventListener("click", () => {
			const time = obsidian.moment(input.value, "YYYY-MM-DDTHH:mm", true);
			if (time.isValid()) void set(time);
		});

		if (current) {
			const remove = contentEl.createEl("button", { cls: "fkm-reminder-remove mod-warning", text: "Remove reminder" });
			remove.addEventListener("click", () => void set(null));
		}
	}

	onClose() {
		this.contentEl.empty();
	}
}
