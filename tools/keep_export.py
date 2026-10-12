#!/usr/bin/env python3
"""
keep_export.py - export everything from Google Keep for Full Keep Mode.

Google Takeout leaves out the order of your notes on the board and the
indentation of checklist items. This script reads them from Keep itself (with
the unofficial gkeepapi library, the same way other Keep tools do) and writes
an export folder that Full Keep Mode's "Import from Google Keep" command reads:

    keep-export/
      notes.json     every note: title, text, checklist items with their
                     sub-items and ticks, colour, pinned, archived, labels,
                     order on the board, dates, links
      media/         images, drawings and recordings

Usage
-----
    pip install gkeepapi gpsoauth requests
    python keep_export.py you@gmail.com            # export from Keep
    python keep_export.py --from-dump dump.json    # convert a gkeepapi dump

Signing in: Google doesn't let scripts sign in with your password. Instead:
  1. Open https://accounts.google.com/EmbeddedSetup in your browser and sign in
     (click "I agree" at the end, even if the page then keeps loading).
  2. Open the browser's developer tools -> Application (Chrome) or Storage
     (Firefox) -> Cookies -> accounts.google.com, and copy the value of
     "oauth_token" (it starts with "oauth2_4/").
  3. Paste it when this script asks. It's typed invisibly, used once to sign
     in, kept only in memory, and never saved or shown.
The script only reads from Keep; it never changes your notes.
"""
import argparse
import datetime
import getpass
import json
import mimetypes
import sys
from collections import defaultdict
from pathlib import Path

EPOCH = "1970-01-01T00:00:00.000000Z"


def alive(node):
    """Not deleted or trashed (a trashed note is kept, but marked)."""
    ts = node.get("timestamps") or {}
    return ts.get("deleted", EPOCH) in (EPOCH, None, "")


def convert(dump, media_files=None):
    """A gkeepapi dump (Keep.dump()) -> the export format."""
    media_files = media_files or {}
    labels = {label["mainId"]: label["name"] for label in dump.get("labels", [])}
    children = defaultdict(list)
    for node in dump["nodes"]:
        if node.get("parentId"):
            children[node["parentId"]].append(node)

    def items_of(note_id):
        items = [n for n in children[note_id] if n["type"] == "LIST_ITEM" and alive(n)]
        by_parent = defaultdict(list)
        for item in items:
            by_parent[item.get("superListItemId") or None].append(item)

        def tree(parent):
            out = []
            for item in sorted(by_parent[parent], key=lambda i: -int(i.get("sortValue") or 0)):
                out.append({
                    "text": item.get("text", ""),
                    "checked": bool(item.get("checked")),
                    "children": tree(item["id"]),
                })
            return out

        return tree(None)

    notes = []
    for node in dump["nodes"]:
        if node["type"] not in ("NOTE", "LIST") or not alive(node):
            continue
        ts = node.get("timestamps") or {}
        blobs = [n for n in children[node["id"]] if n["type"] == "BLOB" and alive(n)]
        media = []
        for index, blob in enumerate(blobs):
            name = media_files.get(blob["id"]) or media_files.get(f"{node['id']}_{index}")
            if name:
                media.append(name)
        links = []
        for annotation in (node.get("annotationsGroup") or {}).get("annotations", []):
            web = annotation.get("webLink")
            if web and web.get("url"):
                links.append({"url": web["url"], "title": web.get("title") or ""})
        notes.append({
            "id": node["id"],
            "serverId": node.get("serverId"),
            "type": "list" if node["type"] == "LIST" else "note",
            "title": node.get("title") or "",
            "text": (node.get("text") or "") if node["type"] == "NOTE" else "",
            "items": items_of(node["id"]) if node["type"] == "LIST" else [],
            "color": (node.get("color") or "DEFAULT").upper(),
            "pinned": bool(node.get("isPinned")),
            "archived": bool(node.get("isArchived")),
            "trashed": ts.get("trashed", EPOCH) not in (EPOCH, None, ""),
            "order": int(node.get("sortValue") or 0),
            "labels": [labels[l["labelId"]] for l in node.get("labelIds", [])
                       if isinstance(l, dict) and l.get("labelId") in labels and l.get("deleted", EPOCH) == EPOCH],
            "created": ts.get("created"),
            "edited": ts.get("userEdited") or ts.get("updated"),
            "links": links,
            "media": media,
        })
    return {
        "format": "full-keep-mode-export",
        "version": 1,
        "exported": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "notes": notes,
    }


def media_index(folder):
    """Media file names by blob id (or <note id>_<n>, from older exports)."""
    found = {}
    if folder and folder.is_dir():
        for path in folder.iterdir():
            found[path.stem] = path.name
    return found


def sign_in(email):
    import gkeepapi
    import gpsoauth

    device_id = "0123456789abcdef"
    oauth_token = getpass.getpass("Paste the oauth_token (typed invisibly): ").strip()
    if not oauth_token:
        sys.exit("No token given.")
    response = gpsoauth.exchange_token(email, oauth_token, device_id)
    master_token = response.get("Token")
    if not master_token:
        sys.exit(f"Google didn't accept the token ({response.get('Error', 'unknown error')}). "
                 "Get a fresh one; it only works once and for a few minutes.")
    keep = gkeepapi.Keep()
    keep.authenticate(email, master_token, device_id=device_id)
    return keep


def download_media(keep, folder):
    import requests

    folder.mkdir(parents=True, exist_ok=True)
    failed = 0
    for note in keep.all():
        for blob in note.blobs:
            try:
                response = requests.get(keep.getMediaLink(blob), timeout=60)
                response.raise_for_status()
                kind = response.headers.get("Content-Type", "").split(";")[0]
                extension = mimetypes.guess_extension(kind) or ".bin"
                (folder / f"{blob.id}{extension}").write_bytes(response.content)
            except Exception as error:  # keep going; report at the end
                failed += 1
                print(f"  couldn't download a file of \"{note.title or note.id}\": {error}")
    return failed


def main():
    parser = argparse.ArgumentParser(description="Export Google Keep for Full Keep Mode.")
    parser.add_argument("email", nargs="?", help="your Google account, to export from Keep")
    parser.add_argument("--from-dump", type=Path, help="convert a gkeepapi dump (JSON) instead")
    parser.add_argument("--media", type=Path, help="with --from-dump: the folder with its media files")
    parser.add_argument("--out", type=Path, default=Path("keep-export"), help="export folder (default: keep-export)")
    args = parser.parse_args()
    if not args.email and not args.from_dump:
        parser.error("give your Google account, or --from-dump")

    out = args.out
    media_out = out / "media"
    out.mkdir(parents=True, exist_ok=True)
    if args.from_dump:
        dump = json.loads(args.from_dump.read_text(encoding="utf-8"))
        media = media_index(args.media)
        if args.media:
            media_out.mkdir(exist_ok=True)
            for name in media.values():
                (media_out / name).write_bytes((args.media / name).read_bytes())
        failed = 0
    else:
        keep = sign_in(args.email)
        print("Signed in. Reading your notes…")
        dump = keep.dump()
        failed = download_media(keep, media_out)
        media = media_index(media_out)

    export = convert(dump, media)
    (out / "notes.json").write_text(json.dumps(export, ensure_ascii=False, indent=1), encoding="utf-8")
    notes = export["notes"]
    lists = [n for n in notes if n["type"] == "list"]
    sub_items = sum(1 for n in lists for i in n["items"] for _ in i["children"])
    print(f"Exported {len(notes)} notes to {out}/ "
          f"({len(lists)} checklists with {sub_items} sub-items, "
          f"{sum(len(n['media']) for n in notes)} files"
          f"{f', {failed} files failed' if failed else ''}).")
    print("Next, in Obsidian: command \"Import from Google Keep\", and choose this folder.")


if __name__ == "__main__":
    main()
