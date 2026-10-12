/* Admin pages: questions, characters, media library, interaction schemes */
'use strict';
(() => {
const FQ = window.FQ, h = FQ.h;

/* =========================================================== QUESTIONS */
const QS = { q: '', status: '', category_id: '', difficulty: '', sort: 'updated_at', order: 'desc', page: 1, page_size: 15 };

FQ.pages.questions = async (main) => {
  const cats = await FQ.api('/categories');
  const tableBox = h('div');
  const load = async () => {
    const p = new URLSearchParams(Object.entries(QS).filter(([, v]) => v !== '' && v !== null));
    const r = await FQ.api('/questions?' + p); renderTable(r);
  };
  const th = (label, key) => h('th', { class: key ? 'sort' : '', onclick: key ? () => { QS.order = QS.sort === key && QS.order === 'asc' ? 'desc' : 'asc'; QS.sort = key; load().catch(FQ.fail); } : null },
    label + (QS.sort === key ? (QS.order === 'asc' ? ' ▲' : ' ▼') : ''));
  const renderTable = (r) => {
    const pages = Math.max(1, Math.ceil(r.total / r.page_size));
    const edit = FQ.can('editor');
    tableBox.replaceChildren(
      h('div', { class: 'tbl-wrap' }, h('table', { class: 'qtable' },
        h('thead', {}, h('tr', {}, th('ID', 'id'), th('Question', 'text'), th('Category', 'category'), th('Correct answer'), th('Languages'), th('Status', 'status'), th('Updated', 'updated_at'), h('th'))),
        h('tbody', {}, r.items.map(q => h('tr', {},
          h('td', { class: 'muted' }, '#' + q.id),
          h('td', {}, h('div', { class: 'qcell' },
            q.image_url ? h('img', { class: 'thumb', src: q.image_url, alt: '' }) : h('div', { class: 'thumb text', title: 'Text-only question' }, 'Aa'),
            h('div', {}, h('div', { class: 'qt' }, q.text_en || '—'), q.text_ar ? h('div', { class: 'qt muted rtl' }, q.text_ar) : null))),
          h('td', {}, h('div', {}, q.category_en || '—'), h('div', { class: 'muted small' }, q.difficulty + ' · ' + q.option_count + ' options')),
          h('td', {}, h('div', {}, q.correct_label_en || '—'), h('div', { class: 'muted rtl' }, q.correct_label_ar || '')),
          h('td', {}, h('div', { class: 'row tight' }, q.languages.length ? q.languages.map(l => FQ.badge(l.toUpperCase(), 'ok')) : FQ.badge('incomplete', 'bad'))),
          h('td', {}, FQ.badge(q.status), q.enabled ? null : h('div', { class: 'muted small' }, 'disabled')),
          h('td', { class: 'muted small nowrap' }, FQ.fmtDate(q.updated_at)),
          h('td', { class: 'actions' }, h('div', { class: 'btn-row' },
            edit ? h('button', { class: 'btn small primary', onclick: () => editQuestion(q.id).catch(FQ.fail) }, 'Edit') : null,
            h('button', { class: 'btn small', onclick: () => previewMenu(q) }, 'View'),
            FQ.menu('More ▾', [
              edit && (q.status === 'published' ? { label: 'Unpublish', onclick: () => setStatus(q.id, 'unpublished') } : { label: 'Publish', onclick: () => setStatus(q.id, 'published') }),
              edit && { label: 'Duplicate', onclick: async () => { try { await FQ.api(`/questions/${q.id}/duplicate`, { method: 'POST' }); FQ.toast('Duplicated as a draft', 'ok'); load(); } catch (e) { FQ.fail(e); } } },
              edit && { label: 'Delete…', danger: true, onclick: async () => { if (await FQ.confirm(`Delete question #${q.id}? Past results keep a copy of its text.`)) { try { await FQ.api('/questions/' + q.id, { method: 'DELETE' }); load(); } catch (e) { FQ.fail(e); } } } }])))))))),
      r.items.length ? '' : h('p', { class: 'muted' }, 'No questions match your filters.'),
      h('div', { class: 'pager' }, h('span', { class: 'muted' }, `${r.total} question(s) · page ${r.page} of ${pages}`),
        h('button', { class: 'btn small', disabled: r.page <= 1, onclick: () => { QS.page--; load(); } }, '‹ Prev'),
        h('button', { class: 'btn small', disabled: r.page >= pages, onclick: () => { QS.page++; load(); } }, 'Next ›')));
  };
  const setStatus = async (id, status) => { try { await FQ.api(`/questions/${id}/status`, { method: 'POST', body: { status } }); FQ.toast(status === 'published' ? 'Published' : 'Unpublished', 'ok'); load(); } catch (e) { FQ.fail(e); } };
  const filters = h('div', { class: 'row', style: { marginBottom: '14px' } },
    h('input', { placeholder: 'Search text, option or ID…', value: QS.q, style: { maxWidth: '280px' }, oninput: (e) => { clearTimeout(filters.t); filters.t = setTimeout(() => { QS.q = e.target.value; QS.page = 1; load(); }, 300); } }),
    FQ.select([['', 'All statuses'], ['draft', 'Draft'], ['published', 'Published'], ['unpublished', 'Unpublished']], QS.status, { style: { width: 'auto' }, onchange: (e) => { QS.status = e.target.value; QS.page = 1; load(); } }),
    FQ.select([['', 'All categories'], ...cats.map(c => [c.id, c.name_en])], QS.category_id, { style: { width: 'auto' }, onchange: (e) => { QS.category_id = e.target.value; QS.page = 1; load(); } }),
    FQ.select([['', 'Any difficulty'], ['easy', 'Easy'], ['medium', 'Medium'], ['hard', 'Hard']], QS.difficulty, { style: { width: 'auto' }, onchange: (e) => { QS.difficulty = e.target.value; QS.page = 1; load(); } }));
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Questions'), h('div', { class: 'row' },
    FQ.can('editor') ? h('button', { class: 'btn', onclick: () => categoriesDialog(cats).catch(FQ.fail) }, 'Categories') : null,
    FQ.can('editor') ? h('button', { class: 'btn primary', onclick: () => editQuestion(null) }, '+ New question') : null)), h('div', { class: 'panel' }, filters, tableBox));
  FQ.reloadQuestions = load; await load();
};

function previewMenu(q) {
  const link = (lang) => h('a', { class: 'btn', target: '_blank', rel: 'noopener', href: `/game/?preview=question&id=${q.id}&lang=${lang}` }, `Preview in ${lang === 'en' ? 'English' : 'Arabic'}`);
  const m = FQ.modal({ title: `Question #${q.id}`, width: 520, body: [h('p', {}, q.text_en || q.text_ar), h('p', { class: 'muted' }, `Version ${q.version} · UID ${q.uid}`),
    h('div', { class: 'row' }, q.languages.includes('en') || q.text_en ? link('en') : null, q.languages.includes('ar') || q.text_ar ? link('ar') : null),
    h('p', { class: 'muted' }, 'Previews play the real game screen with this question; nothing is saved to the results.')] });
}

async function categoriesDialog(cats) {
  const body = h('div');
  const render = async () => {
    cats = await FQ.api('/categories');
    body.replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Slug'), h('th', {}, 'English'), h('th', {}, 'Arabic'), h('th', {}, 'Questions'), h('th'))),
      h('tbody', {}, cats.map(c => { const slug = h('input', { value: c.slug }), en = h('input', { value: c.name_en }), ar = h('input', { value: c.name_ar, class: 'rtl' });
        return h('tr', {}, h('td', {}, slug), h('td', {}, en), h('td', {}, ar), h('td', {}, c.question_count), h('td', { class: 'actions' },
          h('button', { class: 'btn small', onclick: async () => { try { await FQ.api('/categories/' + c.id, { method: 'PUT', body: { slug: slug.value, name_en: en.value, name_ar: ar.value } }); FQ.toast('Saved', 'ok'); } catch (e) { FQ.fail(e); } } }, 'Save'),
          h('button', { class: 'btn small danger', onclick: async () => { if (await FQ.confirm('Delete this category? Its questions become uncategorised.')) { await FQ.api('/categories/' + c.id, { method: 'DELETE' }).catch(FQ.fail); render(); } } }, 'Delete'))); }))));
    const s = h('input', { placeholder: 'slug-like-this' }), en = h('input', { placeholder: 'English name' }), ar = h('input', { placeholder: 'الاسم بالعربية', class: 'rtl' });
    body.append(h('h3', { style: { marginTop: '20px' } }, 'Add category'), h('div', { class: 'grid3' }, s, en, ar),
      h('button', { class: 'btn primary', style: { marginTop: '10px' }, onclick: async () => { try { await FQ.api('/categories', { method: 'POST', body: { slug: s.value, name_en: en.value, name_ar: ar.value } }); render(); } catch (e) { FQ.fail(e); } } }, 'Add'));
  };
  FQ.modal({ title: 'Question categories', width: 860, body, onClose: () => FQ.route() }); await render();
}


/* Builds a ready-to-save question from a character: image comes from the character, the correct answer is its name,
   wrong answers are other characters of the same kind. */
function questionFromCharacter(c, all) {
  const kind = { player: ['Who is this player?', 'من هذا اللاعب؟'], mascot: ['Who is this mascot?', 'من هو هذا التميمة؟'], object: ['What is this?', 'ما هذا؟'], team: ['Which team is this?', 'أي فريق هذا؟'] }[c.category] || ['Who or what is this?', 'من أو ما هذا؟'];
  const others = all.filter(x => x.id !== c.id && (x.name_en || x.name_ar)).sort(() => Math.random() - 0.5);
  const same = others.filter(x => x.category === c.category), rest = others.filter(x => x.category !== c.category);
  const picks = [...same, ...rest].slice(0, 3);
  const options = [{ label_en: c.name_en, label_ar: c.name_ar, is_correct: true }, ...picks.map(x => ({ label_en: x.name_en, label_ar: x.name_ar, is_correct: false }))];
  while (options.length < 4) options.push({ label_en: '', label_ar: '', is_correct: false });
  options.sort(() => Math.random() - 0.5);
  return { character_id: c.id, text_en: kind[0], text_ar: kind[1], options };
}
FQ.questionFromCharacter = questionFromCharacter;

async function editQuestion(id, prefill = {}) {
  const [cats, chars, schemes] = await Promise.all([FQ.api('/categories'), FQ.api('/characters'), FQ.api('/schemes')]);
  const q = id ? await FQ.api('/questions/' + id) : { text_en: '', text_ar: '', explanation_en: '', explanation_ar: '', category_id: null, difficulty: 'easy', image_asset_id: null,
    reveal_asset_id: null, character_id: null, scheme_id: null, enabled: true, sort_order: 0, status: 'draft', options: [0, 1, 2, 3].map(() => ({ label_en: '', label_ar: '', is_correct: false })), ...prefill };
  const f = {
    text_en: h('textarea', { rows: 2, value: q.text_en, placeholder: 'What is shown in this picture?' }), text_ar: h('textarea', { rows: 2, class: 'rtl', value: q.text_ar, placeholder: 'ماذا تظهر هذه الصورة؟' }),
    exp_en: h('textarea', { rows: 2, value: q.explanation_en }), exp_ar: h('textarea', { rows: 2, class: 'rtl', value: q.explanation_ar }),
    cat: FQ.select([['', '— none —'], ...cats.map(c => [c.id, c.name_en])], q.category_id ?? ''),
    diff: FQ.select([['easy', 'Easy'], ['medium', 'Medium'], ['hard', 'Hard']], q.difficulty),
    char: FQ.select([['', '— none —'], ...chars.map(c => [c.id, c.name_en || c.name_ar])], q.character_id ?? ''),
    scheme: FQ.select([['', 'Default 2×2 grid'], ...schemes.map(s => [s.id, s.name + (s.enabled ? '' : ' (disabled)')])], q.scheme_id ?? ''),
    enabled: h('input', { type: 'checkbox', checked: q.enabled }), order: h('input', { type: 'number', value: q.sort_order }),
  };
  const img = FQ.assetPicker({ value: q.image_asset_id }), reveal = FQ.assetPicker({ value: q.reveal_asset_id });
  let opts = q.options.map(o => ({ ...o }));
  const hasPicture = !!(q.image_asset_id || q.reveal_asset_id || q.character_id);
  const kindSel = FQ.select([['picture', 'Picture question (shows an image)'], ['text', 'Text-only question (no image)']], hasPicture || !id && prefill.character_id ? 'picture' : (id ? 'text' : 'picture'));
  const pictureBox = h('div');
  const optBox = h('div'); const renderOpts = () => {
    optBox.replaceChildren(...opts.map((o, i) => h('div', { class: 'opt-row' },
      h('input', { type: 'radio', name: 'correct', checked: o.is_correct, title: 'Correct answer', onchange: () => opts.forEach((x, k) => x.is_correct = k === i) }),
      h('input', { value: o.label_en, placeholder: `Option ${i + 1} (English)`, oninput: (e) => o.label_en = e.target.value }),
      h('input', { value: o.label_ar, class: 'rtl', placeholder: `الخيار ${i + 1} (عربي)`, oninput: (e) => o.label_ar = e.target.value }),
      h('button', { class: 'btn small danger', type: 'button', disabled: opts.length <= 2, onclick: () => { opts.splice(i, 1); renderOpts(); } }, '×'))));
  };
  renderOpts();
  const err = h('div', { class: 'error', hidden: true });
  const syncKind = () => { pictureBox.hidden = kindSel.value === 'text'; };
  kindSel.addEventListener('change', syncKind);
  const tpl = !id ? FQ.select([['', 'Start from…'], ['mc', 'Multiple choice (4 options)'], ['tf', 'True / False']], '', { onchange: (e) => {
    if (e.target.value === 'tf') { opts = [{ label_en: 'True', label_ar: 'صح', is_correct: true }, { label_en: 'False', label_ar: 'خطأ', is_correct: false }]; kindSel.value = 'text'; }
    else if (e.target.value === 'mc') { opts = [0, 1, 2, 3].map(() => ({ label_en: '', label_ar: '', is_correct: false })); }
    syncKind(); renderOpts(); e.target.value = ''; } }) : null;
  const fillFromChar = h('button', { class: 'btn small', type: 'button', onclick: () => { const c = chars.find(x => String(x.id) === f.char.value); if (!c) return FQ.toast('Choose a character first'); const p = questionFromCharacter(c, chars);
    f.text_en.value = p.text_en; f.text_ar.value = p.text_ar; opts = p.options; renderOpts(); kindSel.value = 'picture'; syncKind(); FQ.toast('Filled from the character — check the answers, then publish', 'ok'); } }, 'Fill question & answers from this character');
  const payload = () => ({ text_en: f.text_en.value, text_ar: f.text_ar.value, explanation_en: f.exp_en.value, explanation_ar: f.exp_ar.value,
    category_id: f.cat.value ? Number(f.cat.value) : null, difficulty: f.diff.value, image_asset_id: kindSel.value === 'text' ? null : img.getValue(), reveal_asset_id: kindSel.value === 'text' ? null : reveal.getValue(),
    character_id: kindSel.value === 'text' ? null : (f.char.value ? Number(f.char.value) : null), scheme_id: f.scheme.value ? Number(f.scheme.value) : null, enabled: f.enabled.checked, sort_order: Number(f.order.value) || 0,
    options: opts.map(o => ({ id: o.id ?? null, label_en: o.label_en, label_ar: o.label_ar, is_correct: !!o.is_correct })) });
  let current = id;
  const save = async () => {
    err.hidden = true;
    if (current) { const r = await FQ.api('/questions/' + current, { method: 'PUT', body: payload() }); if (r.auto_unpublished) FQ.toast('The edit made it invalid, so it was unpublished. Fix the issues and publish again.', 'bad'); return r.question; }
    const r = await FQ.api('/questions', { method: 'POST', body: payload() }); current = r.id; return r;
  };
  syncKind();
  const run = (fn) => async () => { try { await fn(); } catch (e) { err.textContent = e.message; err.hidden = false; err.scrollIntoView({ block: 'nearest' }); } };
  const m = FQ.modal({ title: id ? `Edit question #${id}` : 'New question', width: 980, onClose: () => FQ.reloadQuestions && FQ.reloadQuestions(),
    body: [h('div', { class: 'row', style: { marginBottom: '14px', alignItems: 'flex-start' } }, h('div', { style: { minWidth: '320px' } }, FQ.field('Question type', kindSel, 'Pictures are optional: choose “Text-only” for a normal quiz.')), tpl ? h('div', { style: { minWidth: '220px' } }, FQ.field('Template', tpl)) : null),
      h('div', { class: 'grid2' }, FQ.field('Question (English)', f.text_en), FQ.field('السؤال (Arabic)', f.text_ar),
      FQ.field('Explanation (English, optional)', f.exp_en), FQ.field('الشرح (Arabic, optional)', f.exp_ar)),
      (pictureBox.append(h('div', { class: 'grid2', style: { marginTop: '14px' } },
        FQ.field('Question image', img, 'Shown on the question screen. Crops, mascots, objects — any image.'),
        FQ.field('Reveal image (optional)', reveal, 'Shown as a sticker after answering (e.g. the full player photo). Falls back to the character\'s reveal image.')),
        h('div', { style: { marginTop: '14px' } }, FQ.field('Character / object (optional)', f.char, 'Picking a character uses its image automatically when no question image is set.'), h('div', { style: { marginTop: '8px' } }, fillFromChar))), pictureBox),
      h('div', { class: 'grid3', style: { marginTop: '14px' } }, FQ.field('Category', f.cat), FQ.field('Difficulty', f.diff), FQ.field('Interaction scheme', f.scheme, 'Leave on default unless you need a special layout.')),
      h('h3', { style: { marginTop: '22px' } }, 'Answer options'),
      h('p', { class: 'muted' }, 'Mark exactly one correct answer (the radio button). A language is playable only when the question and every option are filled in for it.'),
      optBox, h('button', { class: 'btn small', type: 'button', onclick: () => { if (opts.length < 8) { opts.push({ label_en: '', label_ar: '', is_correct: false }); renderOpts(); } } }, '+ Add option'),
      h('div', { class: 'row', style: { marginTop: '16px' } }, h('label', { class: 'check' }, f.enabled, 'Enabled'), h('div', { style: { width: '140px' } }, FQ.field('Sort order', f.order))), err],
    footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Close'),
      h('button', { class: 'btn', onclick: run(async () => { if (!current) await save(); const prev = (lang) => window.open(`/game/?preview=question&id=${current}&lang=${lang}`, '_blank', 'noopener'); await save(); prev(f.text_en.value ? 'en' : 'ar'); }) }, 'Save & preview'),
      h('button', { class: 'btn', onclick: run(async () => { await save(); FQ.toast('Saved as draft', 'ok'); m.close(); }) }, 'Save'),
      h('button', { class: 'btn primary', onclick: run(async () => { await save(); await FQ.api(`/questions/${current}/status`, { method: 'POST', body: { status: 'published' } }); FQ.toast('Published — it will appear in new game sessions', 'ok'); m.close(); }) }, 'Save & publish')] });
}
FQ.editQuestion = editQuestion;

/* =========================================================== CHARACTERS */
FQ.pages.characters = async (main) => {
  const box = h('div', { class: 'cards' }); let search = '';
  const load = async () => {
    const list = await FQ.api('/characters?q=' + encodeURIComponent(search));
    const all = list;
    box.replaceChildren(...list.map(c => h('div', { class: 'card' },
      h('div', { class: 'img' }, c.image_url ? h('img', { src: c.image_url, alt: '' }) : h('span', { class: 'muted' }, 'No image')),
      h('div', { class: 'card-title' }, h('b', {}, c.name_en || c.name_ar), c.name_ar && c.name_en ? h('div', { class: 'muted rtl' }, c.name_ar) : null),
      h('div', { class: 'row tight' }, FQ.badge(c.category, 'off'), c.usage_count ? FQ.badge(`in ${c.usage_count} question${c.usage_count > 1 ? 's' : ''}`, 'ok') : FQ.badge('not in any question yet', 'draft')),
      FQ.can('editor') ? h('div', { class: 'card-actions' },
        h('button', { class: 'btn small primary wide', onclick: () => FQ.editQuestion(null, questionFromCharacter(c, all)) }, '＋ Create question with this'),
        h('button', { class: 'btn small', onclick: () => editChar(c) }, 'Edit'),
        h('button', { class: 'btn small danger', onclick: async () => { if (await FQ.confirm(`Delete “${c.name_en || c.name_ar}”?`)) { try { await FQ.api('/characters/' + c.id, { method: 'DELETE' }); load(); } catch (e) { FQ.fail(e); } } } }, 'Delete')) : null)));
    if (!list.length) box.append(h('p', { class: 'muted' }, 'No characters yet. Add players, mascots or objects, then reuse them across questions.'));
  };
  const editChar = (c) => {
    c = c || { name_en: '', name_ar: '', description_en: '', description_ar: '', category: 'player', metadata: {}, asset_id: null, reveal_asset_id: null };
    const f = { ne: h('input', { value: c.name_en }), na: h('input', { value: c.name_ar, class: 'rtl' }), de: h('textarea', { value: c.description_en }), da: h('textarea', { value: c.description_ar, class: 'rtl' }),
      cat: FQ.select([['player', 'Player'], ['mascot', 'Mascot'], ['object', 'Object'], ['team', 'Team'], ['other', 'Other']], c.category),
      meta: h('textarea', { rows: 3, value: JSON.stringify(c.metadata || {}, null, 2) }) };
    const img = FQ.assetPicker({ value: c.asset_id }), rev = FQ.assetPicker({ value: c.reveal_asset_id }); const err = h('div', { class: 'error', hidden: true });
    const m = FQ.modal({ title: c.id ? 'Edit character' : 'New character', width: 760, body: [h('div', { class: 'grid2' }, FQ.field('Name (English)', f.ne), FQ.field('الاسم (Arabic)', f.na),
      FQ.field('Description (English)', f.de), FQ.field('الوصف (Arabic)', f.da)), h('div', { class: 'grid3', style: { marginTop: '14px' } }, FQ.field('Category', f.cat),
      FQ.field('Question image', img, 'What players see, e.g. the cropped eyes'), FQ.field('Reveal image', rev, 'Shown after answering, e.g. the full photo')), h('details', { class: 'adv' }, h('summary', {}, 'Advanced: extra details (optional)'), h('p', { class: 'muted' }, 'Optional notes stored with this character, as JSON. The game does not use them yet, so you can safely leave this as {}. Example: {"club": "Al Hilal", "nationality": "Saudi Arabia", "shirt_number": 9}'), f.meta), err],
      footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), h('button', { class: 'btn primary', onclick: async () => {
        try { let meta = {}; try { meta = JSON.parse(f.meta.value || '{}'); } catch (e) { throw new Error('Extra details must be valid JSON, e.g. {"club": "Al Hilal"} — or leave it as {}'); }
          const body = { name_en: f.ne.value, name_ar: f.na.value, description_en: f.de.value, description_ar: f.da.value, category: f.cat.value, metadata: meta, asset_id: img.getValue(), reveal_asset_id: rev.getValue() };
          await FQ.api(c.id ? '/characters/' + c.id : '/characters', { method: c.id ? 'PUT' : 'POST', body }); m.close(); load(); FQ.toast('Saved', 'ok');
        } catch (e) { err.textContent = e.message; err.hidden = false; } } }, 'Save')] });
  };
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Characters & objects'), FQ.can('editor') ? h('button', { class: 'btn primary', onclick: () => editChar() }, '+ New character') : null),
    h('div', { class: 'help' }, h('b', {}, 'How this works: '), 'a character is a reusable picture + name (a player, mascot, team or object). It does not appear in the game by itself — click ', h('b', {}, 'Create question with this'), ' to turn it into a question (the image, the correct answer and wrong answers are filled in for you), then ', h('b', {}, 'Save & publish'), '. Quizzes without pictures don’t need characters at all.'),
    h('div', { class: 'row', style: { marginBottom: '14px' } }, h('input', { placeholder: 'Search by name…', style: { maxWidth: '300px' }, oninput: (e) => { search = e.target.value; clearTimeout(box.t); box.t = setTimeout(load, 250); } })), box);
  await load();
};

/* =========================================================== MEDIA LIBRARY */
FQ.pages.assets = async (main) => {
  const box = h('div', { class: 'cards' }); let kind = '';
  const load = async () => {
    const list = await FQ.api('/assets' + (kind ? '?kind=' + kind : ''));
    box.replaceChildren(...list.map(a => h('div', { class: 'card' },
      h('div', { class: 'img' }, a.kind === 'font' ? h('b', { style: { fontSize: '28px' } }, 'Aa') : h('img', { src: a.url, alt: '' })),
      h('div', { class: 'muted', style: { wordBreak: 'break-all' } }, `${a.original_name || a.url}`), h('div', { class: 'muted' }, `${a.width ? a.width + '×' + a.height + ' · ' : ''}${(a.size_bytes / 1024).toFixed(0)} KB ${a.in_use ? '· in use' : ''}`),
      FQ.can('editor') ? h('div', { class: 'card-actions' }, h('label', { class: 'btn small' }, 'Replace', h('input', { type: 'file', hidden: true, onchange: async (e) => { const fd = new FormData(); fd.append('file', e.target.files[0]); try { await FQ.api(`/assets/${a.id}/replace`, { method: 'PUT', body: fd }); FQ.toast('Replaced everywhere it is used', 'ok'); load(); } catch (x) { FQ.fail(x); } } })),
        h('button', { class: 'btn small danger', onclick: async () => { if (await FQ.confirm('Delete this file?')) { try { await FQ.api('/assets/' + a.id, { method: 'DELETE' }); load(); } catch (e) { FQ.fail(e); } } } }, 'Delete')) : null)));
    if (!list.length) box.append(h('p', { class: 'muted' }, 'The library is empty.'));
  };
  const up = h('input', { type: 'file', multiple: true, accept: 'image/*,.woff2,.woff,.ttf,.otf', hidden: true, onchange: async (e) => {
    for (const file of e.target.files) { const fd = new FormData(); fd.append('file', file); try { await FQ.api('/assets', { method: 'POST', body: fd }); } catch (x) { FQ.toast(`${file.name}: ${x.message}`, 'bad'); } } load(); } });
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Media library'), FQ.can('editor') ? h('div', {}, up, h('button', { class: 'btn primary', onclick: () => up.click() }, '+ Upload files')) : null),
    h('p', { class: 'muted' }, 'PNG, JPEG, WebP, GIF, SVG and WOFF2/WOFF/TTF/OTF fonts up to 8 MB. Files are checked by content, not by file name.'),
    h('div', { class: 'row', style: { marginBottom: '12px' } }, FQ.select([['', 'All files'], ['image', 'Images'], ['font', 'Fonts']], '', { style: { width: 'auto' }, onchange: (e) => { kind = e.target.value; load(); } })), box);
  await load();
};

/* =========================================================== INTERACTION SCHEMES */
FQ.pages.schemes = async (main) => {
  const box = h('div', { class: 'panel' });
  const load = async () => {
    const list = await FQ.api('/schemes');
    box.replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Name'), h('th', {}, 'Type'), h('th', {}, 'Description'), h('th', {}, 'Questions'), h('th', {}, 'Status'), h('th'))),
      h('tbody', {}, list.map(s => h('tr', {}, h('td', {}, h('b', {}, s.name)), h('td', {}, s.scheme_type === 'touch_zones' ? 'Touch zones' : 'Pose mapping'), h('td', { class: 'muted', style: { maxWidth: '380px' } }, s.description),
        h('td', {}, s.usage_count || (s.name.startsWith('Standard') ? 'all (default)' : 0)), h('td', {}, FQ.badge(s.enabled ? 'enabled' : 'disabled', s.enabled ? 'ok' : 'off')),
        h('td', { class: 'actions' }, h('div', { class: 'btn-row' }, FQ.can('editor') ? h('button', { class: 'btn small primary', onclick: () => editScheme(s) }, 'Edit') : null, h('a', { class: 'btn small', target: '_blank', rel: 'noopener', href: `/game/?preview=scheme&id=${s.id}` }, 'Test'),
          FQ.can('editor') ? FQ.menu('More ▾', [{ label: 'Duplicate', onclick: async () => { await FQ.api(`/schemes/${s.id}/duplicate`, { method: 'POST' }).catch(FQ.fail); load(); } },
            { label: s.enabled ? 'Disable' : 'Enable', onclick: async () => { await FQ.api('/schemes/' + s.id, { method: 'PUT', body: { name: s.name, description: s.description, scheme_type: s.scheme_type, config: s.config, enabled: !s.enabled } }).catch(FQ.fail); load(); } },
            { label: 'Delete…', danger: true, onclick: async () => { if (!(await FQ.confirm(`Delete “${s.name}”?`))) return; try { await FQ.api('/schemes/' + s.id, { method: 'DELETE' }); } catch (e) { if (e.status === 409 && await FQ.confirm(e.message + '\n\nUnassign it from those questions and delete?', 'Unassign & delete')) await FQ.api('/schemes/' + s.id + '?force=true', { method: 'DELETE' }).catch(FQ.fail); else if (e.status !== 409) FQ.fail(e); } load(); } }]) : null)))))));
  };
  const editScheme = (s) => {
    s = s || { name: '', description: '', scheme_type: 'touch_zones', config: { layout: 'grid2x2' }, enabled: true };
    const cfg = JSON.parse(JSON.stringify(s.config || {}));
    const name = h('input', { value: s.name }), desc = h('textarea', { rows: 2, value: s.description }), type = FQ.select([['touch_zones', 'Touch zones (layout of the answer buttons)'], ['pose_mapping', 'Pose mapping (camera required)']], s.scheme_type);
    const enabled = h('input', { type: 'checkbox', checked: s.enabled }), cfgBox = h('div'), err = h('div', { class: 'error', hidden: true });
    const renderCfg = () => {
      cfgBox.replaceChildren();
      if (type.value === 'touch_zones') {
        const layout = FQ.select([['grid2x2', '2×2 grid'], ['row', 'Single row'], ['column', 'Single column'], ['custom', 'Custom zones']], cfg.layout || 'grid2x2', { onchange: (e) => { cfg.layout = e.target.value; if (cfg.layout === 'custom' && !(cfg.zones || []).length) cfg.zones = [0, 1, 2, 3].map(i => ({ option_index: i, x: 0.1 + (i % 2) * 0.45, y: 0.55 + Math.floor(i / 2) * 0.17, w: 0.35, h: 0.14 })); renderCfg(); } });
        cfgBox.append(FQ.field('Layout', layout));
        if ((cfg.layout || 'grid2x2') === 'custom') {
          const prev = h('div', { class: 'sim-screen', style: { marginTop: '12px', cursor: 'default' } });
          const draw = () => prev.replaceChildren(...(cfg.zones || []).map(z => h('div', { style: { position: 'absolute', left: z.x * 100 + '%', top: z.y * 100 + '%', width: z.w * 100 + '%', height: z.h * 100 + '%', background: '#2b44ff', color: '#fff', fontSize: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '4px' } }, 'Option ' + (z.option_index + 1))));
          draw();
          const rows = (cfg.zones || []).map((z, i) => h('div', { class: 'row', style: { marginBottom: '6px' } }, h('span', { style: { width: '70px' } }, 'Option ' + (z.option_index + 1)),
            ...['x', 'y', 'w', 'h'].map(k => h('label', { class: 'muted' }, k.toUpperCase() + ' % ', h('input', { type: 'number', min: 0, max: 100, step: 1, value: Math.round(z[k] * 100), style: { width: '76px' }, oninput: (e) => { z[k] = Math.max(0, Math.min(1, Number(e.target.value) / 100)); draw(); } }))),
            h('button', { class: 'btn small danger', type: 'button', onclick: () => { cfg.zones.splice(i, 1); renderCfg(); } }, '×')));
          cfgBox.append(h('p', { class: 'muted' }, 'Zones are fractions of the projected screen. Each zone is the touch area of one answer (by position).'), ...rows,
            h('button', { class: 'btn small', type: 'button', onclick: () => { cfg.zones = cfg.zones || []; cfg.zones.push({ option_index: cfg.zones.length, x: 0.1, y: 0.6, w: 0.3, h: 0.12 }); renderCfg(); } }, '+ Zone'), prev);
        }
      } else {
        cfg.mappings = cfg.mappings || [{ pose: 'arm_up_left', option_index: 0 }]; cfg.min_confidence = cfg.min_confidence ?? 0.75;
        cfgBox.append(h('div', { class: 'error', style: { background: '#fff4dc', color: '#7a4b00' } }, 'The RPLIDAR cannot recognise body poses. Pose answers need a camera + pose-estimation service that posts labels to /api/input/pose (see docs/SENSOR.md).'),
          ...cfg.mappings.map((m, i) => h('div', { class: 'row', style: { marginBottom: '6px' } }, h('input', { value: m.pose, placeholder: 'pose label e.g. arm_up_left', style: { maxWidth: '260px' }, oninput: (e) => m.pose = e.target.value }),
            h('label', { class: 'muted' }, 'answers option # ', h('input', { type: 'number', min: 1, max: 8, value: m.option_index + 1, style: { width: '70px' }, oninput: (e) => m.option_index = Math.max(0, Number(e.target.value) - 1) })),
            h('button', { class: 'btn small danger', type: 'button', onclick: () => { cfg.mappings.splice(i, 1); renderCfg(); } }, '×'))),
          h('button', { class: 'btn small', type: 'button', onclick: () => { cfg.mappings.push({ pose: '', option_index: cfg.mappings.length }); renderCfg(); } }, '+ Mapping'),
          FQ.field('Minimum confidence (0–1)', h('input', { type: 'number', step: 0.05, min: 0, max: 1, value: cfg.min_confidence, oninput: (e) => cfg.min_confidence = Number(e.target.value) })));
      }
    };
    type.addEventListener('change', () => { Object.keys(cfg).forEach(k => delete cfg[k]); if (type.value === 'touch_zones') cfg.layout = 'grid2x2'; renderCfg(); }); renderCfg();
    const m = FQ.modal({ title: s.id ? 'Edit scheme' : 'New scheme', width: 760, body: [FQ.field('Name', name), FQ.field('Description', desc), FQ.field('Type', type), h('div', { style: { marginTop: '14px' } }, cfgBox),
      h('label', { class: 'check', style: { marginTop: '14px' } }, enabled, 'Enabled'), err],
      footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), h('button', { class: 'btn primary', onclick: async () => {
        try { await FQ.api(s.id ? '/schemes/' + s.id : '/schemes', { method: s.id ? 'PUT' : 'POST', body: { name: name.value, description: desc.value, scheme_type: type.value, config: cfg, enabled: enabled.checked } }); m.close(); load(); FQ.toast('Saved', 'ok'); }
        catch (e) { err.textContent = e.message; err.hidden = false; } } }, 'Save')] });
  };
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Interaction schemes'), FQ.can('editor') ? h('button', { class: 'btn primary', onclick: () => editScheme() }, '+ New scheme') : null),
    h('div', { class: 'help' }, h('b', {}, 'Do I need this page? '), 'Usually not. Every question already uses the ', h('b', {}, 'Standard 2×2 grid'), ' (four big answer buttons) unless you pick another scheme. Use this page only if you want a different answer layout — a single row, a column, or custom touch areas placed on the projected wall — or for body-pose answers (needs a camera service; disabled by default). Pick a scheme per question in the question editor. “Test” shows it on the real game screen.'), box);
  await load();
};
})();
