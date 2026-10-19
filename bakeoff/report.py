"""report.html: one column per model, one row per page, so they can be compared at a glance."""
from __future__ import annotations

import html
from pathlib import Path

CHECKLIST = [
    "Likeness: would the parent recognise their child on every page, close-up and far away?",
    "Consistency: same face, hair and outfit from page to page?",
    "Style: does it look like the reference page, not generic AI art?",
    "Mistakes: extra fingers, merged limbs, stray letters in the picture?",
    "Layout: is the text side calm, and are faces clear of the fold line?",
    "Refusals: did the model turn the child's photo down?",
]

CSS = """
:root { --bg: #faf7f2; --fg: #2b2420; --muted: #7a6e66; --card: #fff; --line: #e6ded4;
        --ok: #2f7d4f; --bad: #b3412e; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1b1916; --fg: #eee6dc; --muted: #a59a90; --card: #25221e; --line: #3a352f;
          --ok: #6cc28f; --bad: #ef8a76; }
}
body { margin: 0; padding: 24px 16px; background: var(--bg); color: var(--fg);
       font: 15px/1.5 system-ui, sans-serif; }
h1 { margin: 0 0 4px; font-size: 22px; }
.muted { color: var(--muted); }
ul { margin: 8px 0 20px; padding-left: 20px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; }
th, td { border: 1px solid var(--line); padding: 8px; vertical-align: top; background: var(--card); }
th { text-align: left; min-width: 360px; }
th.row { min-width: 150px; max-width: 180px; font-weight: 600; }
img { width: 360px; display: block; border-radius: 4px; }
.ok { color: var(--ok); } .bad { color: var(--bad); }
.err { font-size: 12px; color: var(--bad); max-width: 360px; word-break: break-word; }
.small { font-size: 12px; }
"""


def _cell(entry: dict | None) -> str:
    if not entry:
        return "<td></td>"
    status = entry["status"]
    if status == "ok":
        shown = entry.get("spread") or entry["file"]
        raw = f' · <a href="{html.escape(entry["file"])}">raw image</a>' if entry.get("spread") else ""
        return (f'<td><a href="{html.escape(shown)}"><img loading="lazy" src="{html.escape(shown)}"></a>'
                f'<div class="small muted">{entry["seconds"]:.0f}s{raw}</div></td>')
    label = {"refused": "⛔ Refused", "failed": "⚠️ Failed", "skipped": "Skipped"}[status]
    return f'<td><b class="bad">{label}</b><div class="err">{html.escape(entry.get("error", ""))}</div></td>'


def write(out_dir: Path, title: str, results: list[dict], scenes: list[dict], dry_run: bool) -> Path:
    head = "".join(
        f'<th>{html.escape(r["name"])}<div class="small muted">{html.escape(r.get("note", ""))}</div>'
        f'<div class="small"><span class="{"ok" if r["ok"] == r["total"] else "bad"}">'
        f'{r["ok"]}/{r["total"]} images</span> · {r["refused"]} refused · '
        f'~${r["usd"]:.2f} · {r["seconds"]:.0f}s</div></th>'
        for r in results
    )
    rows = [f'<tr><th class="row">Character sheet</th>{"".join(_cell(r["sheet"]) for r in results)}</tr>']
    for scene in scenes:
        cells = "".join(_cell(next((p for p in r["pages"] if p["id"] == scene["id"]), None)) for r in results)
        rows.append(f'<tr><th class="row">{html.escape(scene["id"])}'
                    f'<div class="small muted">tests {html.escape(scene.get("tests", ""))}</div></th>{cells}</tr>')
    checklist = "".join(f"<li>{html.escape(c)}</li>" for c in CHECKLIST)
    note = "<p><b>Dry run:</b> placeholder images, no model was called.</p>" if dry_run else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Image model bake-off</title><style>{CSS}</style></head>
<body>
<h1>{html.escape(title)}</h1>
<div class="muted">Same photo, style page and story for every model. Costs are estimates from models.json.</div>
{note}
<ul>{checklist}</ul>
<div class="scroll"><table><tr><th class="row"></th>{head}</tr>{"".join(rows)}</table></div>
</body></html>
"""
    path = out_dir / "report.html"
    path.write_text(page, encoding="utf-8")
    return path
