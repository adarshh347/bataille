# sandbox/schemas — prompt-schemas

These JSON Schemas define the shape of every structured LLM output in the
sandbox. The point is not validation paranoia; it is **diffuse intelligence**:

- The LLM is given the schema as part of its prompt and asked to produce
  matching JSON. Structured output mode (Gemini `responseMimeType:
  "application/json"` + `responseSchema`, OpenAI / Groq `response_format: {type:
  "json_schema", ...}`) enforces the shape at the model level.
- The UI renders cleanly from known fields instead of parsing markdown.
- Downstream agents (the background researcher; later passes; the agent
  itself) can consume earlier output deterministically.
- The schema *is* the contract — when we change the shape, we change one file
  and the change propagates.

## Versioning

Every schema has a `$id` of the form `bataille://schema/<name>/v<n>`. When a
breaking change is needed, bump the version and keep the prior file; the
sandbox should accept the latest by default but be able to read older
research notes / essays without crashing.

## Current schemas

| File | Used by | Shape note |
|---|---|---|
| `clause.json` | `extract_clauses.py`, `clauses.json` | Source-of-truth shape for a dossier clause. New outward tags (⊕/⊗/⚑) live in `outward_tags`. |
| `essay_structured.json` | `/api/read` structured branch | Numbered findings with quotes + page refs + lens_relation. Includes `research_seeds` so essays feed the researcher inbox. |
| `essay_narrative.json` | `/api/read` narrative branch | Thin metadata envelope around a markdown body. Forces hook / turn / ends-on. |
| `research_note.json` | background researcher | One research pass. Append-only stream per clause. `pass_kind` distinguishes internal-cross-corpus vs external-web vs kin-finding etc. |

## Adding a schema

1. Drop a new `<name>.json` here, `$id` = `bataille://schema/<name>/v1`.
2. Reference it from the relevant Python prompt-builder (see
   `server.py`'s `build_structured_output_config()`).
3. Add a row to the table above.
4. Match-test: produce a sample with the model, validate locally with
   `jsonschema` (stdlib `json` is enough for shape, but `jsonschema` catches
   the constraints).

## When to NOT add a schema

If the only thing varying between outputs is free-form prose with no fields
the UI or a downstream agent will key on, do not schematize. Schemas are for
contracts; everything else is just text.
