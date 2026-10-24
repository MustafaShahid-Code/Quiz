/* Admin pages: branding slides, themes (white-label), game settings */
'use strict';
(() => {
const FQ = window.FQ, h = FQ.h;

/* =========================================================== BRANDING SLIDES */
FQ.pages.slides = async (main) => {
  const box = h('div', { class: 'panel' });
  const games = await FQ.loadGames(), restricted = !FQ.state.user.all_games && FQ.state.user.role !== 'admin';
  const gname = (id) => { const g = games.find(x => x.id === id); return g ? (g.name_en || g.name_ar) : null; };
  let scope = FQ.gameScope.get(); if (scope && !games.some(g => String(g.id) === scope)) scope = '';
  if (restricted && !scope) scope = String(games[0] && games[0].id || '');
  const load = async () => {
    const all = await FQ.api('/slides');
    const list = scope ? all.filter(x => x.game_id === null || String(x.game_id) === scope) : all;
    const swap = async (a, b) => { try { await FQ.api('/slides/' + a.id, { method: 'PUT', body: slideBody(a, { sort_order: b.sort_order }) }); await FQ.api('/slides/' + b.id, { method: 'PUT', body: slideBody(b, { sort_order: a.sort_order }) }); } catch (e) { FQ.fail(e); } load(); };
    box.replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Order'), h('th', {}, 'Slide'), h('th', {}, 'Shown in'), h('th', {}, 'Text'), h('th', {}, 'Duration'), h('th', {}, 'Schedule'), h('th', {}, 'Status'), h('th'))),
      h('tbody', {}, list.map((s, i) => h('tr', {},
        h('td', {}, FQ.can('editor') ? h('div', { class: 'row' }, h('button', { class: 'btn small', disabled: i === 0, onclick: () => swap(s, list[i - 1]) }, '↑'), h('button', { class: 'btn small', disabled: i === list.length - 1, onclick: () => swap(s, list[i + 1]) }, '↓')) : i + 1),
        h('td', {}, h('div', { style: { width: '120px', height: '68px', background: s.bg_color, borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' } }, s.image_url ? h('img', { src: s.image_url, alt: '', style: { maxWidth: '100%', maxHeight: '100%', objectFit: s.fit } }) : h('span', { style: { color: '#fff', fontSize: '11px' } }, 'text slide'))),
        h('td', {}, s.game_id === null ? FQ.badge('all games', 'off') : FQ.badge(gname(s.game_id) || '—', 'ok')),
        h('td', {}, h('div', {}, s.title_en || s.body_en || '—'), h('div', { class: 'muted rtl' }, s.title_ar || s.body_ar || '')),
        h('td', {}, (s.duration_ms / 1000) + ' s'), h('td', { class: 'muted' }, s.starts_at || s.ends_at ? `${s.starts_at ? FQ.fmtDate(s.starts_at) : 'now'} → ${s.ends_at ? FQ.fmtDate(s.ends_at) : 'no end'}` : 'Always'),
        h('td', {}, FQ.badge(s.enabled ? 'enabled' : 'disabled', s.enabled ? 'ok' : 'off')),
        h('td', { class: 'actions' }, FQ.can('editor') ? [h('button', { class: 'btn small', onclick: () => edit(s, list) }, 'Edit'),
          h('button', { class: 'btn small danger', onclick: async () => { if (await FQ.confirm('Delete this slide?')) { await FQ.api('/slides/' + s.id, { method: 'DELETE' }).catch(FQ.fail); load(); } } }, 'Delete')] : null)))))
      , list.length ? '' : h('p', { class: 'muted' }, 'No slides: the game will open directly on the welcome screen.'));
  };
  const slideBody = (s, over = {}) => ({ title_en: s.title_en, title_ar: s.title_ar, body_en: s.body_en, body_ar: s.body_ar, asset_id: s.asset_id, bg_color: s.bg_color, fit: s.fit,
    duration_ms: s.duration_ms, sort_order: s.sort_order, enabled: s.enabled, starts_at: s.starts_at, ends_at: s.ends_at, game_id: s.game_id ?? null, ...over });
  const edit = (s, list = []) => {
    s = s || { title_en: '', title_ar: '', body_en: '', body_ar: '', asset_id: null, bg_color: '#000000', fit: 'contain', duration_ms: 6000, sort_order: (list.length ? Math.max(...list.map(x => x.sort_order)) + 1 : 0), enabled: true, starts_at: null, ends_at: null, game_id: scope ? Number(scope) : null };
    const img = FQ.assetPicker({ value: s.asset_id }), err = h('div', { class: 'error', hidden: true });
    const toLocal = (v) => v ? v.slice(0, 16) : '';
    const f = { te: h('input', { value: s.title_en }), ta: h('input', { value: s.title_ar, class: 'rtl' }), be: h('textarea', { rows: 2, value: s.body_en }), ba: h('textarea', { rows: 2, class: 'rtl', value: s.body_ar }),
      bg: h('input', { type: 'color', value: s.bg_color }), fit: FQ.select([['contain', 'Fit whole image (letterbox)'], ['cover', 'Fill the screen (crop)']], s.fit), dur: h('input', { type: 'number', min: 1.5, max: 60, step: 0.5, value: s.duration_ms / 1000 }),
      st: h('input', { type: 'datetime-local', value: toLocal(s.starts_at) }), en: h('input', { type: 'datetime-local', value: toLocal(s.ends_at) }), on: h('input', { type: 'checkbox', checked: s.enabled }),
      game: FQ.select([...(restricted ? [] : [['', 'All games (shared)']]), ...games.map(g => [g.id, g.name_en || g.name_ar])], s.game_id ?? '') };
    const m = FQ.modal({ title: s.id ? 'Edit slide' : 'New slide', width: 780, body: [FQ.field('Shown in', f.game, 'A slide can be shared by every game, or belong to one customer’s game only.'), h('div', { style: { height: '12px' } }), FQ.field('Image (sponsor logos, campaign artwork…)', img, 'Tip: use a wide image; a black background suits logos exported on black.'),
      h('div', { class: 'grid3', style: { marginTop: '14px' } }, FQ.field('Background colour', f.bg), FQ.field('Image fit', f.fit), FQ.field('Seconds on screen', f.dur)),
      h('div', { class: 'grid2', style: { marginTop: '14px' } }, FQ.field('Title (English)', f.te, 'Text slides show it large; on image slides it is just a label.'), FQ.field('العنوان (Arabic)', f.ta),
        FQ.field('Caption / body (English)', f.be), FQ.field('النص (Arabic)', f.ba)),
      h('div', { class: 'grid2', style: { marginTop: '14px' } }, FQ.field('Show from (optional)', f.st, 'Campaign scheduling — server time'), FQ.field('Show until (optional)', f.en)),
      h('label', { class: 'check', style: { marginTop: '14px' } }, f.on, 'Enabled'), err],
      footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), h('button', { class: 'btn primary', onclick: async () => {
        try { const body = { title_en: f.te.value, title_ar: f.ta.value, body_en: f.be.value, body_ar: f.ba.value, asset_id: img.getValue(), bg_color: f.bg.value, fit: f.fit.value,
          duration_ms: Math.round(Number(f.dur.value) * 1000), sort_order: s.sort_order, enabled: f.on.checked, starts_at: f.st.value || null, ends_at: f.en.value || null, game_id: f.game.value ? Number(f.game.value) : null };
          await FQ.api(s.id ? '/slides/' + s.id : '/slides', { method: s.id ? 'PUT' : 'POST', body }); m.close(); load(); FQ.toast('Saved', 'ok'); } catch (e) { err.textContent = e.message; err.hidden = false; } } }, 'Save')] });
  };
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Branding & sponsor slides'), h('div', { class: 'row' }, games.length > 1 ? FQ.gameSelect(games, scope, { all: !restricted, attrs: { onchange: (e) => { scope = e.target.value; FQ.gameScope.set(scope); load(); } } }) : null, h('a', { class: 'btn', href: '/game/' + (scope ? '?game=' + encodeURIComponent((games.find(g => String(g.id) === scope) || {}).slug) : ''), target: '_blank', rel: 'noopener' }, 'See it on the game screen ↗'), FQ.can('editor') ? h('button', { class: 'btn primary', onclick: () => edit() }, '+ New slide') : null)),
    h('p', { class: 'muted' }, 'Slides marked “all games” are shared; the others belong to a single game. They loop on the first screen of the game (and whenever the game goes idle). A touch anywhere continues to the welcome screen. Turn the whole screen off in Game settings → Sponsors screen.'), box);
  await load();
};

/* =========================================================== THEMES */
const COLOR_GROUPS = [
  ['Background', [['bg_from', 'Gradient start'], ['bg_to', 'Gradient end'], ['bg_glow', 'Glow / light accent'], ['branding_bg', 'Sponsor screen background']]],
  ['Text', [['text', 'Main text'], ['text_muted', 'Secondary text'], ['title', 'Title'], ['accent_line', 'Title underline accent']]],
  ['Answer buttons', [['button_bg', 'Button'], ['button_text', 'Button text'], ['button_hover', 'Button hover'], ['button_selected_border', 'Selected outline']]],
  ['Cards & feedback', [['card_bg', 'Image card'], ['correct', 'Correct answer'], ['incorrect', 'Wrong answer'], ['burst_bg', 'Burst bubble'], ['burst_text', 'Burst text'], ['burst_stroke', 'Burst outline']]],
  ['Confetti', [['confetti_1', 'Confetti 1'], ['confetti_2', 'Confetti 2'], ['confetti_3', 'Confetti 3'], ['confetti_4', 'Confetti 4']]],
];
const HEX6 = /^#[0-9a-fA-F]{6}$/;

FQ.pages.themes = async (main) => {
  const box = h('div', { class: 'cards' });
  const swatch = (t) => { const c = t.tokens.colors; return h('div', { style: { height: '110px', borderRadius: '10px', background: `linear-gradient(160deg, ${c.bg_from}, ${c.bg_to})`, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '10px' } },
    h('div', { style: { background: c.button_bg, color: c.button_text, padding: '8px 14px', borderRadius: t.tokens.shape.button_radius / 2 + 'px', fontWeight: 700, fontSize: '13px' } }, 'Answer'),
    h('div', { style: { background: c.burst_bg, color: c.burst_text, padding: '8px 12px', borderRadius: '14px', fontWeight: 800, fontSize: '13px' } }, 'GOAL!'),
    h('div', { style: { background: c.correct, width: '14px', height: '14px', borderRadius: '50%' } })); };
  const load = async () => {
    const list = await FQ.api('/themes');
    box.replaceChildren(...list.map(t => h('div', { class: 'card' }, swatch(t),
      h('div', { class: 'row' }, h('b', { class: 'grow' }, t.name), t.is_active ? FQ.badge('active', 'ok') : (t.is_preset ? FQ.badge('preset') : null)),
      FQ.can('editor') ? h('div', { class: 'card-actions' },
        t.is_active ? h('button', { class: 'btn small wide', disabled: true }, '● Live on the game screen') : h('button', { class: 'btn small primary wide', onclick: async () => { await FQ.api(`/themes/${t.id}/activate`, { method: 'POST' }).catch(FQ.fail); FQ.toast('Theme is live on the game screen', 'ok'); load(); } }, 'Activate'),
        h('button', { class: 'btn small', onclick: () => editTheme(t) }, 'Edit'), h('button', { class: 'btn small', onclick: async () => { await FQ.api(`/themes/${t.id}/duplicate`, { method: 'POST' }).catch(FQ.fail); load(); } }, 'Duplicate'),
        h('button', { class: 'btn small', onclick: () => exportTheme(t) }, 'Export'),
        t.is_active ? h('button', { class: 'btn small', disabled: true, title: 'Activate another theme before deleting this one' }, 'Delete') : h('button', { class: 'btn small danger', onclick: async () => { if (await FQ.confirm(`Delete theme “${t.name}”?`)) { await FQ.api('/themes/' + t.id, { method: 'DELETE' }).catch(FQ.fail); load(); } } }, 'Delete')) : null)));
  };
  const exportTheme = async (t) => {
    try { const data = await FQ.api(`/themes/${t.id}/export`); const a = h('a', { href: URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })), download: t.name.replace(/[^\w-]+/g, '_') + '.fqtheme.json' }); document.body.appendChild(a); a.click(); a.remove(); } catch (e) { FQ.fail(e); }
  };
  const imp = h('input', { type: 'file', accept: '.json,application/json', hidden: true, onchange: async (e) => {
    try { const data = JSON.parse(await e.target.files[0].text()); await FQ.api('/themes/import', { method: 'POST', body: data }); FQ.toast('Theme imported', 'ok'); load(); } catch (x) { FQ.toast('Import failed: ' + x.message, 'bad'); } e.target.value = ''; } });
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Themes & colours'), FQ.can('editor') ? h('div', { class: 'row' }, imp, h('button', { class: 'btn', onclick: () => imp.click() }, 'Import theme…'), h('button', { class: 'btn primary', onclick: async () => editTheme(null) }, '+ New theme')) : null),
    h('p', { class: 'muted' }, 'White-label the whole player experience for each client: colours, fonts, logos, background, button style and effects. Only one theme is live at a time; export a theme (with its logos and fonts embedded) to reuse it on another installation.'), box);
  await load();
};

async function editTheme(t) {
  const defaults = await FQ.api('/themes/defaults');
  const tokens = JSON.parse(JSON.stringify(t ? t.tokens : defaults));
  const name = h('input', { value: t ? t.name : 'New theme' }), err = h('div', { class: 'error', hidden: true });
  const prev = h('div', { class: 'tprev' }, h('div', { class: 't' }, 'Football Challenge!'), h('div', { class: 'line' }), h('div', { class: 'c' }),
    h('div', { style: { fontSize: '12px' } }, 'What is shown in this picture?'), h('div', { class: 'b' }, 'Football'), h('div', { class: 'b sel' }, 'Selected answer'),
    h('div', { class: 'row2' }, h('div', { class: 'ok' }, 'Correct'), h('div', { class: 'no' }, 'Wrong')), h('div', { class: 'burst' }, 'GOOOAL!'));
  const paint = () => { const c = tokens.colors, s = prev.style;
    s.background = `radial-gradient(ellipse at 72% 18%, ${c.bg_glow}99, transparent 60%), linear-gradient(160deg, ${c.bg_from}, ${c.bg_to})`;
    for (const [k, v] of Object.entries({ text: c.text, title: c.title, line: c.accent_line, card: c.card_bg, btn: c.button_bg, btntext: c.button_text, sel: c.button_selected_border, burst: c.burst_bg, bursttext: c.burst_text })) s.setProperty('--p-' + k, v);
    prev.querySelector('.ok').style.background = c.correct; prev.querySelector('.no').style.background = c.incorrect;
    prev.querySelectorAll('.b').forEach(b => b.style.borderRadius = tokens.shape.button_radius / 2 + 'px'); prev.querySelector('.c').style.borderRadius = tokens.shape.card_radius / 2 + 'px';
    prev.style.fontFamily = tokens.fonts.family_en; };
  const colorField = (key, label) => { const col = h('input', { type: 'color', value: HEX6.test(tokens.colors[key]) ? tokens.colors[key] : '#000000' }), txt = h('input', { value: tokens.colors[key], style: { width: '96px' } });
    col.oninput = () => { tokens.colors[key] = col.value; txt.value = col.value; paint(); }; txt.oninput = () => { if (/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(txt.value)) { tokens.colors[key] = txt.value; if (HEX6.test(txt.value)) col.value = txt.value; paint(); } };
    return h('label', {}, col, h('span', { style: { flex: 1 } }, label), txt); };
  const fontPick = FQ.assetPicker({ value: tokens.fonts.font_asset_id, kind: 'font', onChange: (id) => tokens.fonts.font_asset_id = id });
  const logoL = FQ.assetPicker({ value: tokens.assets.logo_left_asset_id, onChange: (id) => tokens.assets.logo_left_asset_id = id }), logoR = FQ.assetPicker({ value: tokens.assets.logo_right_asset_id, onChange: (id) => tokens.assets.logo_right_asset_id = id });
  const bgPick = FQ.assetPicker({ value: tokens.assets.background_asset_id, onChange: (id) => tokens.assets.background_asset_id = id });
  const fam = (k, label) => FQ.field(label, h('input', { value: tokens.fonts[k], oninput: (e) => { tokens.fonts[k] = e.target.value; paint(); } }), "CSS font-family list, e.g. 'Cairo','Segoe UI',sans-serif");
  const range = (grp, key, label, min, max, step) => { const out = h('span', { class: 'muted' }, tokens[grp][key]); return FQ.field(label, h('div', { class: 'row' }, h('input', { type: 'range', min, max, step, value: tokens[grp][key], style: { flex: 1 }, oninput: (e) => { tokens[grp][key] = Number(e.target.value); out.textContent = e.target.value; paint(); } }), out)); };
  const toggle = (key, label) => h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: tokens.effects[key], onchange: (e) => tokens.effects[key] = e.target.checked }), label);
  const body = h('div', { class: 'theme-layout' }, h('div', {},
    FQ.field('Theme name', name),
    h('h3', { style: { marginTop: '20px' } }, 'Logos & background'),
    h('div', { class: 'grid3' }, FQ.field('Left logo', logoL), FQ.field('Right logo', logoR), FQ.field('Background image (optional)', bgPick)),
    ...COLOR_GROUPS.map(([g, items]) => [h('h3', { style: { marginTop: '20px' } }, g), h('div', { class: 'swatch-grid' }, items.map(([k, l]) => colorField(k, l)))]),
    h('h3', { style: { marginTop: '20px' } }, 'Fonts'), h('div', { class: 'grid2' }, fam('family_en', 'English font stack'), fam('family_ar', 'Arabic font stack')),
    FQ.field('Custom font file (optional)', fontPick, 'Upload a WOFF2/TTF/OTF in the media library; it is applied before the stacks above. Make sure it supports Arabic if you use it for Arabic.'),
    h('h3', { style: { marginTop: '20px' } }, 'Shape & effects'),
    h('div', { class: 'grid2' }, range('shape', 'button_radius', 'Button corner radius', 0, 60, 1), range('shape', 'card_radius', 'Image card corner radius', 0, 60, 1),
      FQ.field('Button style', FQ.select([['solid', 'Solid'], ['outline', 'Outline'], ['glass', 'Glass']], tokens.shape.button_style, { onchange: (e) => tokens.shape.button_style = e.target.value })), range('effects', 'background_overlay', 'Darken background image', 0, 0.9, 0.05)),
    h('div', { class: 'row', style: { marginTop: '12px' } }, toggle('swoosh', 'Animated light streaks'), toggle('confetti', 'Confetti'), toggle('stadium_lights', 'Stadium lights')), err),
    h('div', {}, prev, h('p', { class: 'muted', style: { marginTop: '10px' } }, 'Live approximation. Use “Save & preview” to see the real game screen with this theme.')));
  paint();
  const save = async (activate, preview) => {
    try { err.hidden = true; const bodyJson = { name: name.value, tokens }; const r = await FQ.api(t ? '/themes/' + t.id : '/themes', { method: t ? 'PUT' : 'POST', body: bodyJson });
      t = r; if (activate) await FQ.api(`/themes/${r.id}/activate`, { method: 'POST' });
      FQ.toast(activate ? 'Saved and live on the game screen' : 'Saved', 'ok'); if (preview) window.open(`/game/?preview=theme&id=${r.id}`, '_blank', 'noopener'); else { m.close(); } }
    catch (e) { err.textContent = e.message; err.hidden = false; }
  };
  const m = FQ.modal({ title: t ? `Edit theme — ${t.name}` : 'New theme', width: 1180, body, onClose: () => FQ.route(),
    footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Close'), h('button', { class: 'btn', onclick: () => { Object.assign(tokens.colors, defaults.colors); FQ.toast('Colours reset to the default palette — press Save to keep'); m.close(); editTheme({ ...(t || { id: null, name: name.value }), tokens }); } }, 'Reset colours'),
      h('button', { class: 'btn', onclick: () => save(false, true) }, 'Save & preview'), h('button', { class: 'btn', onclick: () => save(false) }, 'Save'), h('button', { class: 'btn primary', onclick: () => save(true) }, 'Save & activate')] });
}

/* =========================================================== SETTINGS */
const SECTIONS = [
  ['Text & languages', [['title_en', 'Game title (English)', 'text'], ['title_ar', 'عنوان اللعبة (Arabic)', 'text', 'rtl'], ['tagline_en', 'Tagline (English)', 'text'], ['tagline_ar', 'الشعار (Arabic)', 'text', 'rtl'],
    ['instructions_en', 'Instructions (English)', 'text'], ['instructions_ar', 'التعليمات (Arabic)', 'text', 'rtl'], ['default_language', 'Default language', 'select', [['en', 'English'], ['ar', 'العربية']]], ['enabled_languages', 'Languages players can choose', 'langs']]],
  ['Sponsors screen (first screen)', [['branding_enabled', 'Show the sponsors / branding screen first', 'bool'], ['branding_default_duration_ms', 'Default seconds per slide', 'sec'], ['branding_hint_en', 'Touch hint (English)', 'text'], ['branding_hint_ar', 'Touch hint (Arabic)', 'text', 'rtl']]],
  ['Session rules', [['questions_per_session', 'Questions per game (0 = all)', 'num'], ['randomize_questions', 'Random question order', 'bool'], ['randomize_options', 'Shuffle answer options', 'bool'], ['retries_per_question', 'Retries after a wrong answer (0–3)', 'num'], ['retry_points_fraction', 'Points fraction when correct on a retry (0–1)', 'dec']]],
  ['Scoring', [['points_correct', 'Points per correct answer', 'num'], ['points_incorrect', 'Points for a wrong answer (negative to penalise)', 'num'], ['difficulty_bonus', 'Difficulty multipliers', 'diff'], ['high_score_percent', 'Trophy at or above (% correct)', 'num']]],
  ['Answer timer (countdown on the question screen)', [['answer_timer_enabled', 'Players must choose within a time limit', 'bool'], ['answer_time_limit_ms', 'Seconds allowed to choose an answer (2–120)', 'sec'],
    ['timeout_message_en', 'Time-up message (English)', 'text'], ['timeout_message_ar', 'رسالة انتهاء الوقت (Arabic)', 'text', 'rtl']]],
  ['Answer confirmation', [['confirm_enabled', 'Ask “Are you sure?” before judging', 'bool'], ['confirm_delay_ms', 'Seconds to change their mind', 'sec'], ['confirm_retouch_locks', 'Touching the selected answer again locks it in', 'bool'], ['confirm_text_en', 'Prompt (English)', 'text'], ['confirm_text_ar', 'Prompt (Arabic)', 'text', 'rtl']]],
  ['Presentation & kiosk', [['auto_advance', 'Advance automatically after feedback', 'bool'], ['auto_advance_delay_ms', 'Seconds before advancing', 'sec'], ['show_explanations', 'Show explanations', 'bool'], ['show_correct_on_wrong', 'After a wrong answer, show which one was right (off = the player only sees it was wrong)', 'bool'], ['sound_enabled', 'Sound effects', 'bool'], ['show_touch_cursor', 'Show a ripple where a sensor touch lands', 'bool'], ['idle_reset_seconds', 'Return to sponsors screen after idle seconds (0 = never)', 'num']]],
  ['Feedback messages', [['correct_title_en', 'Correct heading (English)', 'text'], ['correct_title_ar', 'العنوان عند الصحيح (Arabic)', 'text', 'rtl'], ['correct_messages_en', 'Correct messages (English, one per line)', 'list'], ['correct_messages_ar', 'رسائل الإجابة الصحيحة (Arabic)', 'list', 'rtl'],
    ['incorrect_messages_en', 'Wrong-answer messages (English)', 'list'], ['incorrect_messages_ar', 'رسائل الإجابة الخاطئة (Arabic)', 'list', 'rtl'], ['retry_message_en', 'Retry message (English)', 'text'], ['retry_message_ar', 'رسالة المحاولة (Arabic)', 'text', 'rtl']]],
  ['Login screen', [['login_layout', 'Layout', 'select', [['split', 'Split — brand panel + form'], ['centered', 'Centered card on a branded backdrop']]], ['login_color_2', 'Gradient end colour (starts from the admin accent colour)', 'color'],
    ['login_bg_asset_id', 'Background image (optional, e.g. stadium photo)', 'asset'], ['login_headline', 'Headline', 'text'], ['login_subtext', 'Sub-text', 'text'],
    ['login_features', 'Highlights on the brand panel (one per line, up to 4)', 'list'], ['login_footer', 'Footer text (e.g. © Client 2026)', 'text']]],
  ['White-label platform (this admin panel)', [['admin_product_name', 'Product name', 'text'], ['client_name', 'Client name (shown in the browser title)', 'text'], ['admin_primary_color', 'Admin accent colour', 'color'], ['admin_logo_asset_id', 'Admin logo', 'asset'], ['favicon_asset_id', 'Favicon', 'asset']]],
];

FQ.pages.settings = async (main) => {
  const s = await FQ.api('/settings'); const edit = FQ.can('admin'); const getters = {}; const err = h('div', { class: 'error', hidden: true });
  const control = (key, label, type, extra) => {
    const v = s[key]; let el, get;
    if (type === 'text') { el = h('input', { value: v, class: extra === 'rtl' ? 'rtl' : '', disabled: !edit }); get = () => el.value; }
    else if (type === 'bool') { el = h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: v, disabled: !edit }), label); get = () => el.firstChild.checked; return [el, get, true]; }
    else if (type === 'num') { el = h('input', { type: 'number', value: v, disabled: !edit }); get = () => Math.round(Number(el.value)); }
    else if (type === 'dec') { el = h('input', { type: 'number', step: 0.05, value: v, disabled: !edit }); get = () => Number(el.value); }
    else if (type === 'sec') { el = h('input', { type: 'number', step: 0.5, value: v / 1000, disabled: !edit }); get = () => Math.round(Number(el.value) * 1000); }
    else if (type === 'select') { el = FQ.select(extra, v, { disabled: !edit }); get = () => el.value; }
    else if (type === 'color') { el = h('input', { type: 'color', value: v, disabled: !edit }); get = () => el.value; }
    else if (type === 'langs') { const boxes = ['en', 'ar'].map(l => h('label', { class: 'check' }, h('input', { type: 'checkbox', value: l, checked: v.includes(l), disabled: !edit }), l === 'en' ? 'English' : 'العربية')); el = h('div', { class: 'row' }, boxes); get = () => boxes.filter(b => b.firstChild.checked).map(b => b.firstChild.value); }
    else if (type === 'list') { el = h('textarea', { rows: 3, class: extra === 'rtl' ? 'rtl' : '', disabled: !edit, value: v.join('\n') }); get = () => el.value.split('\n').map(x => x.trim()).filter(Boolean); }
    else if (type === 'diff') { const ins = ['easy', 'medium', 'hard'].map(k => h('input', { type: 'number', step: 0.1, min: 0, value: v[k], disabled: !edit, style: { width: '90px' } })); el = h('div', { class: 'row' }, ['easy', 'medium', 'hard'].map((k, i) => h('label', { class: 'muted' }, k + ' × ', ins[i]))); get = () => ({ easy: Number(ins[0].value), medium: Number(ins[1].value), hard: Number(ins[2].value) }); }
    else if (type === 'asset') { el = FQ.assetPicker({ value: v }); get = () => el.getValue(); }
    return [FQ.field(label, el), get];
  };
  const panels = SECTIONS.map(([title, fields]) => h('div', { class: 'panel' }, h('h2', {}, title), h('div', { class: 'grid2' }, fields.map(([key, label, type, extra]) => { const [el, get] = control(key, label, type, extra); getters[key] = get; return el; }))));
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Game settings'), edit ? h('button', { class: 'btn primary', onclick: async () => {
    try { err.hidden = true; const values = {}; for (const k in getters) { const v = getters[k](); if (JSON.stringify(v) !== JSON.stringify(s[k])) values[k] = v; }
      if (!Object.keys(values).length) return FQ.toast('Nothing changed'); const r = await FQ.api('/settings', { method: 'PUT', body: { values } }); Object.assign(s, r); FQ.toast('Settings saved — the game picks them up on its next reload', 'ok');
      const b = await fetch('/api/admin/branding').then(x => x.json()); FQ.applyBranding(b); } catch (e) { err.textContent = e.message; err.hidden = false; FQ.fail(e); } } }, 'Save changes') : h('span', { class: 'muted' }, 'Read-only (administrators can edit)')),
    err, ...panels, h('p', { class: 'muted' }, 'Colours, logos, fonts and effects of the player screen live under Themes & colours. ', h('a', { href: '/admin/?preview=login', target: '_blank' }, 'Preview the login screen (save first)')));
};
})();
