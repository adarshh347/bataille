# Background researcher — design

*Written 2026-05-29 alongside the first working scaffold (`researcher.py`,
`/api/research/*` endpoints). This doc records the design choices so a later
session can extend without re-deriving the rationale.*

## What it is

A long-running process that picks clauses from the dossier and produces
**research notes** for them, slowly accumulating depth one pass at a time.
The user marks clauses worth attention by **pinning**; the researcher prefers
pinned, then falls back to ⟳/⚑/⊕-tagged clauses with no research yet, then
random under-researched genetic clauses.

Each pass answers a *different question*. The pass kinds:

| kind | answers | depends on |
|---|---|---|
| `internal-cross-corpus` | where does this lens echo *elsewhere in our knowledge files*? | nothing external |
| `kin-finding` | which philosophical kin perform the same gesture? (⊗) | model's training knowledge |
| `outward-projection` | non-bataille, ideally non-western, instances of this structure (⊕) | model's training knowledge |
| `install-deep-test` | does the lens really rewire perception of a fresh 2026 phenomenon? (⚑) | nothing external |
| `external-web` | live sources from the open web | needs a web tool (not yet wired) |
| `synthesis` | given N prior passes, what does the dossier now know? | prior passes in the file |

Default auto-progression on an un-touched clause: internal → kin → outward →
synthesis, then repeat. Explicit `--pass-kind` overrides.

## Storage — why JSONL, why not sqlite *yet*

Per clause: `sandbox/research/<clause-id>.jsonl`, one JSON object per line,
append-only.

JSONL was picked for these reasons:
- **One write, no migration.** Append-only is the simplest possible model;
  it cannot corrupt prior passes mid-write.
- **Cheap to inspect.** `cat`, `jq`, `git diff` all work.
- **Concurrency-safe enough.** Single writer per file (the researcher is the
  only writer); readers see the file as it stands at open time. We don't
  need transactions or row locking until we have multi-writer workloads.

We **will** want sqlite once any of these is true:
1. **Cross-clause queries become common.** "Show me every research note where
   `pass_kind = outward-projection` and `findings[*].source_kind =
   comparative-tradition`." Walking 100 JSONL files is fine; walking 5000 is
   not.
2. **The UI wants `ORDER BY recent` across all clauses.** A research feed.
3. **The vector store arrives.** Vector DBs (chromadb, qdrant, sqlite-vec)
   want a metadata store next to the embeddings; sqlite is the natural
   companion.

Migration plan: a single `migrations/001_jsonl_to_sqlite.py` walks every
`research/*.jsonl`, inserts rows into `research_notes(clause_id, pass_number,
pass_kind, generated_at, payload_json)`. Researcher's only changed code is
the four functions `research_file / append_note / read_notes /
next_pass_number` — `payload_json` keeps the full schema-valid object so we
never need to widen the table when the schema grows.

## Schema enforcement

Each pass is constrained to `schemas/research_note.json` two ways:

1. **At the model:** structured-output mode (`responseSchema` for Gemini,
   `response_format` for OpenAI/Groq). This usually works; when it doesn't,
   the LLM produces JSON-shaped output that still drifts in nested fields.
2. **At the writer:** `shape_validate()` runs a cheap top-level check. Failures
   are recorded as `warnings` on the note rather than dropped. We want to
   **see** the failure mode, not hide it.

When/if shape failures become common, swap `shape_validate()` for the
`jsonschema` library (small dep, optional install) — the call sites don't
change.

## Cadence — three modes, all served by the same primitive

`run_one_pass(clause_id, pass_kind=None, provider, model)` is the only
primitive. Cadence is just *who calls it and how often*:

- **Manual / button-driven.** UI fires `POST /api/research/run-once`. Used to
  seed a clause's research file or to ask for a specific pass kind.
- **Autopilot (in-process).** `researcher.autopilot(interval_seconds)` —
  picks the next clause, runs a pass, sleeps, repeats. Suitable for `nohup
  python3 researcher.py --autopilot --interval 60 &` while you work.
- **Cron / external scheduler.** `python3 researcher.py --once <clause_id>`
  on a schedule. The server doesn't need to know about it.

Recommended default for now: **manual + pinned-driven**. Autopilot is one
flag away when the dossier is stable enough that you want passive
deepening overnight. Don't autopilot before you have ~10 pinned clauses, or
you'll burn tokens on whatever the random picker grabs.

## Provider choice

`gemini-2.5-flash` is the default — 1M context (we need it for
internal-cross-corpus, which dumps every other knowledge file), fast, free
tier covers heavy use. Groq `gpt-oss-120b` is the alternative when we want
agentic / tool-using behavior (not yet leveraged).

Anthropic isn't enabled for the researcher by default because the user's
`.env` doesn't have a key and our token budgets are tighter there.

## Web search — the missing piece for `external-web`

Right now `external-web` returns a `warnings: ['no-web-access']` note. To
wire it: pick one of {Tavily, Exa, Brave Search, Serper.dev}, add a key
field to `.env`, add `web_search(query) -> list[result]` in `researcher.py`
behind a feature flag. The pass-system prompt then includes the search
results in the user message and the schema's `source_kind` resolves to
`"web"` with `source_ref` = the URL.

Cost note: web-search APIs are cheap (~$0.005/query); the LLM cost of
processing 5 search results is the real expense. Cap external-web passes at
1/clause/day initially.

## Vector store — the next step after sqlite

Use case that finally needs it: **"given an arbitrary paragraph in the
book, surface the 3 clauses whose lens most likely applies."** This is
exactly what RAG does well. Until that question is in play, vector adds
complexity without buying anything.

When the time comes: `sqlite-vec` (single binary, lives in the same db as
our metadata) > chromadb (separate server, but more features) for our
scale. Embed: `text-embedding-3-small` or Gemini's `text-embedding-004`,
512 dims is enough for our corpus size.

## Endpoints (current)

```
GET  /api/research/notes?clause_id=<id>     → {clause_id, notes: [...]}
GET  /api/research/status                   → {pinned, counts, pass_kinds}
POST /api/research/run-once                 → run_one_pass(...)
POST /api/research/pin                      → toggle pin
```

## Not yet built (intentionally)

- UI affordances: pin button on clauses, research feed panel, per-clause
  research drawer. Held until the user confirms cadence (autopilot vs
  pinned-only).
- The autopilot daemon as a managed sub-process of the server. Run it
  standalone for now; folding it in requires a graceful-shutdown story that
  is more complexity than the current phase wants.
- A `lock` or PID file so two researcher processes don't double-append. The
  current invariant — exactly one writer at a time — is enforced by the
  user not running multiple at once. Trivial to add when needed.

## Quick start

```bash
# pin a clause
python3 sandbox/researcher.py --pin book-erotism-027

# run one pass on it (auto-pick pass kind)
python3 sandbox/researcher.py --once book-erotism-027

# run a specific pass kind
python3 sandbox/researcher.py --once book-erotism-027 --pass-kind kin-finding

# autopilot for 5 ticks at 30s interval
python3 sandbox/researcher.py --autopilot --interval 30 --max-ticks 5

# inspect what's been accumulated
python3 sandbox/researcher.py --list-notes book-erotism-027
```

Or via the server:

```bash
curl -X POST http://localhost:8765/api/research/run-once \
  -H 'Content-Type: application/json' \
  -d '{"clause_id":"book-erotism-027","pass_kind":"outward-projection"}'

curl 'http://localhost:8765/api/research/notes?clause_id=book-erotism-027' | jq
```
