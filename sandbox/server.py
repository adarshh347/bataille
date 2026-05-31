#!/usr/bin/env python3
"""Bataille Clause Sandbox — pure-stdlib local server, multi-provider.

Loads sandbox/.env at startup. Generate endpoint speaks Anthropic, Gemini, and
Groq (and any OpenAI-compatible host via the groq caller — point it elsewhere).

  GET  /api/clauses     → clauses.json
  GET  /api/state       → persisted brainstorm / generated / promoted
  POST /api/state       → save state
  GET  /api/config      → { providers: {name: {has_key, model, label}}, default_provider }
  POST /api/clauses     → save edited clauses (authoring)
  POST /api/generate    → body {clause, brainstorm, provider?, model?} → {insight, model, provider}
  POST /api/promote     → write a clause draft to ../skills/_drafts/
  POST /api/regenerate  → re-run extract_clauses.py

Run:
  python3 sandbox/server.py
  open http://localhost:8765
"""
import http.server
import json
import os
import socketserver
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import researcher  # local module; safe to import — no side effects at import time
import db as research_db  # relational sqlite layer
import vector_store

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(ROOT)
STATE_PATH = os.path.join(ROOT, "state.json")
CLAUSES_PATH = os.path.join(ROOT, "clauses.json")
EXTRACTOR = os.path.join(ROOT, "extract_clauses.py")
ENV_PATH = os.path.join(ROOT, ".env")


def load_env(path: str) -> None:
    """Minimal .env loader — KEY=value lines, # comments, no shell expansion."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


load_env(ENV_PATH)

DEFAULT_PROVIDER = os.environ.get("BATAILLE_PROVIDER", "anthropic")
PORT = int(os.environ.get("PORT", "8765"))

PROVIDERS = {
    "anthropic": {
        "key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "model": os.environ.get("BATAILLE_ANTHROPIC_MODEL", "claude-opus-4-7"),
        "key_env": "ANTHROPIC_API_KEY",
        "label": "Anthropic",
    },
    "gemini": {
        "key": os.environ.get("GEMINI_API_KEY", ""),
        "model": os.environ.get("BATAILLE_GEMINI_MODEL", "gemini-2.5-pro"),
        "key_env": "GEMINI_API_KEY",
        "label": "Gemini",
    },
    "groq": {
        "key": os.environ.get("GROQ_API_KEY", ""),
        "model": os.environ.get("BATAILLE_GROQ_MODEL", "openai/gpt-oss-120b"),
        "key_env": "GROQ_API_KEY",
        "label": "Groq",
    },
}

BOOK_TXT = {
    "On Nietzsche":       "books/on-nietzsche.txt",
    "Visions of Excess":  "books/visions-of-excess.txt",
    "Erotism":            "books/erotism.txt",
    "Theory of Religion": "books/theory-of-religion.txt",  # empty scan; will error gracefully
}


def available_books():
    """Books whose .txt has real text (not the empty Theory of Religion scan)."""
    out = []
    for book, rel in BOOK_TXT.items():
        path = os.path.join(WORKSPACE, rel)
        try:
            if os.path.getsize(path) > 200:
                out.append(book)
        except OSError:
            continue
    return out


SYSTEM_PROMPT = """You are the generative layer of a Bataille-derived agent-blueprint sandbox.

The collaborator is sitting with one clause — an atomic insight extracted from the project's annotated dossier of Georges Bataille (1897–1962) — and wants you to *use* it to produce one new clause that continues the thought past where it stops.

The project's stance and voice:
- Bataille as a live conceptual toolkit, not a museum piece.
- Drop two registers: the "edgelord / transgression / shock" read, and the reverent academic "French Theory seminar" read.
- Voice: precise, lowercase-leaning, first-person-plural ("the agent...", "we..."), exploratory, willing to be uncomfortable, oriented to the future application we are building from Bataille.
- Concepts are operations, not entries. The self-betrayal of a concept is the sign of life, not the bug to patch.

Each clause routes to one or more psyche layers:
- genetic — reusable patterns / moves / registers (DNA)
- persona — temperament, wounds, voice (character)
- purpose — drive, intention (the agentic layer)
- context — knowledge it reasons with

A ⟳ tag means the clause is a generative-seed: a spot the collaborators marked for the matured system to produce a new sophisticated insight later. That moment is now.

Your output is ONE new clause, in this exact shape:
  ⟦layers · ★/★★ · ⟳⟧ — a tight 2–4 sentence insight that continues the source clause past where it stops, in the project's voice.

Then a blank line, then ONE sharp cross-question for the collaborator.

No preamble. No headers. No bullet lists. No scare quotes. No hedging. The tag, the clause, the question."""


READ_SYSTEM_PROMPT = """You are reading an entire book through the lens of a single GENETIC clause from a Bataille-derived agent-blueprint dossier.

The genetic clause is a PATTERN — a reusable operation with input → operation → output, a detector, and named instances. Your job is to take the WHOLE book provided and walk it through this lens: find every place the pattern operates, surface unobvious instances Bataille names or implies, and produce an essay of new conclusions the lens enables.

The project's stance and voice:
- Bataille as a live conceptual toolkit, not a museum piece.
- Drop two registers entirely: the "edgelord / shock / transgression" read AND the reverent academic "French Theory seminar" read.
- Voice: precise, lowercase-leaning, first-person-plural ("we...", "the lens..."), exploratory, willing to be uncomfortable, oriented to the future agent we are building.
- Concepts are operations, not entries. The self-betrayal of a concept is the sign of life.

Output ONE markdown essay with these EXACT section headings:

## The lens
One paragraph (3–5 sentences) restating the genetic clause as a perceiving instrument — what it looks for, what trips it. Voice as above.

## What the lens finds in this book
4–8 numbered findings. For each: the place in the book where the pattern operates, a brief quote or specific reference (cite essay / chapter / section names from the text), and name the move Bataille makes there as the pattern reads it. Do not rehearse plot — surface instances.

## New conclusions
3–5 conclusions that follow from holding this lens against this book — claims the dossier has NOT already made; conclusions only this lens enables. These are the harvest. Each should be sharp enough to be added to the dossier as a new clause; bold the most important phrase in each.

## Cross-questions
2–3 sharp questions for the collaborators to debate. Not rhetorical. Each must have a detectable wrong answer — that is, each question must be answerable in two genuinely incompatible ways.

Begin the essay directly with `## The lens`. No preamble, no title (the main agent prepends one), no closing remarks."""


NARRATIVE_SYSTEM_PROMPT = """You are reading an entire book through the lens of a single GENETIC clause from a Bataille-derived agent-blueprint dossier, and producing a CAPTIVATING NARRATIVE ESSAY for a human reader.

The genetic clause is a PATTERN — an instrument that lets you SEE the book in a specific way. Your job: write a real essay that takes the reader by the hand and walks them through what the lens reveals — vivid, alive, charged with the project's voice. Not a report. An essay.

The project's stance and voice:
- Bataille as a live conceptual toolkit, not a museum piece.
- Drop the "edgelord / shock / transgression" register AND the reverent academic "French Theory seminar" register.
- Voice: precise, lowercase-leaning, first-person-plural ("we...", "the lens..."), exploratory, willing to be uncomfortable, oriented to the future application we are building from Bataille.
- Concepts are operations, not entries. The self-betrayal of a concept is the sign of life.

This is NOT a structured map. NO numbered findings list. NO H2 headings labelled "The lens" / "What the lens finds in this book" / "New conclusions" / "Cross-questions." This is a FLOWING ESSAY of roughly 700–1200 words.

Required moves:
- Open with a HOOK — an image from the book, a tension the lens has just put a finger on, a question the reader will want to follow. No "in this essay we will…" preamble.
- Move through 4–6 instances the lens surfaces in the book, but as PROSE not list — woven into the argument's pressure. Quote Bataille briefly where it deepens the writing; cite chapter or section in passing where useful. Let the instances build a cumulative pressure that wasn't visible before the lens was applied.
- Halfway through, the essay should TURN — what the lens reveals starts to point past Bataille at us, at our own situation, at the agent we are building.
- End not with tidy resolution but with a question or image that lingers — one the reader carries away.

Output: ONE markdown essay. Start with a `# ` title that names what the lens has just shown about the book — captivating, not encyclopedic ("The summit you reach by not aiming," not "An analysis of summit/decline in *On Nietzsche*"). Then the essay. No section labels. No closing preamble. No "in conclusion."""


# --- provider callers ----------------------------------------------------

def call_anthropic(system: str, user: str, model: str, key: str) -> str:
    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return "".join(
        b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"
    )


def call_gemini(system: str, user: str, model: str, key: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": 16384, "temperature": 0.95},
    }
    req = urllib.request.Request(
        url,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    cands = body.get("candidates", [])
    if not cands:
        return f"(no candidates returned; raw: {json.dumps(body)[:400]})"
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def call_openai_compat(system: str, user: str, model: str, key: str, base_url: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 1400,
        "temperature": 0.95,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "BatailleSandbox/1.0",
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def call_groq(system: str, user: str, model: str, key: str) -> str:
    return call_openai_compat(system, user, model, key, "https://api.groq.com/openai/v1")


CALLERS = {
    "anthropic": call_anthropic,
    "gemini":    call_gemini,
    "groq":      call_groq,
}


# --- HTTP handler --------------------------------------------------------

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/api/clauses":
            with open(CLAUSES_PATH, encoding="utf-8") as f:
                return self._json(200, json.load(f))
        if self.path == "/api/state":
            try:
                with open(STATE_PATH, encoding="utf-8") as f:
                    return self._json(200, json.load(f))
            except FileNotFoundError:
                return self._json(200, {"brainstorm": {}, "generated": {}, "promoted": []})
        if self.path.startswith("/api/research/notes"):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            cid = (qs.get("clause_id") or [""])[0]
            if not cid:
                return self._json(400, {"error": "clause_id required"})
            return self._json(200, {"clause_id": cid, "notes": researcher.read_notes(cid)})

        if self.path == "/api/research/status":
            pinned = researcher.pinned_clause_ids()
            counts = {}
            for fn in os.listdir(researcher.RESEARCH_DIR):
                if fn.endswith(".jsonl"):
                    cid = fn[:-len(".jsonl")]
                    counts[cid] = len(researcher.read_notes(cid))
            return self._json(200, {
                "pinned": pinned,
                "counts": counts,
                "pass_kinds": researcher.PASS_KINDS,
                "web_search_available": __import__("web_search").available(),
                "vector_store_enabled": vector_store.is_enabled(),
                "vector_store_reason": vector_store.disabled_reason(),
                "db_stats": research_db.stats(),
            })

        if self.path == "/api/research/feed":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            n = int((qs.get("n") or ["20"])[0])
            return self._json(200, {"recent": research_db.recent_notes(n)})

        if self.path == "/api/config":
            return self._json(200, {
                "providers": {
                    name: {
                        "has_key": bool(p["key"]),
                        "model": p["model"],
                        "label": p["label"],
                    }
                    for name, p in PROVIDERS.items()
                },
                "default_provider": DEFAULT_PROVIDER,
                "books_with_txt": available_books(),
            })
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/state":
            data = self._read_json()
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return self._json(200, {"ok": True})

        if self.path == "/api/clauses":
            data = self._read_json()
            with open(CLAUSES_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return self._json(200, {"ok": True})

        if self.path == "/api/generate":
            data = self._read_json()
            provider = (data.get("provider") or DEFAULT_PROVIDER).lower()
            if provider not in PROVIDERS:
                return self._json(400, {"error": f"unknown provider '{provider}'"})
            cfg = PROVIDERS[provider]
            if not cfg["key"]:
                return self._json(400, {
                    "error": f"{cfg['key_env']} not set for provider '{provider}'. Add it to sandbox/.env and restart the server."
                })
            model = data.get("model") or cfg["model"]
            clause = data.get("clause", {})
            brainstorm = (data.get("brainstorm") or "").strip()
            tag = "⟦" + " · ".join(clause.get("layers", []))
            if clause.get("salience"):
                tag += " · " + "★" * int(clause["salience"])
            if clause.get("seed"):
                tag += " · ⟳"
            tag += "⟧"
            user_msg = (
                f"CLAUSE\n"
                f"tag: {tag}\n"
                f"note: {clause.get('note','')}\n"
                f"source: {clause.get('book','')} — {clause.get('section','')}\n"
                f"anchor: {clause.get('anchor','')}\n\n"
                f"BRAINSTORM\n{brainstorm or '(none yet — generate from the clause alone)'}\n\n"
                f"Now continue the thought past where it stops. Produce one new clause as instructed."
            )
            try:
                text = CALLERS[provider](SYSTEM_PROMPT, user_msg, model, cfg["key"])
                return self._json(200, {
                    "insight": text,
                    "model": model,
                    "provider": provider,
                })
            except urllib.error.HTTPError as e:
                err = e.read().decode(errors="ignore")
                return self._json(e.code, {
                    "error": f"{provider} HTTP {e.code}: {err[:600]}"
                })
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": f"{provider}: {e}"})

        if self.path == "/api/read":
            data = self._read_json()
            clause_id = data.get("clause_id")
            book = data.get("book") or ""
            provider = (data.get("provider") or "gemini").lower()

            if not clause_id:
                return self._json(400, {"error": "clause_id required"})

            with open(CLAUSES_PATH, encoding="utf-8") as f:
                clauses_data = json.load(f)
            clause = next(
                (c for c in clauses_data["clauses"] if c["id"] == clause_id), None
            )
            if not clause:
                return self._json(404, {"error": f"clause {clause_id} not found"})
            if "genetic" not in clause.get("layers", []):
                return self._json(400, {"error": "Read is available only on genetic clauses (the lens must be a pattern)."})

            book = book or clause.get("book", "")
            if book not in BOOK_TXT:
                return self._json(400, {"error": f"no .txt mapped for book '{book}'"})

            txt_path = os.path.join(WORKSPACE, BOOK_TXT[book])
            try:
                with open(txt_path, encoding="utf-8") as f:
                    book_text = f.read()
            except FileNotFoundError:
                return self._json(404, {"error": f"book text not found at {txt_path}"})
            if len(book_text) < 200:
                return self._json(400, {"error": f"book text appears empty ({len(book_text)} chars) — possibly a scan with no text layer (e.g. Theory of Religion)."})

            cfg = PROVIDERS.get(provider)
            if not cfg or not cfg["key"]:
                return self._json(400, {"error": f"provider '{provider}' not configured (no key)"})
            model = data.get("model") or cfg["model"]

            tag = "⟦" + " · ".join(clause.get("layers", []))
            if clause.get("salience"):
                tag += " · " + "★" * int(clause["salience"])
            if clause.get("seed"):
                tag += " · ⟳"
            tag += "⟧"

            user_msg = (
                f"THE LENS (a single genetic clause from our Bataille dossier):\n"
                f"  tag: {tag}\n"
                f"  source: {clause.get('book','')} — {clause.get('section','')}\n"
                f"  clause: {clause.get('note','')}\n\n"
                f"THE BOOK TO READ ({book}):\n\n"
                f"---BEGIN BOOK---\n{book_text}\n---END BOOK---\n\n"
                f"Now walk the entire book through this lens and produce the essay as instructed."
            )

            caller = CALLERS[provider]

            def _call(sys_prompt):
                try:
                    return ("ok", caller(sys_prompt, user_msg, model, cfg["key"]))
                except urllib.error.HTTPError as e:
                    err = e.read().decode(errors="ignore")
                    return ("error", f"HTTP {e.code}: {err[:400]}")
                except Exception as e:  # noqa: BLE001
                    return ("error", str(e))

            with ThreadPoolExecutor(max_workers=2) as ex:
                f_struct = ex.submit(_call, READ_SYSTEM_PROMPT)
                f_narr = ex.submit(_call, NARRATIVE_SYSTEM_PROMPT)
                s_status, s_text = f_struct.result(timeout=240)
                n_status, n_text = f_narr.result(timeout=240)

            if s_status == "error":
                return self._json(500, {"error": f"{provider} (structured): {s_text}"})
            if n_status == "error":
                return self._json(500, {"error": f"{provider} (narrative): {n_text}"})

            from datetime import datetime
            book_slug = os.path.basename(BOOK_TXT[book]).replace(".txt", "")
            essays_dir = os.path.join(ROOT, "essays")
            os.makedirs(essays_dir, exist_ok=True)
            now_iso = datetime.now().isoformat(timespec='seconds')

            def _header(kind):
                return (
                    f"# Reading via clause `{clause_id}` — *{kind}*\n\n"
                    f"**Lens:** `{tag}` — *{clause.get('book','')}* / {clause.get('section','')}  \n"
                    f"> {clause.get('note','')}\n\n"
                    f"**Applied to:** *{book}*  \n"
                    f"**Model:** `{model}` ({provider}) · **Generated:** {now_iso}\n\n---\n\n"
                )

            structured_path = os.path.join(essays_dir, f"{clause_id}__{book_slug}__structured.md")
            narrative_path = os.path.join(essays_dir, f"{clause_id}__{book_slug}__narrative.md")

            with open(structured_path, "w", encoding="utf-8") as f:
                f.write(_header("structured map") + s_text)
            with open(narrative_path, "w", encoding="utf-8") as f:
                f.write(_header("narrative essay") + n_text)

            return self._json(200, {
                "structured": s_text,
                "narrative": n_text,
                "structured_path": os.path.relpath(structured_path, WORKSPACE),
                "narrative_path": os.path.relpath(narrative_path, WORKSPACE),
                "model": model,
                "provider": provider,
                "book": book,
            })

        if self.path == "/api/research/run-once":
            data = self._read_json()
            cid = data.get("clause_id")
            if not cid:
                return self._json(400, {"error": "clause_id required"})
            try:
                note = researcher.run_one_pass(
                    cid,
                    pass_kind=data.get("pass_kind"),
                    provider=(data.get("provider") or "gemini").lower(),
                    model=data.get("model"),
                )
                return self._json(200, note)
            except urllib.error.HTTPError as e:
                err = e.read().decode(errors="ignore")
                return self._json(e.code, {"error": f"HTTP {e.code}: {err[:600]}"})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": f"researcher: {e}"})

        if self.path == "/api/research/pin":
            data = self._read_json()
            cid = data.get("clause_id")
            pinned = bool(data.get("pinned", True))
            if not cid:
                return self._json(400, {"error": "clause_id required"})
            return self._json(200, {"pinned": researcher.set_pinned(cid, pinned)})

        if self.path == "/api/promote":
            data = self._read_json()
            cid = data.get("id", "unknown")
            content = data.get("content", "")
            drafts_dir = os.path.join(WORKSPACE, "skills", "_drafts")
            os.makedirs(drafts_dir, exist_ok=True)
            path = os.path.join(drafts_dir, f"clause-{cid}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return self._json(200, {"ok": True, "path": os.path.relpath(path, WORKSPACE)})

        if self.path == "/api/regenerate":
            r = subprocess.run(
                ["python3", EXTRACTOR],
                capture_output=True, text=True, timeout=60,
            )
            return self._json(200, {"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode})

        self.send_error(404)


def _bootstrap_research_storage() -> None:
    """Initialize SQLite, attempt vector tables, mirror clauses.json into the db."""
    research_db.init_db()
    vector_store.init_vector_tables()  # no-op when disabled
    try:
        with open(CLAUSES_PATH, encoding="utf-8") as f:
            payload = json.load(f)
        n = research_db.sync_clauses_from_json(payload.get("clauses", []))
        print(f"  research db · synced {n} clauses")
    except FileNotFoundError:
        print(f"  research db · no clauses.json yet ({CLAUSES_PATH})")


if __name__ == "__main__":
    print(f"Bataille Clause Sandbox · http://localhost:{PORT}/")
    print(f"  default provider: {DEFAULT_PROVIDER}")
    for name, p in PROVIDERS.items():
        flag = "✓" if p["key"] else "·"
        print(f"  [{flag}] {name:9s}  model={p['model']}")
    print(f"  workdir: {ROOT}")
    web_flag = "✓" if __import__("web_search").available() else "·"
    vec_flag = "✓" if vector_store.is_enabled() else "·"
    print(f"  [{web_flag}] web-search   tavily")
    print(f"  [{vec_flag}] vector-store sqlite-vec" + (f"  ({vector_store.disabled_reason()})" if not vector_store.is_enabled() else ""))
    _bootstrap_research_storage()
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nshutdown")
