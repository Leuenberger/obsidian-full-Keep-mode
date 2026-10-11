# Full Keep Mode for Obsidian

An [Obsidian](https://obsidian.md) plugin that brings the Google Keep
experience to Obsidian: a board of coloured cards, pinned notes, quick notes,
and checklists that tidy themselves up the way Keep's do.

![Ticking items, a ghost parent, dragging and indenting](docs/demo.gif)

## Features

### Notes and the board

- **Pin and colour buttons** in every note's top bar, in tabs and in the
  board's pop-up. Pinned notes come first on the board.
- **"Take a note…"** at the top of the board opens a new note in a pop-up, title
  ready to type. Close it without writing anything and it's thrown away, like in
  Keep.
- **Drag cards** to reorder the board: with the mouse, or hold a card and drag
  it on a phone or tablet. A dragged card takes the place of the card you drop
  it on.
- **"Create a Keep board"** sets up a ready-made board: newest notes first,
  pinned ones on top, archived notes (`#archived`) left out.

The board itself is drawn by the
[Keep Bases View](https://github.com/k4fn/keep-bases-view) plugin;
Full Keep Mode adds the rest. Both use the same note properties, `keep_pinned`
and `keep_color`. A note's place on the board is stored in `keep_order`.

### Checklists

- **Ticked items move down** below a "*N* ticked items" divider. Untick one and
  it moves back up.
- **Ghost parents.** Tick a sub-item of an item that isn't done yet, and it
  shows in the ticked section under a faded copy of its parent, like in Keep.
  The note itself keeps it under its parent.
- **Ticking an item ticks its sub-items** along with it.
- **Drag and drop.** Every item has a grip next to its checkbox. Drag it up or
  down to move the item, sideways to indent or outdent it, with a mouse or a
  finger. An item takes its sub-items along.
- **Two levels, like Keep.** An item can be indented once. You can allow three
  levels or unlimited in the settings.
- **Multi-line items line up.** Extra lines of an item (Shift+Enter) and
  wrapped lines start exactly under the item's text.
- **Undo and redo buttons** in the note's top bar. Ticking an item and its move
  to the bottom are one step, so one undo restores the list.

Everything is **plain Markdown**: properties in the note's front matter and
ordinary `- [ ]` / `- [x]` lists. Nothing is stored anywhere else.

## How the checklist rules work

| You do | Result |
|---|---|
| Tick an item | It moves below the divider, with its sub-items |
| Tick a sub-item | It shows under a ghost of its parent in the ticked section |
| Drag an item onto another place | It moves there with its sub-items. Dropped at the top level below an item that has sub-items, it lands after them. |
| Drag a sub-item out to the top level, in place | The sub-items below it become its own |
| Drag an item to the right, or press Tab | It's indented under the item above, sub-items included (still two levels) |
| Tab on an indented item, or on the first item | Nothing; there are only two levels |

## Getting started

1. Install **Full Keep Mode** and **Keep Bases View** (Settings → Community
   plugins → Browse) and enable both.
2. Run the command **Create a Keep board** (Ctrl/Cmd+P).
3. Optional, to match Keep: turn off **Settings → Editor → Fold indent**, so
   list items can't be collapsed.

The checklist features work in any note, with or without the board.

## Settings

| Setting | Default |
|---|---|
| Pin button | on |
| Colour button | on |
| "Take a note…" bar | on |
| Drag cards | on |
| Move ticked items down | on |
| Ticked sub-items under a ghost parent | on |
| Tick sub-items along | on |
| Drag handles (checklists) | on |
| Indent levels | Two levels, like Google Keep |
| Line up multi-line items | on |
| Undo and redo buttons | on |

To keep the checklist features out of a single note, give it the property
`full-keep-mode: false`.

Commands: **Take a note**, **Create a Keep board**, and **Move ticked items
down in this note** (tidies up a list that already has ticked items in between).

## Installation

From Obsidian: **Settings → Community plugins → Browse**, search for
"Full Keep Mode", install and enable.

Manually: download `main.js`, `manifest.json` and `styles.css` from the
[latest release](../../releases/latest) into
`<your vault>/.obsidian/plugins/full-keep-mode/`, then enable the plugin under
**Settings → Community plugins**.

## Limitations

- Checklists work in the editor (Live Preview and Source mode), not in Reading
  view.
- On phones, Obsidian's own indent button in the toolbar isn't limited to two
  levels; Tab and dragging are.
- Not yet: reminders, labels on the board, archiving from a note.

## Development

There's no build step: `main.js` is the plugin as it ships.

The tests in `tests/live_test.py` run against a real Obsidian. They create
temporary notes and a temporary board, tick, drag with real mouse events, press
Tab, pin, colour and take notes, and check the results:

```bash
# Start Obsidian with its debugging port (close it first). Windows:
"%LOCALAPPDATA%\Programs\Obsidian\Obsidian.exe" --remote-debugging-port=9222
# macOS:
open -a Obsidian --args --remote-debugging-port=9222

pip install websocket-client pillow
python tests/live_test.py      # the tests (keep the Obsidian window visible)
python tests/record_demo.py    # re-records docs/demo.gif
```

## License

[MIT](LICENSE)
