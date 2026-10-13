# Full Keep Mode for Obsidian

**It's just like Google Keep, but in [Obsidian](https://obsidian.md), with
your notes as plain Markdown files that you own.**

The board of coloured cards, pinned notes, labels, the archive, reminders,
"Take a note…", and Keep's checklists, where ticked items drop to the bottom and
sub-items follow their parent. If you know Keep, you already know how to use it.

**New to Obsidian and only ever used Keep?** This plugin is made for you. Install
it, import your Keep notes, and you're on a board that looks and works like the
one you're used to. No Markdown, folders or settings to learn first; the rest of
Obsidian is there whenever you want it.

![The Keep board: hovering a card, pinning, searching, ticking items on a card and in an open note, and dragging a card](docs/board.gif)

## Why Full Keep Mode

- **Just like Google Keep.** Same board, same cards, same colours, same pins
  and labels, same side menu, same checklists. On a phone too: notes open full
  screen with Keep's top and bottom bars.
- **Faster than Keep.** Everything is on your device, so the board opens,
  searches and filters instantly, with no loading and no waiting for a server.
  In daily use it feels quicker than Google Keep itself.
- **Your notes stay yours.** Every note is an ordinary Markdown file in your
  Obsidian vault: readable in any editor, synced however you like, and usable
  with everything else Obsidian can do (links, search, graph, other plugins).
- **Made for Obsidian's phone app.** On your phone, notes open full screen
  with Keep's top and bottom bars, cards and checklists work with your finger,
  and the side menu is the drawer, just like in Keep's app. With
  [Obsidian Sync](https://obsidian.md/sync), your board, pins, colours, labels
  and checklists stay the same on your phone and your computer.
- **Works offline,** always.
- **One plugin, nothing else to install.**

## Keep, feature by feature

| In Google Keep | In Full Keep Mode |
|---|---|
| Board of cards, "Pinned" and "Others" | ✓ Keep's cards in columns (two on phones), pinned first |
| Note colours | ✓ Keep's exact colours, light and dark; cards and open notes (top bar included) take the colour |
| Pin | ✓ on the card (hover) and in the note |
| Labels and the side menu (☰) | ✓ Notes, Reminders, your labels and Archive; label picker on every note |
| Search bar | ✓ always on top; finds titles, labels and text |
| "Take a note…" and "New list" | ✓ a note taken under a label gets that label |
| Archive, with Undo | ✓ archive view in the side menu |
| Reminders | ✓ Keep's choices (later today, tomorrow, next week) or any time |
| Drag cards to reorder | ✓ mouse, or hold and drag on a phone |
| Tick items on a card | ✓ |
| Checklists: ticked items move down, "*N* ticked items" | ✓ |
| Ticked sub-items under a faded copy of their parent | ✓ |
| Drag items up/down, sideways to indent; two levels | ✓ Keep's exact rules, including where sub-items go |
| Show / hide checkboxes | ✓ |
| Note opens over the board (full screen on phones) | ✓ with Keep's top and bottom bars on phones |
| Labels and "Edited …" below the note | ✓ |
| Your notes from Keep | ✓ imported with their order, colours, labels and checklist sub-items |

## Checklists, just like Keep's

![Ticking items, a ghost parent, dragging and indenting](docs/demo.gif)

- **Ticked items move down** below a "*N* ticked items" divider. Untick one and
  it moves back up.
- **Ghost parents.** Tick a sub-item of an item that isn't done yet, and it
  shows in the ticked section under a faded copy of its parent, like in Keep.
  The note itself keeps it under its parent.
- **Ticking an item ticks its sub-items** along with it.
- **Drag and drop.** Every item has a grip. Drag it up or down to move the
  item, sideways to indent or outdent it, with a mouse or a finger. An item
  takes its sub-items along. Like in Keep, a sub-item's grip is right below its
  parent's checkbox.
- **Two levels, like Keep.** An item can be indented once. You can allow three
  levels or unlimited in the settings.
- **Multi-line items line up.** Extra lines of an item (Shift+Enter) and
  wrapped lines start exactly under the item's text.
- **Pasting works like Keep.** Paste several lines into an item and they line
  up as its lines; pasted items stay items, whatever indentation they had.
- **Checkboxes stay checkboxes.** The cursor never lands inside `- [ ]`, and
  a selection doesn't turn checkboxes back into brackets. Backspace at the
  start of an item joins it to the item above, Delete at the end of an item
  joins the next one, like in Keep.
- **Undo and redo buttons.** Ticking an item and its move to the bottom are one
  step, so one undo restores the list.

| You do | Result |
|---|---|
| Tick an item | It moves below the divider, with its sub-items |
| Tick a sub-item | It shows under a ghost of its parent in the ticked section |
| Drag an item onto another place | It moves there with its sub-items. Dropped at the top level below an item that has sub-items, it lands after them. |
| Drag a sub-item out to the top level, in place | The sub-items below it become its own |
| Drag an item to the right, or press Tab | It's indented under the item above, sub-items included (still two levels) |
| Tab on an indented item, or on the first item | Nothing; there are only two levels |

## The board, just like Keep's

- **Cards** with the note's colour, title, text or unticked items
  ("+ 3 ticked items"), first image, reminder and labels. Notes without a title
  show none, like in Keep. Tick items right on the card.
- **Hover a card** (on a computer) for the pin and Keep's buttons: reminder,
  colour, archive and more. Right-click a card, or hold it on a phone, for its
  menu.
- **Click a card** to open the note over the board, in its colour. On a
  computer it covers just the board's tab: switch to another tab and back, and
  the note is still open there. On phones it takes the whole screen, with Keep's top bar (back, pin, reminder, archive) and
  bottom bar ("+", colour, undo/redo, "⋮"), both staying put while you scroll.
- **The board is your home screen**, like Keep's: it opens when Obsidian starts,
  and on a phone an empty tab shows it too.
- **The search bar** stays at the top while you scroll. Its ☰ button opens the
  side menu: Notes, Reminders, your labels, Archive.
- **"Take a note…"** opens a new note with the title ready to type; the
  checkbox icon starts a new list instead. Close it untouched and it's thrown
  away, like in Keep.
- **Drag cards** to put them in your order. A dragged card takes the place of
  the card you drop it on.

## Notes, just like Keep's

- **Pin, colour, reminder and archive buttons** in every note's top bar.
- **No clutter.** Properties are hidden; the note's labels and "Edited …"
  appear below the text, outside it, so Ctrl/Cmd+A selects just the text.
- **Labels**: the "+ Label" button below a note (or "Labels" in its ⋮ menu)
  opens Keep's "Label note": tick labels or type a new one.
- **Keep titles** with characters a file name can't have ("Sept/Oct 2026").
  Editing the title renames the note too.
- **Archive** with "Undo" in the confirmation.
- **Reminders** pop up as a notice in Obsidian, plus a system notification on a
  computer; "Open" shows the note over the board. Reminders that fell due while Obsidian was closed are shown when you
  open it.
- **Show / hide checkboxes** (⋮ menu) turns a note's lines into a checklist and
  back.

## Moving from Google Keep

The command **Import from Google Keep** (or the button in the plugin's
settings) brings your notes over, ready for the board. There are two ways to
get them out of Keep:

**Everything (recommended): the export script.** It keeps the order of your
notes on the board and the sub-items of your checklists, which Google's own
export leaves out, plus everything else: text, ticks, colours, pins, archive,
labels, images, dates and links between notes.

1. Install [Python](https://www.python.org/downloads/), then:
   `pip install gkeepapi gpsoauth requests`
2. Download [`tools/keep_export.py`](tools/keep_export.py).
3. Get a one-time sign-in code: open
   <https://accounts.google.com/EmbeddedSetup>, sign in and click "I agree"
   (the page may keep loading; that's fine). Then open the browser's developer
   tools → Application (Chrome) or Storage (Firefox) → Cookies →
   accounts.google.com, and copy the value of `oauth_token`.
4. Run `python keep_export.py you@gmail.com` and paste the code when asked.
   It's typed invisibly, used once to sign in, and never saved.
5. In Obsidian, run **Import from Google Keep** and choose the `keep-export`
   folder the script made.

The script only reads from Keep. Google has no official way for apps to read
Keep, so it uses [gkeepapi](https://github.com/kiwiz/gkeepapi), the unofficial
library other Keep tools use too.

**Quick: Google Takeout.** At [takeout.google.com](https://takeout.google.com),
select only Keep, download and unzip it, then run **Import from Google Keep**
and choose its `Keep` folder. Takeout has your notes, ticks, colours, pins,
archive, labels and images, but **not** the order of your notes (the board then
shows the newest first) and **not** checklist sub-items (they come in flat).

Either way: notes from Keep's trash are left out, and reminders aren't part of
either export (Keep keeps them in Google Tasks). Import on a computer; the notes
then reach your phone like any other notes.

## Getting started

1. Install **Full Keep Mode** (Settings → Community plugins → Browse) and
   enable it. It needs Obsidian 1.10 or later (for Bases); nothing else.
2. Run the command **Create a Keep board** (Ctrl/Cmd+P), or use the button in
   the plugin's settings.
3. Optional, to match Keep: turn off **Settings → Editor → Fold indent**, so
   list items can't be collapsed.

The checklist features work in any note, with or without the board.

## How it stores things

Everything is **plain Markdown**: ordinary `- [ ]` / `- [x]` lists, and
properties in each note's front matter: `keep_pinned`, `keep_color`,
`keep_order` (the note's place on the board), `keep_archived`, `keep_reminder`,
`keep_title` and `tags` (the labels). Nothing is stored anywhere else.

The board is a view of Obsidian's Bases: a `.base` file with views of type
`keep-board` decides which notes are on it ("Board": not archived; "Archive":
archived).

## Settings

| Setting | Default |
|---|---|
| Hide properties | on |
| Keep titles | on |
| Labels and edit date below the note | on |
| Pin button | on |
| Colour button | on |
| Archive button | on |
| Reminders | on |
| Board as home screen | on |
| Search bar | on |
| Labels side menu | on |
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

Commands: **Take a note**, **Take a note as a checklist**, **Labels of this
note**, **Show or hide checkboxes in this note**, **Open the labels side menu**,
**Create a Keep board**, and **Move ticked items down in this note** (tidies up
a list that already has ticked items in between).

## Installation

From Obsidian: **Settings → Community plugins → Browse**, search for
"Full Keep Mode", install and enable.

Manually: download `main.js`, `manifest.json` and `styles.css` from the
[latest release](../../releases/latest) into
`<your vault>/.obsidian/plugins/full-keep-mode/`, then enable the plugin under
**Settings → Community plugins**.

## Good to know

Reminders show up while Obsidian is open, and ones you missed appear when you
open it. Obsidian doesn't let plugins schedule notifications, so unlike Keep,
a reminder can't reach your phone while Obsidian is closed.

## Development

There's no build step: `main.js` is the plugin as it ships.

The tests in `tests/live_test.py` run against a real Obsidian. They create
temporary notes and a temporary board, tick, drag with real mouse events, press
keys, pin, colour, archive, set reminders, search, filter by label and take
notes, and check the results:

```bash
# Start Obsidian with its debugging port (close it first). Windows:
"%LOCALAPPDATA%\Programs\Obsidian\Obsidian.exe" --remote-debugging-port=9222
# macOS:
open -a Obsidian --args --remote-debugging-port=9222

pip install websocket-client pillow
python tests/live_test.py          # the tests (keep the Obsidian window visible)
python tests/record_board_demo.py  # re-records docs/board.gif
python tests/record_demo.py        # re-records docs/demo.gif
```

## License

[MIT](LICENSE)
