#!/usr/bin/env python3
"""Extract ⟦⟧ annotation-clauses from the knowledge dossier into clauses.json.

Each `> ⟦layer · ★★ · ⟳⟧ — note` blockquote line becomes one clause record:
    {id, book, file, section, anchor, layers[], salience, seed, note}

Run from anywhere; paths are absolute.
"""
import json
import os
import re

ROOT = "/Users/adarsh.kumar/sandboxes/bataille"
KNOWLEDGE = os.path.join(ROOT, "knowledge")
OUT = os.path.join(ROOT, "sandbox", "clauses.json")

FILES = [
    ("01-life-and-phases.md",      "Life & the Four Phases"),
    ("02-core-concepts.md",        "Concept Lexicon"),
    ("book-on-nietzsche.md",       "On Nietzsche"),
    ("book-visions-of-excess.md",  "Visions of Excess"),
    ("book-theory-of-religion.md", "Theory of Religion"),
    ("book-erotism.md",            "Erotism"),
]

LAYERS = {"genetic", "persona", "purpose", "context"}

# > ⟦tag⟧ — note   (em/en/hyphen dash)
CLAUSE_RE = re.compile(r"^>\s*⟦(.+?)⟧\s*[—–-]\s*(.*)$")


def parse_tag(tag: str):
    layers, salience, seed = [], 0, False
    for part in tag.split("·"):
        p = part.strip()
        if p in LAYERS:
            layers.append(p)
        elif p and all(ch == "★" for ch in p):
            salience = len(p)
        elif "⟳" in p:
            seed = True
    return layers, salience, seed


def strip_md(s: str) -> str:
    # light cleanup for the anchor preview only
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    return s.strip()


def is_skippable_line(s: str) -> bool:
    return (
        not s
        or s.startswith(">")
        or s.startswith("*Annotations in")
        or s.startswith("---")
    )


clauses = []
summary_by_book = {}
summary_by_layer = {l: 0 for l in LAYERS}
seeds = 0
salient_2 = 0

for fname, book in FILES:
    path = os.path.join(KNOWLEDGE, fname)
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    section = ""
    anchor = ""
    idx = 0
    book_count = 0

    for line in lines:
        s = line.strip()
        m = CLAUSE_RE.match(line)
        if m:
            tag, note = m.group(1), m.group(2).strip()
            layers, salience, seed = parse_tag(tag)
            idx += 1
            book_count += 1
            clauses.append({
                "id": f"{fname.removesuffix('.md')}-{idx:03d}",
                "book": book,
                "file": f"knowledge/{fname}",
                "section": section,
                "anchor": strip_md(anchor)[:320],
                "layers": layers,
                "salience": salience,
                "seed": seed,
                "note": note,
            })
            for l in layers:
                summary_by_layer[l] = summary_by_layer.get(l, 0) + 1
            if seed:
                seeds += 1
            if salience >= 2:
                salient_2 += 1
        elif s.startswith("#"):
            section = s.lstrip("#").strip()
        elif not is_skippable_line(s):
            anchor = s  # most recent substantive prose line before next annotation

    summary_by_book[book] = book_count

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(
        {
            "generated_from": "knowledge/*.md (⟦⟧ annotations)",
            "count": len(clauses),
            "summary": {
                "by_book": summary_by_book,
                "by_layer": summary_by_layer,
                "seeds": seeds,
                "salience_high": salient_2,
            },
            "clauses": clauses,
        },
        f,
        ensure_ascii=False,
        indent=2,
    )

print(f"wrote {OUT}")
print(f"total clauses: {len(clauses)}")
print("by book:")
for b, n in summary_by_book.items():
    print(f"  {n:3d}  {b}")
print("by layer:")
for l, n in summary_by_layer.items():
    print(f"  {n:3d}  {l}")
print(f"⟳ generative seeds: {seeds}")
print(f"★★ high salience:   {salient_2}")
