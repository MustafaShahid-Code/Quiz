/* Admin page: Games. Every game owns its own questions; this is where games are created and configured. */
'use strict';
(() => {
const FQ = window.FQ, h = FQ.h;

/* Shared helpers: the "current game" is remembered per browser and scopes Questions / Results / Dashboard. */
FQ.gameScope = {
  get() { try { return localStorage.getItem('fq_game') || ''; } catch { return ''; } },
  set(v) { try { localStorage.setItem('fq_game', v || ''); } catch { /* storage blocked: ignore */ } },
};
FQ.loadGames = async () => (await FQ.api('/games')).items;
FQ.gameSelect = (games, value, opts = {}) => FQ.select([...(opts.all === false ? [] : [['', 'All games']]), ...games.map(g => [g.id, g.name_en || g.name_ar])], value ?? '', { style: { width: 'auto' }, ...opts.attrs });

const VAULT_GROUP = ['Vault screen', [
  ['vault_win_title_en', 'Title when the vault opens (English)', 'text'], ['vault_win_title_ar', 'Title when the vault opens (Arabic)', 'text', 'rtl'],
  ['vault_lose_message_en', 'Message when the answer is wrong (English)', 'text'], ['vault_lose_message_ar', 'Message when the answer is wrong (Arabic)', 'text', 'rtl'],
  ['vault_prize_hold_ms', 'Seconds the prize stays on screen', 'sec'],
  ['vault_prizes_title_en', 'Final screen heading (English)', 'text'], ['vault_prizes_title_ar', 'Final screen heading (Arabic)', 'text', 'rtl']]];
const OVERRIDES = [
  ['Texts on the player screen', [
    ['title_en', 'Title (English)', 'text'], ['title_ar', 'Title (Arabic)', 'text', 'rtl'],
    ['tagline_en', 'Tagline (English)', 'text'], ['tagline_ar', 'Tagline (Arabic)', 'text', 'rtl'],
    ['instructions_en', 'Instructions (English)', 'text'], ['instructions_ar', 'Instructions (Arabic)', 'text', 'rtl']]],
  ['Branding for this game', [
    ['branding_enabled', 'Show the sponsor / branding screen', 'bool'], ['branding_use_shared_slides', 'Also show the shared slides', 'bool'],
    ['branding_hint_en', 'Touch hint (English)', 'text'], ['branding_hint_ar', 'Touch hint (Arabic)', 'text', 'rtl']]],
  ['Rules', [
    ['questions_per_session', 'Questions per round (0 = all)', 'num'], ['retries_per_question', 'Retries per question', 'num'],
    ['randomize_questions', 'Shuffle questions', 'bool'], ['randomize_options', 'Shuffle answer options', 'bool'],
    ['answer_timer_enabled', 'Answer countdown on', 'bool'], ['answer_time_limit_ms', 'Seconds to answer', 'sec'],
    ['points_correct', 'Points per correct answer', 'num'], ['show_explanations', 'Show explanations', 'bool'],
    ['show_correct_on_wrong', 'After a wrong answer, show which one was right', 'bool']]],
];

FQ.pages.games = async (main) => {
  const [games, themesList, settings, types] = await Promise.all([FQ.loadGames(), FQ.api('/themes'), FQ.api('/settings'), FQ.api('/game-types')]);
  const edit = FQ.can('admin');
  const gameUrl = (g) => `${location.origin}/game/?game=${encodeURIComponent(g.slug)}`;

  const form = async (g) => {
    const isNew = !g;
    const v = g || { name_en: '', name_ar: '', slug: '', description_en: '', description_ar: '', cover_asset_id: null, theme_id: null, overrides: {}, enabled: true, sort_order: games.length };
    const f = {
      name_en: h('input', { value: v.name_en, placeholder: 'Guess the Player' }), name_ar: h('input', { class: 'rtl', value: v.name_ar, placeholder: 'خمّن اللاعب' }),
      slug: h('input', { value: v.slug, placeholder: 'guess-the-player', disabled: !isNew && v.is_default }),
      d_en: h('input', { value: v.description_en, placeholder: 'Who is hiding behind the eyes?' }), d_ar: h('input', { class: 'rtl', value: v.description_ar }),
      theme: FQ.select([['', 'Use the active theme'], ...themesList.map(t => [t.id, t.name])], v.theme_id ?? ''),
      pw: h('input', { type: 'text', autocomplete: 'off', placeholder: v.has_password ? 'Leave empty to keep the current password' : 'No password — anyone with the link can play' }),
      pwClear: h('input', { type: 'checkbox' }),
      type: FQ.select(types.map(t => [t.id, t.label]), v.game_type || 'quiz', { disabled: !isNew && v.question_count > 0 }),
      enabled: h('input', { type: 'checkbox', checked: v.enabled, disabled: !!v.is_default }), order: h('input', { type: 'number', value: v.sort_order }),
    };
    const cover = FQ.assetPicker({ value: v.cover_asset_id });
    const ovGetters = {};
    const vaultPanel = (() => { const [title, fields] = VAULT_GROUP; return [title, fields]; })();
    const mkPanel = (([title, fields]) => h('div', { style: { marginTop: '14px' } }, h('h4', { style: { margin: '0 0 8px' } }, title),
      h('div', { class: 'grid2' }, fields.map(([key, label, type, rtl]) => {
        const has = key in v.overrides; const cur = has ? v.overrides[key] : settings[key];
        const toggle = h('input', { type: 'checkbox', checked: has });
        let el, get;
        if (type === 'bool') { el = h('input', { type: 'checkbox', checked: !!cur }); get = () => el.checked; }
        else if (type === 'num') { el = h('input', { type: 'number', value: cur }); get = () => Math.round(Number(el.value)); }
        else if (type === 'sec') { el = h('input', { type: 'number', step: 0.5, value: cur / 1000 }); get = () => Math.round(Number(el.value) * 1000); }
        else { el = h('input', { value: cur, class: rtl || '' }); get = () => el.value; }
        const sync = () => { el.disabled = !toggle.checked; }; toggle.addEventListener('change', sync); sync();
        ovGetters[key] = () => (toggle.checked ? get() : undefined);
        return h('div', { class: 'field' }, h('label', {}, label), h('div', { class: 'row tight' }, h('label', { class: 'check small', title: 'Tick to use a different value for this game only' }, toggle, 'Override'), el));
      }))));
    const ovPanels = OVERRIDES.map(mkPanel);
    const vaultBox = h('div', {}, mkPanel(VAULT_GROUP));
    const syncType = () => { vaultBox.hidden = f.type.value !== 'vault'; };
    f.type.addEventListener('change', syncType); syncType();
    const err = h('div', { class: 'error', hidden: true });
    const payload = () => {
      const overrides = {}; for (const k in ovGetters) { if (VAULT_GROUP[1].some(x => x[0] === k) && f.type.value !== 'vault') continue; const x = ovGetters[k](); if (x !== undefined) overrides[k] = x; }
      return { name_en: f.name_en.value, name_ar: f.name_ar.value, slug: f.slug.value, description_en: f.d_en.value, description_ar: f.d_ar.value,
        game_type: f.type.value, access_password: f.pw.value || null, clear_access_password: f.pwClear.checked, cover_asset_id: cover.getValue(), theme_id: f.theme.value ? Number(f.theme.value) : null, overrides, enabled: f.enabled.checked, sort_order: Number(f.order.value) || 0 };
    };
    const m = FQ.modal({ title: isNew ? 'New game' : `Edit “${v.name_en || v.name_ar}”`, width: 860,
      body: [h('div', { class: 'grid2' }, FQ.field('Name (English)', f.name_en), FQ.field('الاسم (Arabic)', f.name_ar),
        FQ.field('Game type', f.type, isNew ? 'Quiz: pick the right answer. Vault: the right answer opens a vault and reveals the prize attached to that question. Fixed once the game has questions.' : 'Fixed once the game has questions.'), h('div'),
        FQ.field('Short description (English)', f.d_en, 'Shown on the game-selection card.'), FQ.field('الوصف (Arabic)', f.d_ar)),
        h('div', { class: 'grid3', style: { marginTop: '14px' } }, FQ.field('Link name', f.slug, 'Used in the link: /game/?game=<this>. Lowercase letters, numbers, dashes. Leave empty to generate it.'),
          FQ.field('Theme', f.theme, 'Each game can have its own look (colours, logos, fonts).'), FQ.field('Order', f.order)),
        h('div', { style: { marginTop: '14px', maxWidth: '520px' } }, FQ.field('Access password', f.pw, 'Players type only this password (no username) when the game opens. Each game has its own; two games may share the same one. Changing it signs out every screen that had unlocked the game.'),
          v.has_password ? h('label', { class: 'check', style: { marginTop: '6px' } }, f.pwClear, 'Remove the password (open access)') : null),
        h('div', { style: { marginTop: '14px' } }, FQ.field('Cover image (optional)', cover, 'Shown on the game-selection card.')),
        h('div', { class: 'row', style: { marginTop: '10px' } }, h('label', { class: 'check' }, f.enabled, v.is_default ? 'Enabled (the default game is always on)' : 'Enabled — players can see and play it')),
        h('h3', { style: { marginTop: '20px' } }, 'Settings for this game'), h('p', { class: 'muted' }, 'Anything not overridden uses the global Game settings. Add this game’s own sponsor slides under Branding slides (choose this game there); logos, colours and fonts come from its theme. Questions are never shared between games.'),
        vaultBox, ...ovPanels, err],
      footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'),
        h('button', { class: 'btn primary', onclick: async () => { try { err.hidden = true;
          await FQ.api(isNew ? '/games' : '/games/' + v.id, { method: isNew ? 'POST' : 'PUT', body: payload() });
          FQ.toast(isNew ? 'Game created — now add its questions' : 'Game saved', 'ok'); m.close(); FQ.route(); } catch (e) { err.textContent = e.message; err.hidden = false; } } }, isNew ? 'Create game' : 'Save')] });
  };

  const card = (g) => h('div', { class: 'panel game-card' + (g.enabled ? '' : ' off') },
    h('div', { class: 'row', style: { justifyContent: 'space-between', alignItems: 'flex-start' } },
      h('div', { class: 'row tight', style: { alignItems: 'center' } }, g.cover_url ? h('img', { class: 'thumb', src: g.cover_url, alt: '' }) : h('div', { class: 'thumb text' }, '🎮'),
        h('div', {}, h('h2', { style: { margin: 0 } }, g.name_en || g.name_ar), g.name_ar && g.name_en ? h('div', { class: 'muted rtl' }, g.name_ar) : null)),
      h('div', { class: 'row tight' }, g.is_default ? FQ.badge('default', 'ok') : null, g.has_password ? FQ.badge('🔒 password', 'off') : null, g.game_type === 'vault' ? FQ.badge('vault', 'sim') : null, FQ.badge(g.enabled ? 'enabled' : 'disabled', g.enabled ? 'ok' : 'off'))),
    h('p', { class: 'muted' }, g.description_en || g.description_ar || 'No description.'),
    h('div', { class: 'row tight' }, FQ.badge(`${g.published_count} live question${g.published_count === 1 ? '' : 's'}`, g.published_count ? 'ok' : 'bad'),
      h('span', { class: 'muted small' }, `${g.question_count} total · ${g.session_count} round${g.session_count === 1 ? '' : 's'} played`)),
    h('div', { class: 'muted small', style: { margin: '8px 0', wordBreak: 'break-all' } }, h('code', {}, `/game/?game=${g.slug}`)),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn small primary', onclick: () => { FQ.gameScope.set(String(g.id)); FQ.go('questions'); } }, 'Questions'),
      h('a', { class: 'btn small', href: `/game/?game=${encodeURIComponent(g.slug)}`, target: '_blank', rel: 'noopener' }, '▶ Play'),
      h('button', { class: 'btn small', onclick: async () => { try { await navigator.clipboard.writeText(gameUrl(g)); FQ.toast('Link copied', 'ok'); } catch { FQ.toast(gameUrl(g)); } } }, 'Copy link'),
      edit ? h('button', { class: 'btn small', onclick: () => form(g) }, 'Edit') : null,
      edit ? FQ.menu('More ▾', [
        !g.is_default && { label: 'Make default', onclick: async () => { try { await FQ.api(`/games/${g.id}/make-default`, { method: 'POST' }); FQ.toast('Default game changed', 'ok'); FQ.route(); } catch (e) { FQ.fail(e); } } },
        !g.is_default && { label: 'Delete…', danger: true, onclick: async () => { if (await FQ.confirm(`Delete the game “${g.name_en || g.name_ar}”? This only works when it has no questions or results.`)) { try { await FQ.api('/games/' + g.id, { method: 'DELETE' }); FQ.route(); } catch (e) { FQ.fail(e); } } } }]) : null));

  main.append(h('div', { class: 'head' }, h('div', {}, h('h1', {}, 'Games'), h('p', { class: 'muted', style: { margin: 0 } }, 'Each game has its own questions, and can have its own look and rules. Players choose a game on the start screen, or you can link straight to one.')),
    edit ? h('button', { class: 'btn primary', onclick: () => form(null) }, '+ New game') : null),
    h('div', { class: 'game-grid' }, games.map(card)));
};
})();
