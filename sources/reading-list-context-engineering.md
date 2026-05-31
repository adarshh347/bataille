# Reading list — context engineering & information retrieval, for this project

*Curated 2026-05-29. Filter: pieces that bear directly on what we're
building — a multi-pass researcher that accumulates structured notes per
clause, with prompt-schemas as the contract, sqlite arriving when relational
queries do, vector arriving when paragraph→clause retrieval becomes the
question. Skipped: anything in the "ten LLM prompting tips" register.*

> One-line takeaway under each entry: **why this matters for *us***, not
> just why it's a good piece in general.

## I. Context engineering — the discipline that replaces "prompt engineering"

1. **Andrej Karpathy — "Context is the new prompt" framing** (look for his
   tweets / talks from 2024 onward on the move from prompt-as-instruction to
   context-as-curated-environment).
   - *For us:* the researcher is exactly this — its job is to curate what the
     model sees per pass, not to "prompt better."

2. **Anthropic — "Effective context engineering for agents"** (engineering
   blog, late 2025). The canonical framing of context budget, context
   compression, sub-agents-as-context-managers.
   - *For us:* the autopilot loop must compress prior passes before
     re-injecting them (we already do `prior_passes_summary`); this piece
     covers the failure modes we'll hit at pass ~10.

3. **Anthropic — "Building effective AI agents"** (Dec 2024). Workflow
   vs. agent, the augmented-LLM, why orchestration > autonomy for
   reliability.
   - *For us:* the researcher is a *workflow* (deterministic pass-progression),
     not an agent. Knowing why we chose that is half the design.

4. **Lance Martin (LangChain) — "Context engineering for agents"** (mid-2025
   blog series). The four moves: write, select, compress, isolate.
   - *For us:* `internal-cross-corpus` is "select"; `synthesis` is "compress";
     per-pass JSONL files are "isolate"; pass schemas are "write."

## II. Structured output — making JSON-mode reliable

5. **OpenAI — "Introducing Structured Outputs in the API"** (Aug 2024) +
   the JSON Schema subset they support.
   - *For us:* our Groq path uses `response_format: json_object` (looser
     than full structured-output). Groq supports the strict mode on some
     models — worth testing whether `gpt-oss-120b` accepts the strict path.

6. **Google — Gemini structured output / responseSchema docs.**
   - *For us:* directly relevant; the `_gemini_clean_schema` workaround in
     `researcher.py` exists because Gemini rejects `$schema`, `$id`,
     `additionalProperties`. Read the official subset list when extending.

7. **"Outlines" library + "guidance" (Microsoft) papers.** Constrained
   decoding as a *grammar* enforced at the token level, not just JSON-mode.
   - *For us:* probably not needed yet. Worth knowing exists for when
     pass-kind-specific sub-grammars matter (e.g. citations must match
     `<file>:<line>`).

## III. Retrieval — when (and when not) to add RAG

8. **Anthropic — "Contextual Retrieval"** (Sep 2024). Chunk + contextual
   prepend + embeddings + BM25 + rerank. ~67% reduction in retrieval failures
   over naive embedding-only.
   - *For us:* the exact recipe to follow when we add the
     paragraph→clause retrieval feature. BM25 + embeddings is the
     production-grade baseline; we should not skip BM25 thinking we can
     "just use vectors."

9. **Lewis et al. — "Retrieval-Augmented Generation for
   Knowledge-Intensive NLP Tasks"** (RAG, 2020). The original.
   - *For us:* skim, don't deep-read. Foundational vocabulary, dated
     specifics.

10. **Liu et al. — "Lost in the Middle: How Language Models Use Long
    Contexts"** (Stanford, 2023). Models retrieve well from the start and
    end of a long context, poorly from the middle.
    - *For us:* affects how we build the `internal-cross-corpus` user
      message — put the *most likely echo* nearest the start, not in
      alphabetical file order.

11. **Anthropic — "Long context prompting tips."** Place the long doc
    first, the question last. Use XML tags for structure.
    - *For us:* the READ endpoint already does this (book first, lens
      question last); audit `researcher.build_user_message` against it.

## IV. The shape of memory for long-running agents

12. **Anthropic — "Claude Code's memory system" / agent memory writeups**
    (2025). File-based long-term memory > vector store for *user* memory;
    semantic search is for *knowledge*, files are for *facts about you*.
    - *For us:* directly mirrors `~/.claude/.../memory/*.md` we already
      have. The researcher's per-clause files are *knowledge memory*;
      `MEMORY.md` is *user/process memory*. Two stores, different shapes.

13. **MemGPT (Berkeley, late 2023 / early 2024 paper).** The OS metaphor:
    main context as RAM, external store as disk, with paging.
    - *For us:* one possible future for the agent built from this dossier
      — but not now. Read for vocabulary.

## V. Embeddings & vector stores (read when sqlite migration lands)

14. **Asahi Ushio / various — embedding model comparisons 2025.** What's
    state-of-the-art at small dims (256–768) for English+French mixed
    corpora (we have French Bataille quotes).
    - *For us:* informs the choice when we wire embeddings.

15. **`sqlite-vec` GitHub + Alex Garcia's writeup.** Vector search inside
    SQLite, single binary, no separate process.
    - *For us:* this is what we should reach for when paragraph→clause
      retrieval becomes a real question. Don't add chromadb/qdrant unless
      sqlite-vec proves insufficient.

## VI. Things to know about but probably *not* implement here

16. **DSPy (Stanford).** Treat prompts as differentiable; compile pipelines.
    - *For us:* the "treat the LLM call as a function with a typed
      interface" philosophy is the right one — and it's exactly what our
      schemas + pass-kinds already model. Reading DSPy would tempt
      premature abstraction.

17. **Knowledge graphs / Neo4j / TigerGraph for RAG.** The graph-RAG vogue
    of 2024–2025.
    - *For us:* probably not. Our clause→research→essay→promotion
      relationships are a tree, not a graph, and sqlite + foreign keys
      cover trees fine.

## Reading order if you have 90 minutes

1. Anthropic "Effective context engineering" (45 min — read carefully)
2. Anthropic "Contextual Retrieval" (20 min — skim recipes, save details)
3. Liu et al. "Lost in the Middle" (15 min — read the figures)
4. `sqlite-vec` README + one blog post on it (10 min — for when we
   migrate)

## Reading order if you have 4 hours

Add: Lance Martin's series (1 hr), "Building effective AI agents" (45
min), MemGPT (skim 30 min), one structured-output deep-dive (30 min),
30-min skim of two embedding-comparison posts.

## Open questions to read with in mind

- *When do we need a reranker?* (Probably the moment we add embeddings; a
  cross-encoder rerank on top of embedding recall is the standard
  production recipe.)
- *How do we evaluate the researcher?* (LLM-as-judge with a rubric is the
  cheap path; pinning ground-truth research notes for ~10 clauses and
  comparing is the rigorous one. Probably the first; consider the second
  if we ever fine-tune.)
- *Where does the "agent built from this dossier" actually live?* (This
  reading list assumes the answer is a multi-pass orchestration on top of
  Claude/Gemini, not a fine-tune. Worth revisiting once we have ~1000
  research notes — fine-tuning a small open model on our own dossier may
  become attractive.)
