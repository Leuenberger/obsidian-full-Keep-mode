# Full Keep Mode for Obsidian

An [Obsidian](https://obsidian.md) plugin: checklists that behave like Google Keep's: ticked items get out of
the way, items can be dragged around and indented with a mouse or a finger, and
long items stay neatly lined up.

![Ticking items, a ghost parent, dragging and indenting](docs/demo.gif)

## Features

- **Ticked items move down** below a "*N* ticked items" divider. Untick one and
  it moves back up.
- **Ghost parents.** Tick a sub-item of an item that isn't done yet, and it
  shows in the ticked section under a faded copy of its parent, like in Keep.
  The note itself keeps it under its parent.
- **Ticking an item ticks its sub-items** along with it.
- **Drag and drop.** Every item has a grip next to its checkbox. Drag it up or
  down to move the item, sideways to indent or outdent it. This works with a
  mouse and on touch screens (iPhone, iPad, Android). An item takes its
  sub-items along.
- **Two levels, like Keep.** An item can be indented once. You can allow three
  levels or unlimited in the settings.
- **Multi-line items line up.** Extra lines of an item (Shift+Enter) and
  wrapped lines start exactly under the item's text.
- **Undo and redo buttons** in the note's top bar. Ticking an item and its move
  to the bottom are one step, so one undo restores the list.
- **Plain Markdown.** Nothing is stored anywhere else: your notes stay ordinary
  `- [ ]` / `- [x]` lists that work everywhere.

## How the rules work

The plugin follows Google Keep's behaviour:

| You do | Result |
|---|---|
| Tick an item | It moves below the divider, with its sub-items |
| Tick a sub-item | It shows under a ghost of its parent in the ticked section |
| Drag an item onto another place | It moves there with its sub-items. Dropped at the top level below an item that has sub-items, it lands after them. |
| Drag a sub-item out to the top level, in place | The sub-items below it become its own |
| Drag an item to the right, or press Tab | It is indented under the item above, sub-items included (still two levels) |
| Tab on an indented item, or on the first item | Nothing; there are only two levels |

## Settings

| Setting | Default |
|---|---|
| Move ticked items down | on |
| Ticked sub-items under a ghost parent | on |
| Tick sub-items along | on |
| Drag handles | on |
| Indent levels | Two levels, like Google Keep |
| Line up multi-line items | on |
| Undo and redo buttons | on |

To leave a single note alone, give it the property `full-keep-mode: false`.

Tip: to make list items non-collapsible like in Keep, turn off
**Settings → Editor → Fold indent**.

There's also a command, **Move ticked items down in this note**, to tidy up
lists that already have ticked items in between.

## Installation

From Obsidian: **Settings → Community plugins → Browse**, search for
"Full Keep Mode", install and enable.

Manually: download `main.js`, `manifest.json` and `styles.css` from the
[latest release](../../releases/latest) into
`<your vault>/.obsidian/plugins/full-keep-mode/`, then enable the plugin under
**Settings → Community plugins**.

## Limitations

- It works in the editor (Live Preview and Source mode), not in Reading view.
- On phones, Obsidian's own indent button in the toolbar isn't limited to two
  levels; Tab and dragging are.

## Coming from Google Keep?

Google Keep's lists, Shift+Enter lines included, map directly onto this
plugin's checklists.

## Development

There is no build step: `main.js` is the plugin as it ships.

The tests in `tests/live_test.py` run against a real Obsidian. They create
temporary notes, tick, drag with real mouse events, press Tab and check the
results:

```bash
# Start Obsidian with its debugging port (close it first). Windows:
"%LOCALAPPDATA%\Programs\Obsidian\Obsidian.exe" --remote-debugging-port=9222
# macOS:
open -a Obsidian --args --remote-debugging-port=9222

pip install websocket-client pillow
python tests/live_test.py      # the tests
python tests/record_demo.py    # re-records docs/demo.gif
```

## License

[MIT](LICENSE)
