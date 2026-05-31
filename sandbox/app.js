// Bataille Clause Sandbox — vanilla JS, multi-provider + Read-with-lens

const state = {
  clauses: [],
  summary: { by_book: {}, by_layer: {} },
  filter: { block: 'all', star2: false, seed: false, q: '' },
  selected: null,
  brainstorm: {},
  generated: {},
  essays: {},
  promoted: [],
  config: { providers: {}, default_provider: 'anthropic', books_with_txt: [] },
  selectedProvider: null,
};

const $ = (id) => document.getElementById(id);
const escapeHTML = (s) =>
  (s || '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function anyProviderHasKey() {
  return Object.values(state.config.providers || {}).some((p) => p.has_key);
}

function firstUsableProvider() {
  const def = state.config.default_provider;
  if (state.config.providers?.[def]?.has_key) return def;
  const entry = Object.entries(state.config.providers || {}).find(([, p]) => p.has_key);
  return entry ? entry[0] : null;
}

async function load() {
  const [cl, st, cfg] = await Promise.all([
    fetch('/api/clauses').then((r) => r.json()),
    fetch('/api/state').then((r) => r.json()),
    fetch('/api/config').then((r) => r.json()),
  ]);
  state.clauses = cl.clauses;
  state.summary = cl.summary || { by_book: {}, by_layer: {} };
  state.brainstorm = st.brainstorm || {};
  state.generated = st.generated || {};
  state.essays = st.essays || {};
  state.promoted = st.promoted || [];
  state.config = cfg;
  state.selectedProvider = firstUsableProvider() || cfg.default_provider;
  renderStatus();
  renderBlocks();
  renderList();
  renderDetail();
}

function renderStatus() {
  const provs = Object.entries(state.config.providers || {})
    .map(([k, p]) => `${k}${p.has_key ? '·set' : '·–'}`)
    .join(' / ');
  $('status').textContent =
    `${state.clauses.length} clauses · ${provs} · default ${state.config.default_provider}`;
}

function renderBlocks() {
  const layers = ['genetic', 'persona', 'purpose', 'context'];
  const layerCounts = state.summary.by_layer || {};
  const bookCounts = state.summary.by_book || {};
  const seedCount = state.clauses.filter((c) => c.seed).length;
  const starCount = state.clauses.filter((c) => c.salience >= 2).length;

  $('blocks').innerHTML = `
    <div class="group">
      <div class="group-title">Blocks</div>
      <button data-block="all">All clauses<span class="count">${state.clauses.length}</span></button>
      ${layers.map((l) => `<button class="layer-${l}" data-block="layer:${l}">${l[0].toUpperCase() + l.slice(1)}<span class="count">${layerCounts[l] || 0}</span></button>`).join('')}
    </div>
    <div class="group">
      <div class="group-title">Quick filters</div>
      <button data-block="seed">⟳ generative seeds<span class="count">${seedCount}</span></button>
      <button data-block="star2">★★ high salience<span class="count">${starCount}</span></button>
    </div>
    <div class="group">
      <div class="group-title">Books</div>
      ${Object.entries(bookCounts).map(([b, n]) => `<button data-block="book:${escapeHTML(b)}">${escapeHTML(b)}<span class="count">${n}</span></button>`).join('')}
    </div>
  `;
  $('blocks').querySelectorAll('button').forEach((b) => {
    b.addEventListener('click', () => {
      state.filter.block = b.dataset.block;
      $('blocks').querySelectorAll('button').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      renderList();
    });
  });
  const def = $('blocks').querySelector('[data-block="all"]');
  if (def) def.classList.add('active');
}

function filterClauses() {
  const f = state.filter;
  return state.clauses.filter((c) => {
    if (f.block === 'all') {
    } else if (f.block === 'seed') {
      if (!c.seed) return false;
    } else if (f.block === 'star2') {
      if (c.salience < 2) return false;
    } else if (f.block.startsWith('layer:')) {
      const l = f.block.slice(6);
      if (!c.layers.includes(l)) return false;
    } else if (f.block.startsWith('book:')) {
      const b = f.block.slice(5);
      if (c.book !== b) return false;
    }
    if (f.star2 && c.salience < 2) return false;
    if (f.seed && !c.seed) return false;
    if (f.q) {
      const q = f.q.toLowerCase();
      const hay = (c.note + ' ' + c.anchor + ' ' + c.section + ' ' + c.book).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function tagsHTML(c) {
  const parts = c.layers.map((l) => `<span class="tag ${l}">${l}</span>`);
  if (c.salience >= 1) parts.push(`<span class="tag salience">${'★'.repeat(c.salience)}</span>`);
  if (c.seed) parts.push(`<span class="tag seed">⟳ seed</span>`);
  return parts.join('');
}

function snippet(s, n) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n).trim() + '…' : s;
}

function renderList() {
  const list = $('list');
  const items = filterClauses();
  if (!items.length) {
    list.innerHTML =
      '<div class="clause-card" style="cursor:default"><div class="preview" style="color:var(--fg-dimmer);font-style:italic">no clauses match these filters</div></div>';
    return;
  }
  list.innerHTML = items.map((c) => `
    <div class="clause-card${state.selected === c.id ? ' active' : ''}" data-id="${escapeHTML(c.id)}">
      <div class="tag-row">${tagsHTML(c)}</div>
      <div class="source">${escapeHTML(c.book)} · ${escapeHTML(c.section)}</div>
      <div class="preview">${escapeHTML(snippet(c.note, 180))}</div>
    </div>`).join('');
  list.querySelectorAll('.clause-card').forEach((card) => {
    card.addEventListener('click', () => {
      state.selected = card.dataset.id;
      renderList();
      renderDetail();
      card.scrollIntoView({ block: 'nearest' });
    });
  });
}

function providerOptionsHTML() {
  return Object.entries(state.config.providers || {})
    .map(([k, p]) => {
      const label = `${p.label}${p.has_key ? '' : ' · no key'}`;
      const selected = k === state.selectedProvider ? ' selected' : '';
      const disabled = p.has_key ? '' : ' disabled';
      return `<option value="${k}"${selected}${disabled}>${escapeHTML(label)}</option>`;
    })
    .join('');
}

function readBookOptionsHTML(c) {
  const available = state.config.books_with_txt || [];
  const defBook = available.includes(c.book) ? c.book : available[0];
  return available.map((b) =>
    `<option value="${escapeHTML(b)}"${b === defBook ? ' selected' : ''}>${escapeHTML(b)}</option>`
  ).join('');
}

function renderDetail() {
  const d = $('detail');
  const c = state.clauses.find((x) => x.id === state.selected);
  if (!c) {
    d.innerHTML =
      '<div class="empty">select a clause from the middle column<br><span class="dim">— or filter from the left by block, salience, ⟳-seed, or book</span></div>';
    return;
  }
  const brain = state.brainstorm[c.id] || '';
  const gens = state.generated[c.id] || [];
  const essays = state.essays[c.id] || [];
  const promoted = state.promoted.includes(c.id);
  const anyKey = anyProviderHasKey();
  const isGenetic = c.layers.includes('genetic');
  const hasGemini = state.config.providers?.gemini?.has_key;
  const booksAvailable = (state.config.books_with_txt || []).length > 0;

  d.innerHTML = `
    <div class="tag-row">${tagsHTML(c)}</div>
    <div class="source">${escapeHTML(c.book)} — ${escapeHTML(c.section)}<span class="id">${escapeHTML(c.id)}</span></div>
    <div class="note">${escapeHTML(c.note)}</div>
    ${c.anchor ? `<div class="anchor">${escapeHTML(c.anchor)}</div>` : ''}

    <h3>Brainstorm <span class="sub">— think into this clause; autosaves to <span class="dim">state.json</span></span></h3>
    <textarea id="brainstorm" placeholder="…">${escapeHTML(brain)}</textarea>
    <div class="actions"><span class="saved" id="saved-indicator"></span></div>

    <div class="section-divider"></div>

    <h3>Generative pass <span class="sub">— continue the clause past where it stops</span></h3>
    <div class="actions">
      <button class="primary" id="generate-btn" ${anyKey ? '' : 'disabled title="add a key to sandbox/.env and restart"'}>${anyKey ? 'Generate ▷' : 'Generate (no key set)'}</button>
      <span class="via-label">via</span>
      <select id="provider-select" class="provider-select">${providerOptionsHTML()}</select>
      <button id="promote-btn" ${promoted ? 'disabled' : ''}>${promoted ? 'Promoted ✓' : 'Promote → skills/_drafts/'}</button>
    </div>
    ${gens.map((g) => `
      <div class="gen-result">
        <div class="meta">${escapeHTML((g.provider || '') + ' · ' + (g.model || ''))} · ${new Date(g.ts).toLocaleString()}</div>${escapeHTML(g.text)}
      </div>`).join('')}

    ${isGenetic && booksAvailable ? `
    <div class="section-divider"></div>
    <h3>Read a book with this lens <span class="sub">— scan the whole .txt through this pattern; produce essay.md</span></h3>
    <div class="actions">
      <button class="primary" id="read-btn" ${hasGemini ? '' : 'disabled title="needs GEMINI_API_KEY for long-context reading"'}>${hasGemini ? 'Read ▷' : 'Read (no Gemini key)'}</button>
      <span class="via-label">apply to</span>
      <select id="read-book-select" class="provider-select">${readBookOptionsHTML(c)}</select>
      <span class="dim" style="font-size:11px;font-family:var(--sans)">via Gemini · long context</span>
    </div>
    ${essays.map((e, i) => {
      const eid = `essay-${c.id}-${i}`;
      if (e.narrative && e.structured) {
        const npath = e.narrative_path ? ` · <a href="/${escapeHTML(e.narrative_path.replace(/^sandbox\//, ''))}" target="_blank">narrative.md</a>` : '';
        const spath = e.structured_path ? ` · <a href="/${escapeHTML(e.structured_path.replace(/^sandbox\//, ''))}" target="_blank">structured.md</a>` : '';
        return `
        <div class="essay" data-eid="${eid}">
          <div class="meta">${escapeHTML(e.book)} · ${escapeHTML(e.provider || '')} · ${escapeHTML(e.model || '')} · ${new Date(e.ts).toLocaleString()}${npath}${spath}</div>
          <div class="essay-tabs">
            <button class="essay-tab active" data-eid="${eid}" data-mode="narrative">Narrative</button>
            <button class="essay-tab" data-eid="${eid}" data-mode="structured">Structured map</button>
          </div>
          <div class="essay-body active" data-eid="${eid}" data-mode="narrative">${escapeHTML(e.narrative)}</div>
          <div class="essay-body" data-eid="${eid}" data-mode="structured">${escapeHTML(e.structured)}</div>
        </div>`;
      }
      // legacy single-essay shape
      return `
        <div class="essay">
          <div class="meta">${escapeHTML(e.book)} · ${escapeHTML(e.provider || '')} · ${escapeHTML(e.model || '')} · ${new Date(e.ts).toLocaleString()}${e.path ? ` · <a href="/${escapeHTML(e.path.replace(/^sandbox\//, ''))}" target="_blank">${escapeHTML(e.path)}</a>` : ''}</div>
          <div class="essay-body">${escapeHTML(e.text || '')}</div>
        </div>`;
    }).join('')}
    ` : ''}

    <div class="section-divider"></div>

    <h3>Author <span class="sub">— edit the clause note; saves to <span class="dim">clauses.json</span></span></h3>
    <textarea id="edit-note">${escapeHTML(c.note)}</textarea>
    <div class="actions">
      <button id="save-clause-btn">Save edit</button>
      <span class="saved" id="edit-saved"></span>
    </div>
  `;

  const ta = $('brainstorm');
  ta.addEventListener('input', debounce(() => {
    state.brainstorm[c.id] = ta.value;
    saveState();
    $('saved-indicator').textContent = 'saved ' + new Date().toLocaleTimeString();
  }, 400));

  $('provider-select').addEventListener('change', (e) => {
    state.selectedProvider = e.target.value;
  });
  $('generate-btn').addEventListener('click', () => generate(c));
  $('promote-btn').addEventListener('click', () => promote(c));
  $('save-clause-btn').addEventListener('click', () => saveClauseEdit(c));
  if (isGenetic && $('read-btn')) {
    $('read-btn').addEventListener('click', () => readWithLens(c));
  }
  d.querySelectorAll('.essay-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      const eid = btn.dataset.eid;
      const mode = btn.dataset.mode;
      d.querySelectorAll(`.essay-tab[data-eid="${eid}"]`).forEach((b) =>
        b.classList.remove('active'));
      btn.classList.add('active');
      d.querySelectorAll(`.essay-body[data-eid="${eid}"]`).forEach((body) => {
        body.classList.toggle('active', body.dataset.mode === mode);
      });
    });
  });
}

let saveTimer = null;
function saveState() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fetch('/api/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        brainstorm: state.brainstorm,
        generated: state.generated,
        essays: state.essays,
        promoted: state.promoted,
      }),
    });
  }, 200);
}

async function generate(c) {
  const btn = $('generate-btn');
  const orig = btn.textContent;
  const provider = $('provider-select')?.value || state.selectedProvider;
  btn.disabled = true;
  btn.textContent = `generating via ${provider}…`;
  try {
    const r = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clause: c, brainstorm: state.brainstorm[c.id] || '', provider }),
    });
    const j = await r.json();
    if (j.error) { alert('Generation error:\n\n' + j.error); return; }
    state.generated[c.id] = state.generated[c.id] || [];
    state.generated[c.id].push({ text: j.insight, model: j.model, provider: j.provider, ts: Date.now() });
    saveState();
    renderDetail();
  } catch (e) {
    alert('Network error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function readWithLens(c) {
  const btn = $('read-btn');
  const orig = btn.textContent;
  const book = $('read-book-select')?.value || c.book;
  btn.disabled = true;
  btn.textContent = `reading ${book}… (this can take 30–90s)`;
  try {
    const r = await fetch('/api/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clause_id: c.id, book }),
    });
    const j = await r.json();
    if (j.error) { alert('Read error:\n\n' + j.error); return; }
    state.essays[c.id] = state.essays[c.id] || [];
    state.essays[c.id].push({
      book: j.book,
      narrative: j.narrative,
      structured: j.structured,
      narrative_path: j.narrative_path,
      structured_path: j.structured_path,
      model: j.model,
      provider: j.provider,
      ts: Date.now(),
    });
    saveState();
    renderDetail();
  } catch (e) {
    alert('Network error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function promote(c) {
  const gens = state.generated[c.id] || [];
  const tagStr =
    '⟦' + c.layers.join(' · ') +
    (c.salience ? ' · ' + '★'.repeat(c.salience) : '') +
    (c.seed ? ' · ⟳' : '') + '⟧';
  const content =
    `# Clause draft — ${c.id}\n\n` +
    `**Source:** ${c.book} — ${c.section}  \n` +
    `**Tag:** \`${tagStr}\`\n\n` +
    `## Clause\n\n${c.note}\n\n` +
    (c.anchor ? `## Anchor\n\n> ${c.anchor}\n\n` : '') +
    `## Brainstorm\n\n${state.brainstorm[c.id] || '_(none)_'}\n\n` +
    `## Generated insights\n\n` +
    (gens.length
      ? gens.map((g) => `### ${g.provider || ''} · ${g.model || ''} · ${new Date(g.ts).toISOString()}\n\n${g.text}\n`).join('\n')
      : '_(none)_') + '\n';

  const r = await fetch('/api/promote', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: c.id, content }),
  });
  const j = await r.json();
  if (j.ok) {
    if (!state.promoted.includes(c.id)) state.promoted.push(c.id);
    saveState();
    renderDetail();
  } else {
    alert('Promote failed: ' + JSON.stringify(j));
  }
}

async function saveClauseEdit(c) {
  const newNote = $('edit-note').value.trim();
  if (!newNote || newNote === c.note) return;
  c.note = newNote;
  const payload = {
    generated_from: 'edited in sandbox',
    count: state.clauses.length,
    summary: state.summary,
    clauses: state.clauses,
  };
  await fetch('/api/clauses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  $('edit-saved').textContent = 'saved ' + new Date().toLocaleTimeString();
  renderList();
}

$('q').addEventListener('input', debounce(() => {
  state.filter.q = $('q').value;
  renderList();
}, 180));
$('f-star2').addEventListener('change', () => {
  state.filter.star2 = $('f-star2').checked;
  renderList();
});
$('f-seed').addEventListener('change', () => {
  state.filter.seed = $('f-seed').checked;
  renderList();
});
$('regen').addEventListener('click', async () => {
  const btn = $('regen');
  btn.disabled = true;
  btn.textContent = 'extracting…';
  try {
    const r = await fetch('/api/regenerate', { method: 'POST' });
    const j = await r.json();
    if (j.code === 0) {
      await load();
      btn.textContent = '↻ re-extracted';
      setTimeout(() => (btn.textContent = '↻ re-extract'), 1500);
    } else {
      alert('re-extract failed:\n' + j.stderr);
      btn.textContent = '↻ re-extract';
    }
  } finally {
    btn.disabled = false;
  }
});

load();
