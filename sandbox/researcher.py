#!/usr/bin/env python3
"""Background researcher — agents that slowly accumulate research on clauses.

Per-clause storage: append-only JSONL at `sandbox/research/<clause_id>.jsonl`.
Each line is one `research_note` (see schemas/research_note.json).

This module is callable two ways:

  1. As a library, from server.py — `run_one_pass(clause_id, pass_kind, ...)`.
     Used by /api/research/run-once. Synchronous; one LLM call.
  2. As a script — `python3 researcher.py [--autopilot] [--once <clause_id>]`.
     Used by a developer to seed the system, or by a future cron to run
     autopilot ticks. Cron / loop scheduling is intentionally not done here;
     it lives in server.py or an external scheduler.

Schema enforcement: each provider call uses structured-output mode where
available (Gemini `responseSchema`, OpenAI/Groq `response_format`). Output is
JSON-parsed and shape-validated against `schemas/research_note.json` before
write. Validation failures are recorded as `warnings` on a partial note
rather than dropped — we want to *see* the failure mode, not hide it.

This file deliberately does NOT introduce sqlite yet. See
`docs/researcher-design.md` for the migration plan. File-based is fine for
the next ~1000 notes; sqlite when we need relational queries across clauses.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

import db
import vector_store
import web_search

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(ROOT)
CLAUSES_PATH = os.path.join(ROOT, "clauses.json")
RESEARCH_DIR = os.path.join(ROOT, "research")
SCHEMAS_DIR = os.path.join(ROOT, "schemas")
KNOWLEDGE_DIR = os.path.join(WORKSPACE, "knowledge")
BOOKS_DIR = os.path.join(WORKSPACE, "books")
PIN_FILE = os.path.join(RESEARCH_DIR, "_pinned.json")

os.makedirs(RESEARCH_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# pass kinds — each names a *distinct question* the researcher can ask.
# Order matters: the default progression is internal-first (cheap, deepens
# the corpus map) then outward (external, brings the world in).
# ---------------------------------------------------------------------------

PASS_KINDS = [
    "internal-cross-corpus",   # find echoes of the lens in other knowledge/*.md files
    "kin-finding",             # name philosophical kin who perform the same gesture
    "outward-projection",      # comparative cases in non-bataille traditions / domains
    "install-deep-test",       # try the lens as a perceptual default on a fresh phenomenon
    "external-web",            # bring in sources from the open web (needs web tool; not yet wired)
    "synthesis",               # given N prior passes, synthesize what the dossier now knows
]


# ---------------------------------------------------------------------------
# pass-specific system prompts. Kept short; the LLM also receives the
# research_note schema and prior passes as context.
# ---------------------------------------------------------------------------

PASS_SYSTEM_PROMPTS = {
    "internal-cross-corpus": (
        "You are the internal-cross-corpus researcher for a Bataille-derived agent blueprint. "
        "Given a single clause (the lens) and the FULL TEXT of every other knowledge file in our dossier, "
        "your job is to find passages and patterns *in OTHER files* that the lens applies to or that echo it. "
        "Do NOT cite the source file the clause came from; we want CROSS echoes. "
        "Prefer specificity: cite file:line, quote the exact phrase, and name what survives of the lens "
        "and what is different. Findings are not summaries — they are *new links* the dossier did not have."
    ),
    "kin-finding": (
        "You are the kin-finding researcher (skill: annotations-reach-outward, ⊗ tag). "
        "Given a Bataille clause and its anchor passage, name a small family (3–5) of NEAREST minds — "
        "philosophers, mystics, poets, anthropologists — who perform the *same gesture* under different "
        "vocabularies. For each kin, name the *exact move* shared in one sentence and the *exact divergence* "
        "in one sentence. Distrust 'X was influenced by Y' — that is biography. We want the structural "
        "kinship of the move, regardless of historical connection."
    ),
    "outward-projection": (
        "You are the outward-projection researcher (skill: annotations-reach-outward, ⊕ tag). "
        "Given a Bataille structure (the lens), name 3–5 NON-BATAILLE instances where this structure appears. "
        "At least one MUST be non-western. For each instance, name what survives of the pattern and what "
        "breaks. Distrust pure analogy; we want cases that *operate by the same mechanism*, not cases that "
        "merely 'feel similar.' If you cannot find a strong instance in a tradition, say so — silence is "
        "data, slop is not."
    ),
    "install-deep-test": (
        "You are the install-deep tester (skill: annotations-reach-outward, ⚑ tag). "
        "Given a Bataille clause that the user has marked 'install-deep' (rewire the agent's perception, "
        "not its index), your job is to TEST whether the lens behaves as a perceptual default. Do this by: "
        "(a) picking ONE concrete 2026 phenomenon the user did not specify; (b) showing how a default reader "
        "would first see it; (c) showing how the lens-installed reader sees it differently; (d) naming the "
        "FLINCH or the REACH the install produces. If the lens fails to change perception of the phenomenon, "
        "say so honestly — that is itself useful information."
    ),
    "external-web": (
        "You are the external-web researcher. You have been given live web search results below the prompt. "
        "Your job: synthesize what those results add to the dossier's understanding of the lens. "
        "For each finding, the `evidence` field MUST cite the source URL from the results; "
        "the `source_kind` should be 'web'; the `source_ref` should be the URL. "
        "Do NOT cite sources that are not in the provided results. If the results are weak or off-topic, "
        "say so honestly in `warnings` and propose better queries via `next_seeds`."
    ),
    "synthesis": (
        "You are the synthesis pass. Given the FULL prior research stream for one clause (N passes), produce "
        "a *new* note that names what the dossier now knows about this lens that no single prior pass "
        "contained — links *between* passes, contradictions *between* passes, and what the next pass should "
        "do. Do NOT repeat what any single prior pass already said."
    ),
}


# ---------------------------------------------------------------------------
# Storage helpers — file-based, append-only JSONL per clause.
# When we introduce sqlite (see docs/researcher-design.md), the only change
# is the body of append_note / read_notes / pinned_clause_ids.
# ---------------------------------------------------------------------------

def research_file(clause_id: str) -> str:
    return os.path.join(RESEARCH_DIR, f"{clause_id}.jsonl")


def append_note(clause_id: str, note: dict) -> None:
    path = research_file(clause_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")


def read_notes(clause_id: str) -> list[dict]:
    path = research_file(clause_id)
    if not os.path.exists(path):
        return []
    notes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                notes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return notes


def next_pass_number(clause_id: str) -> int:
    return len(read_notes(clause_id)) + 1


def pinned_clause_ids() -> list[str]:
    if not os.path.exists(PIN_FILE):
        return []
    with open(PIN_FILE, encoding="utf-8") as f:
        return json.load(f).get("pinned", [])


def set_pinned(clause_id: str, pinned: bool) -> list[str]:
    current = set(pinned_clause_ids())
    if pinned:
        current.add(clause_id)
    else:
        current.discard(clause_id)
    out = sorted(current)
    with open(PIN_FILE, "w", encoding="utf-8") as f:
        json.dump({"pinned": out}, f, ensure_ascii=False, indent=2)
    # Mirror into sqlite. Safe to call even if db not yet initialized — caller
    # ensures init_db ran at startup.
    try:
        db.set_pinned(clause_id, pinned)
    except Exception as e:  # noqa: BLE001
        print(f"[researcher] db.set_pinned failed: {e}", file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Schema loading + minimal shape validation. We do NOT pull in jsonschema as
# a dep; the validation here is intentionally cheap — it catches the common
# wrong-shape failure (missing required keys, wrong type at top level) and
# lets per-finding nits through as `warnings`.
# ---------------------------------------------------------------------------

def load_schema(name: str) -> dict:
    path = os.path.join(SCHEMAS_DIR, f"{name}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def shape_validate(obj: Any, schema: dict) -> list[str]:
    """Returns a list of human-readable shape problems. Empty list = OK at the top level."""
    problems: list[str] = []
    if schema.get("type") == "object":
        if not isinstance(obj, dict):
            return [f"expected object, got {type(obj).__name__}"]
        for k in schema.get("required", []):
            if k not in obj:
                problems.append(f"missing required key '{k}'")
        props = schema.get("properties", {})
        for k, v in obj.items():
            if k in props:
                t = props[k].get("type")
                if t == "string" and not isinstance(v, str):
                    problems.append(f"'{k}' expected string, got {type(v).__name__}")
                elif t == "integer" and not isinstance(v, int):
                    problems.append(f"'{k}' expected integer, got {type(v).__name__}")
                elif t == "array" and not isinstance(v, list):
                    problems.append(f"'{k}' expected array, got {type(v).__name__}")
    return problems


# ---------------------------------------------------------------------------
# Context gathering — what we feed the LLM along with the schema and prompt.
# ---------------------------------------------------------------------------

def get_clause(clause_id: str) -> dict | None:
    with open(CLAUSES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    for c in data.get("clauses", []):
        if c.get("id") == clause_id:
            return c
    return None


def gather_other_knowledge_files(except_file: str | None) -> str:
    """Concatenate all knowledge/*.md except the one the clause came from."""
    chunks = []
    for fn in sorted(os.listdir(KNOWLEDGE_DIR)):
        if not fn.endswith(".md"):
            continue
        full = os.path.join(KNOWLEDGE_DIR, fn)
        if except_file and os.path.abspath(full) == os.path.abspath(except_file):
            continue
        with open(full, encoding="utf-8") as f:
            chunks.append(f"--- BEGIN {fn} ---\n{f.read()}\n--- END {fn} ---\n")
    return "\n".join(chunks)


def prior_passes_summary(clause_id: str, max_passes: int = 8) -> str:
    notes = read_notes(clause_id)
    if not notes:
        return "(no prior passes)"
    lines = []
    for n in notes[-max_passes:]:
        lines.append(
            f"- pass #{n.get('pass_number','?')} ({n.get('pass_kind','?')}): "
            + "; ".join(f.get("claim", "") for f in n.get("findings", [])[:3])
        )
    return "\n".join(lines)


def build_user_message(clause: dict, pass_kind: str, pass_number: int) -> str:
    base = (
        f"CLAUSE (the lens):\n"
        f"  id: {clause['id']}\n"
        f"  source: {clause.get('book','')} — {clause.get('section','')}\n"
        f"  layers: {', '.join(clause.get('layers',[]))}\n"
        f"  note: {clause.get('note','')}\n"
        f"  anchor: {clause.get('anchor','')}\n\n"
        f"PASS:\n"
        f"  kind: {pass_kind}\n"
        f"  number: {pass_number}\n\n"
        f"PRIOR PASSES (so you do not repeat):\n{prior_passes_summary(clause['id'])}\n\n"
    )
    if pass_kind == "internal-cross-corpus":
        src_file = clause.get("source_file") or ""
        src_full = os.path.join(WORKSPACE, src_file) if src_file else None
        other = gather_other_knowledge_files(src_full)
        base += (
            f"OTHER KNOWLEDGE FILES (do NOT cite the clause's own source file):\n"
            f"---BEGIN CROSS-CORPUS---\n{other}\n---END CROSS-CORPUS---\n\n"
        )
    if pass_kind == "external-web":
        # Build a query from the clause; let the model see real search results
        # rather than asking it to hallucinate citations.
        try:
            q = f"{clause.get('note','')[:200]} {clause.get('anchor','')[:120]}".strip()
            results = web_search.search(q, max_results=6, depth="advanced")
            base += (
                f"WEB SEARCH RESULTS (live, via Tavily):\n"
                f"Query: {q}\n\n"
                f"{web_search.format_results_for_prompt(results)}\n\n"
            )
        except web_search.WebSearchUnavailable as e:
            base += f"WEB SEARCH UNAVAILABLE: {e}\n(Return warnings: ['no-web-access'] and findings: [].)\n\n"
        except Exception as e:  # noqa: BLE001
            base += f"WEB SEARCH ERROR: {e}\n(Return warnings: ['web-search-error: {e}'].)\n\n"
    base += (
        "Produce ONE research_note as a JSON object matching the schema. "
        "Strict: every finding must have evidence + confidence tag. "
        "next_seeds should propose what the NEXT pass should investigate."
    )
    return base


# ---------------------------------------------------------------------------
# Provider call — minimal, structured-output where supported. We do not
# import from server.py to keep researcher.py independently runnable.
# ---------------------------------------------------------------------------

def call_gemini_json(system: str, user: str, model: str, key: str, schema: dict) -> dict:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    cleaned = _gemini_clean_schema(schema)
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "maxOutputTokens": 16384,
            "temperature": 0.7,
            "responseMimeType": "application/json",
            "responseSchema": cleaned,
        },
    }
    req = urllib.request.Request(
        url,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    cands = body.get("candidates", [])
    if not cands:
        raise RuntimeError(f"no candidates: {json.dumps(body)[:400]}")
    text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
    return json.loads(text)


def _gemini_clean_schema(schema: dict) -> dict:
    """Strip JSON-Schema keys Gemini's responseSchema does not accept."""
    DROP = {"$schema", "$id", "additionalProperties", "title", "description"}
    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items() if k not in DROP}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    out = walk(schema)
    return out


def call_groq_json(system: str, user: str, model: str, key: str, schema: dict) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system + "\n\nReturn JSON matching the provided schema; nothing else."},
            {"role": "user", "content": user + "\n\nSCHEMA:\n" + json.dumps(schema)},
        ],
        "max_tokens": 4000,
        "temperature": 0.6,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "BatailleSandbox/1.0",
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return json.loads(body["choices"][0]["message"]["content"])


# ---------------------------------------------------------------------------
# The core: one research pass end-to-end.
# ---------------------------------------------------------------------------

def run_one_pass(
    clause_id: str,
    pass_kind: str | None = None,
    provider: str = "gemini",
    model: str | None = None,
    key: str | None = None,
) -> dict:
    if pass_kind is None:
        # Cheap default progression: pass 1 = internal, 2 = kin, 3 = outward,
        # 4 = synthesis, then loop kin/outward/synthesis.
        n = next_pass_number(clause_id)
        default_order = ["internal-cross-corpus", "kin-finding", "outward-projection", "synthesis"]
        pass_kind = default_order[(n - 1) % len(default_order)]
    if pass_kind not in PASS_KINDS:
        raise ValueError(f"unknown pass_kind: {pass_kind}")

    clause = get_clause(clause_id)
    if clause is None:
        raise ValueError(f"unknown clause: {clause_id}")

    schema = load_schema("research_note")
    pass_number = next_pass_number(clause_id)
    system = PASS_SYSTEM_PROMPTS[pass_kind]
    user = build_user_message(clause, pass_kind, pass_number)

    if provider == "gemini":
        key = key or os.environ.get("GEMINI_API_KEY", "")
        model = model or os.environ.get("BATAILLE_GEMINI_MODEL", "gemini-2.5-flash")
        raw = call_gemini_json(system, user, model, key, schema)
    elif provider == "groq":
        key = key or os.environ.get("GROQ_API_KEY", "")
        model = model or os.environ.get("BATAILLE_GROQ_MODEL", "openai/gpt-oss-120b")
        raw = call_groq_json(system, user, model, key, schema)
    else:
        raise ValueError(f"researcher does not yet support provider: {provider}")

    # Enforce fields the LLM should not be allowed to drift on.
    raw["clause_id"] = clause_id
    raw["pass_kind"] = pass_kind
    raw["pass_number"] = pass_number

    problems = shape_validate(raw, schema)
    if problems:
        raw.setdefault("warnings", []).extend(problems)

    # Provenance stamps — not in the schema (the schema is what the LLM produces),
    # added on write so we can audit the pass without modifying the LLM contract.
    raw["_meta"] = {
        "provider": provider,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    append_note(clause_id, raw)
    # Mirror into sqlite (relational queries) and, if enabled, vector store.
    try:
        db.insert_note(raw)
    except Exception as e:  # noqa: BLE001
        print(f"[researcher] db.insert_note failed: {e}", file=sys.stderr)
    if vector_store.is_enabled():
        try:
            # Embed the concatenated findings text as the note's vector.
            text = " ".join(f.get("claim", "") for f in raw.get("findings", []))
            if text:
                vector_store.store_note_embedding(clause_id, pass_number, text)
        except Exception as e:  # noqa: BLE001
            print(f"[researcher] vector_store.store_note_embedding failed: {e}", file=sys.stderr)
    return raw


# ---------------------------------------------------------------------------
# Autopilot — picks the next clause to work on.
# Priority: (a) pinned with fewest passes, (b) ⟳/⚑/⊕ tagged unresearched,
# (c) random genetic clause.
# ---------------------------------------------------------------------------

def pick_next_clause() -> str | None:
    with open(CLAUSES_PATH, encoding="utf-8") as f:
        clauses = json.load(f).get("clauses", [])
    pinned = pinned_clause_ids()

    def pass_count(cid: str) -> int:
        return len(read_notes(cid))

    pinned_sorted = sorted(
        [c for c in clauses if c["id"] in pinned],
        key=lambda c: pass_count(c["id"]),
    )
    if pinned_sorted:
        return pinned_sorted[0]["id"]

    flagged = [
        c for c in clauses
        if (c.get("seed") or "install-deep" in (c.get("outward_tags") or []) or "research-task" in (c.get("outward_tags") or []))
        and pass_count(c["id"]) == 0
    ]
    if flagged:
        return flagged[0]["id"]

    genetic = [c for c in clauses if "genetic" in c.get("layers", []) and pass_count(c["id"]) < 2]
    if genetic:
        return random.choice(genetic)["id"]
    return None


def autopilot(interval_seconds: int, max_ticks: int | None = None) -> None:
    print(f"researcher autopilot · interval={interval_seconds}s · max_ticks={max_ticks or '∞'}")
    tick = 0
    while max_ticks is None or tick < max_ticks:
        cid = pick_next_clause()
        if cid is None:
            print(f"[tick {tick}] no candidate clause; sleeping")
        else:
            try:
                note = run_one_pass(cid)
                print(f"[tick {tick}] {cid} pass #{note['pass_number']} ({note['pass_kind']}) → {len(note.get('findings',[]))} findings")
            except Exception as e:  # noqa: BLE001
                print(f"[tick {tick}] {cid} FAILED: {e}")
        tick += 1
        time.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bataille background researcher")
    p.add_argument("--once", metavar="CLAUSE_ID", help="run a single pass on a clause and exit")
    p.add_argument("--pass-kind", choices=PASS_KINDS, help="explicit pass kind (default: auto-progress)")
    p.add_argument("--provider", default="gemini", choices=["gemini", "groq"])
    p.add_argument("--model")
    p.add_argument("--autopilot", action="store_true", help="run the pick-next-and-research loop")
    p.add_argument("--interval", type=int, default=60, help="autopilot tick interval seconds")
    p.add_argument("--max-ticks", type=int, default=None)
    p.add_argument("--pin", metavar="CLAUSE_ID", help="pin a clause for priority research")
    p.add_argument("--unpin", metavar="CLAUSE_ID")
    p.add_argument("--list-notes", metavar="CLAUSE_ID")
    a = p.parse_args(argv)

    # ensure server-style .env load so keys are available when run standalone
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

    if a.pin:
        print(set_pinned(a.pin, True))
        return 0
    if a.unpin:
        print(set_pinned(a.unpin, False))
        return 0
    if a.list_notes:
        for n in read_notes(a.list_notes):
            print(json.dumps(n, ensure_ascii=False, indent=2))
        return 0
    if a.once:
        note = run_one_pass(a.once, a.pass_kind, a.provider, a.model)
        print(json.dumps(note, ensure_ascii=False, indent=2))
        return 0
    if a.autopilot:
        autopilot(a.interval, a.max_ticks)
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
