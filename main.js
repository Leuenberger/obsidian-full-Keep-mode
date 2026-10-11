/*
 * Keep-style Checklists - checklists that behave like Google Keep's.
 *
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
};

// A note can opt out with this property set to false.
const OPT_OUT_PROPERTY = "keep-style-checklists";
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
			const el = createSpan({ cls: "tc-grip" });
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
			return createSpan({ cls: `tc-extra-spacer tc-depth-${this.depth}` });
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
			const el = createDiv({ cls: "tc-ticked-section" });
			el.createDiv({ cls: "tc-ticked-label", text: `${this.count} ticked item${this.count === 1 ? "" : "s"}` });
			for (const ghost of this.ghosts) {
				const group = el.createDiv({ cls: "tc-ghost-group" });
				const parent = group.createDiv({ cls: "tc-ghost-item tc-ghost-parent" });
				parent.createEl("input", { type: "checkbox", cls: "task-list-item-checkbox" }).disabled = true;
				parent.createSpan({ cls: "tc-ghost-text", text: plainText(ghost.parent) });
				for (const child of ghost.children) {
					const row = group.createDiv({ cls: "tc-ghost-item tc-ghost-child" });
					const box = row.createEl("input", { type: "checkbox", cls: "task-list-item-checkbox" });
					box.checked = true;
					box.setAttribute("aria-label", "Untick");
					box.addEventListener("click", event => {
						event.preventDefault();
						untick(view, child);
					});
					row.createSpan({ cls: "tc-ghost-text", text: plainText(child.text) });
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
				decos.push(Decoration.line({ class: `tc-task tc-depth-${depth}` }).range(head.from));
				// Extra lines: keep the item's own indentation (and its guide line),
				// replace the rest of the leading whitespace by a spacer.
				for (let k = 1; k <= item.extra.length; k++) {
					const line = doc.line(item.line + k);
					if (isBlank(line.text)) continue;
					const lead = line.text.match(/^[ \t]*/)[0];
					const keep = Math.min(item.indent.length, lead.length);
					const keepOk = lead.slice(0, keep) === item.indent.slice(0, keep);
					const from = line.from + (keepOk ? keep : 0);
					decos.push(Decoration.line({ class: `tc-extra tc-depth-${depth}` }).range(line.from));
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
	// --tc-hang-N (padding / hanging indent) and --tc-spacer-N (spacer width).
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
						if (old.hang !== hang) v.dom.style.setProperty(`--tc-hang-${depth}`, `${hang}px`);
						if (spacer !== null && old.spacer !== spacer) v.dom.style.setProperty(`--tc-spacer-${depth}`, `${spacer}px`);
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
							const spacer = lineEl?.querySelector(".tc-extra-spacer");
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

	// Undo / redo buttons in the note's top bar (also in pop-up editors).
	const headerButtons = ViewPlugin.fromClass(class {
		constructor(view) {
			const info = obsidian.editorInfoField ? view.state.field(obsidian.editorInfoField, false) : null;
			if (info instanceof obsidian.MarkdownView) plugin.addHeaderButtons(info);
		}
	});

	return [decorations, onTick, hangMeasure, tabKey, headerButtons];
}

// ----- settings tab -------------------------------------------------------------------------

class KeepStyleChecklistsSettingTab extends obsidian.PluginSettingTab {
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
		toggle("Undo and redo buttons", "Buttons in the note's top bar (takes effect for newly opened notes).", "undoButtons");

		containerEl.createEl("p", {
			cls: "setting-item-description",
			text: `A note can opt out with the property "${OPT_OUT_PROPERTY}: false". `
				+ "Tip: turn off Settings → Editor → \"Fold indent\" if you don't want items to be collapsible, like in Keep.",
		});
	}
}

// ----- the plugin ---------------------------------------------------------------------------

module.exports = class KeepStyleChecklistsPlugin extends obsidian.Plugin {
	async onload() {
		await this.loadSettings();
		this.headerButtons = new Set();
		this.registerEditorExtension(checklistExtension(this));
		this.addSettingTab(new KeepStyleChecklistsSettingTab(this.app, this));

		this.addCommand({
			id: "sort-ticked-items",
			name: "Move ticked items down in this note",
			editorCallback: editor => this.sortNote(editor.cm),
		});
	}

	onunload() {
		this.headerButtons.forEach(button => button.remove());
		this.headerButtons.clear();
		document.querySelectorAll(".tc-drop-indicator").forEach(el => el.remove());
	}

	async loadSettings() {
		this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
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

	addHeaderButtons(view) {
		if (!this.settings.undoButtons || view.keepStyleChecklistsButtons) return;
		// addAction puts each new button in front, so this reads: undo, redo.
		const redo = view.addAction("redo-2", "Redo", () => view.editor?.redo());
		const undo = view.addAction("undo-2", "Undo", () => view.editor?.undo());
		redo.addClass("tc-redo-button");
		undo.addClass("tc-undo-button");
		view.keepStyleChecklistsButtons = true;
		this.headerButtons.add(undo);
		this.headerButtons.add(redo);
		view.register(() => {
			this.headerButtons.delete(undo);
			this.headerButtons.delete(redo);
			delete view.keepStyleChecklistsButtons;
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
		const indicator = document.body.createDiv({ cls: "tc-drop-indicator" });
		grip.closest(".cm-line")?.addClass("tc-item-dragging");
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
			view.dom.querySelectorAll(".tc-item-dragging").forEach(el => el.removeClass("tc-item-dragging"));
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
};
