/* Admin: bulk question import, prize claims, clear-test-results, system health card. Loaded before pages-system.js. */
'use strict';
(() => {
const FQ = window.FQ, h = FQ.h;
const MAX_IMG = 8 * 1024 * 1024;

/* =========================================================== BULK IMPORT (spreadsheet + image files) */
FQ.importWizard = function importWizard(game, onDone) {
  const st = { sheet: null, preview: null, files: new Map(), busy: false, cancel: false };
  const dt_en = h('input', { value: 'Who is this player?', placeholder: 'Who is this player?', style: { maxWidth: '320px' } });
  const dt_ar = h('input', { class: 'rtl', value: 'من هو هذا اللاعب؟', placeholder: 'من هو هذا اللاعب؟', style: { maxWidth: '320px' } });
  const publish = h('input', { type: 'checkbox', checked: true });
  const sheetIn = h('input', { type: 'file', accept: '.xlsx,.csv,.txt' });
  const imgIn = h('input', { type: 'file', accept: 'image/*', multiple: true });
  const dirIn = h('input', { type: 'file', accept: 'image/*', multiple: true, webkitdirectory: true });
  const out = h('div', { class: 'imp-out' }); const err = h('div', { class: 'error', hidden: true });
  const bar = h('i'); const prog = h('div', { class: 'upprog', hidden: true }, h('div', { class: 'uptrack' }, bar)); const progTxt = h('div', { class: 'muted small' }); prog.append(progTxt);
  const goBtn = h('button', { class: 'btn primary', disabled: true }, 'Import questions');
  const m = FQ.modal({ title: `Import questions into “${game.name_en || game.name_ar}”`, width: 1040, onClose: () => { st.cancel = true; },
    body: [
      h('p', { class: 'muted', style: { marginTop: 0 } }, 'One spreadsheet row = one question. Fill the template, choose it here, then choose the picture files it mentions. Nothing is saved until you press Import.'),
      h('div', { class: 'row' }, h('button', { class: 'btn small', onclick: () => FQ.download('/import/template.xlsx').catch(FQ.fail) }, '⬇ Excel template'),
        h('button', { class: 'btn small', onclick: () => FQ.download('/import/template.csv').catch(FQ.fail) }, '⬇ CSV template')),
      h('div', { class: 'imp-grid' },
        FQ.field('1 · Spreadsheet (.xlsx or .csv)', sheetIn),
        FQ.field('Default question text (English)', dt_en, 'Pre-filled; used for every row whose question text is empty. Change or clear it as needed.'), FQ.field('Default question text (Arabic)', dt_ar)),
      h('div', { class: 'imp-grid' },
        FQ.field('2 · Picture files', imgIn, 'Choose all the pictures (Ctrl+A in the folder)'), FQ.field('…or a whole folder', dirIn)),
      err, out, prog,
      h('label', { class: 'check', style: { marginTop: '10px' } }, publish, 'Publish the questions that are ready (otherwise they are saved as drafts)')],
    footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Close'), goBtn] });

  const key = (n) => String(n || '').trim().toLowerCase();
  const lookup = (fn) => st.files.get(key(fn));
  const problems = () => {
    const p = st.preview; if (!p) return ['Choose the spreadsheet first.'];
    const msgs = [];
    if (p.bad) msgs.push(`${p.bad} row${p.bad === 1 ? ' has' : 's have'} problems (fix the spreadsheet and choose it again).`);
    const missing = p.images.filter(fn => !lookup(fn)); if (missing.length) msgs.push(`${missing.length} picture${missing.length === 1 ? '' : 's'} not chosen yet: ${missing.slice(0, 4).join(', ')}${missing.length > 4 ? '…' : ''}`);
    const big = p.images.filter(fn => lookup(fn) && lookup(fn).size > MAX_IMG); if (big.length) msgs.push(`Too large (max 8 MB): ${big.join(', ')}`);
    return msgs;
  };
  const refreshGo = () => { const pr = problems(); goBtn.disabled = st.busy || pr.length > 0 || !st.preview || !st.preview.ok; };
  const render = () => {
    out.replaceChildren(); const p = st.preview; if (!p) { refreshGo(); return; }
    const pr = problems();
    out.append(h('div', { class: 'row tight', style: { margin: '10px 0 6px' } }, FQ.badge(`${p.ok} ready`, 'ok'), p.bad ? FQ.badge(`${p.bad} with problems`, 'bad') : null, FQ.badge(`${p.images.filter(lookup).length} / ${p.images.length} pictures`, p.images.every(lookup) ? 'ok' : 'off')),
      pr.length && p.ok + p.bad ? h('ul', { class: 'imp-problems' }, pr.map(x => h('li', {}, x))) : null,
      h('div', { class: 'tbl-wrap imp-table' }, h('table', {}, h('thead', {}, h('tr', {}, ['Row', 'Question', 'Options (✓ = correct)', 'Picture', 'After correct', 'Check'].map(x => h('th', {}, x)))),
        h('tbody', {}, p.rows.map(r => {
          const pic = (fn) => !fn ? h('span', { class: 'muted' }, '—') : lookup(fn) ? h('span', { class: 'ok-txt' }, '✓ ' + fn) : h('span', { class: 'bad-txt' }, '✗ ' + fn);
          return h('tr', {}, h('td', {}, r.row), h('td', {}, r.text_en || r.text_ar || '—'),
            h('td', {}, r.options.map(o => h('div', { class: o.slot === r.correct ? 'ok-txt' : '' }, (o.slot === r.correct ? '✓ ' : '') + (o.label_en || '') + (o.label_en && o.label_ar ? '  ·  ' : '') + (o.label_ar || '')))),
            h('td', {}, pic(r.image)), h('td', {}, pic(r.reveal_image)), h('td', {}, r.errors.length ? h('span', { class: 'bad-txt' }, r.errors.join('; ')) : h('span', { class: 'ok-txt' }, 'OK')));
        })))));
    refreshGo();
  };
  const readSheet = async () => {
    if (!st.sheet) return; err.hidden = true;
    const fd = new FormData(); fd.append('file', st.sheet);
    try {
      const r = await fetch(`/api/admin/games/${game.id}/import/preview?default_text_en=${encodeURIComponent(dt_en.value)}&default_text_ar=${encodeURIComponent(dt_ar.value)}`, { method: 'POST', headers: { Authorization: 'Bearer ' + FQ.token() }, body: fd });
      const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Could not read the spreadsheet');
      st.preview = d;
    } catch (e) { st.preview = null; err.textContent = e.message; err.hidden = false; }
    render();
  };
  sheetIn.onchange = () => { st.sheet = sheetIn.files[0] || null; readSheet(); };
  let t = null; for (const el of [dt_en, dt_ar]) el.addEventListener('input', () => { clearTimeout(t); t = setTimeout(readSheet, 400); });
  const addFiles = (list) => { for (const f of list) if (/\.(png|jpe?g|webp|gif)$/i.test(f.name)) st.files.set(key(f.name), f); render(); };
  imgIn.onchange = () => addFiles(imgIn.files); dirIn.onchange = () => addFiles(dirIn.files);

  goBtn.onclick = async () => {
    const p = st.preview; if (!p || problems().length) return;
    st.busy = true; st.cancel = false; goBtn.disabled = true; sheetIn.disabled = imgIn.disabled = dirIn.disabled = true; prog.hidden = false; err.hidden = true;
    const assets = {}; const names = p.images; let done = 0;
    try {
      for (const fn of names) {
        if (st.cancel) throw new Error('Cancelled');
        const f = lookup(fn); progTxt.textContent = `Uploading pictures ${done + 1} / ${names.length}: ${fn} (${FQ.fmtBytes(f.size)})`;
        const a = await FQ.upload(f, (r) => { bar.style.width = Math.round(((done + r) / (names.length + 1)) * 100) + '%'; });
        assets[fn.toLowerCase()] = a.id; done++; bar.style.width = Math.round((done / (names.length + 1)) * 100) + '%';
      }
      progTxt.textContent = 'Creating the questions…';
      const res = await FQ.api(`/games/${game.id}/import/commit`, { method: 'POST', body: { rows: p.rows.map(({ errors, languages, ...r }) => r), assets, publish: publish.checked, default_text_en: dt_en.value, default_text_ar: dt_ar.value } });
      bar.style.width = '100%'; prog.hidden = true; out.replaceChildren(
        h('div', { class: 'imp-done' }, h('h3', {}, `✓ ${res.created} question${res.created === 1 ? '' : 's'} imported`), publish.checked ? h('p', {}, `${res.published} published${res.left_as_draft.length ? `, ${res.left_as_draft.length} left as draft because they are not complete yet:` : '.'}`) : h('p', {}, 'Saved as drafts: review them and publish from the Questions page.'),
          res.left_as_draft.length ? h('ul', {}, res.left_as_draft.map(x => h('li', {}, `Row ${x.row}: ${x.issues.join(' ')}`))) : null));
      goBtn.hidden = true; if (onDone) onDone(res); FQ.toast(`${res.created} questions imported`, 'ok');
    } catch (e) { prog.hidden = true; err.textContent = e.message; err.hidden = false; st.busy = false; sheetIn.disabled = imgIn.disabled = dirIn.disabled = false; refreshGo(); }
  };
  render();
};

/* =========================================================== CLEAR TEST RESULTS */
FQ.clearResultsDialog = function clearResultsDialog(g, onDone) {
  const inp = h('input', { placeholder: g.slug, autocomplete: 'off' }); const go = h('button', { class: 'btn danger', disabled: true }, 'Delete all results');
  inp.oninput = () => { go.disabled = inp.value.trim() !== g.slug; };
  const m = FQ.modal({ title: 'Clear test results', width: 520, body: [
    h('p', {}, `This permanently deletes every played round of “${g.name_en || g.name_ar}” (${g.session_count} so far): players, scores, answers and prize codes. Questions, settings and images are kept. Other games are not touched.`),
    h('p', { class: 'muted' }, 'Do this before the real event starts so test plays do not appear in the leaderboard or the reports. It cannot be undone.'),
    h('div', { class: 'row' }, h('button', { class: 'btn small', onclick: () => FQ.download(`/sessions-export.csv?game_id=${g.id}&tz=${FQ.tz()}`).catch(FQ.fail) }, '⬇ Download them as CSV first')),
    FQ.field(`Type “${g.slug}” to confirm`, inp)],
    footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), go] });
  go.onclick = async () => { try { const r = await FQ.api(`/games/${g.id}/results/clear`, { method: 'POST', body: { confirm: inp.value.trim() } }); m.close(); FQ.toast(`${r.deleted} round${r.deleted === 1 ? '' : 's'} deleted`, 'ok'); if (onDone) onDone(); } catch (e) { FQ.fail(e); } };
  setTimeout(() => inp.focus(), 50);
};

/* =========================================================== PRIZE CLAIMS (staff page) */
FQ.pages.claims = async (main) => {
  const games = await FQ.loadGames(); let gameId = FQ.gameScope.get(); if (!games.some(g => String(g.id) === gameId)) gameId = '';
  let status = 'pending', page = 1;
  const input = h('input', { class: 'claim-input', placeholder: 'ABC-123', autocomplete: 'off', autocapitalize: 'characters', spellcheck: false, maxlength: 12 });
  const result = h('div', { class: 'claim-result' }); const listBox = h('div', { class: 'panel tbl-wrap' });
  const fmt = (c) => c.claimed ? h('span', {}, FQ.badge('collected', 'ok'), ' ', h('span', { class: 'muted small' }, `${c.claimed_by || ''} · ${FQ.fmtDate(c.claimed_at)}`)) : FQ.badge('waiting', 'off');
  const show = (c) => {
    result.replaceChildren(h('div', { class: 'claim-card ' + (c.claimed ? 'done' : 'ready') },
      h('div', { class: 'claim-code' }, c.code), h('h2', { style: { margin: '4px 0' } }, c.player_name || '(no name)'),
      h('div', { class: 'muted' }, `${c.game_name || ''} · ${c.correct}/${c.total} correct · won ${FQ.fmtDate(c.won_at)}`),
      h('div', { style: { margin: '14px 0' } }, c.claimed ? h('div', { class: 'bad-txt', style: { fontWeight: 700 } }, `Already collected by ${c.claimed_by} on ${FQ.fmtDate(c.claimed_at)}`) : h('div', { class: 'ok-txt', style: { fontWeight: 700 } }, 'Valid: the prize has not been collected yet')),
      h('div', { class: 'row' },
        !c.claimed && FQ.can('editor') ? h('button', { class: 'btn primary big', onclick: async () => { try { const r = await FQ.api(`/claims/${encodeURIComponent(c.code)}/redeem`, { method: 'POST', body: {} }); FQ.toast('Marked as collected', 'ok'); show(r); input.value = ''; loadList(); } catch (e) { FQ.fail(e); lookup(); } } }, '✓ Mark as collected') : null,
        c.claimed && FQ.can('admin') ? h('button', { class: 'btn', onclick: async () => { if (await FQ.confirm('Mark this prize as NOT collected again?', 'Undo', false)) { try { show(await FQ.api(`/claims/${encodeURIComponent(c.code)}/undo`, { method: 'POST' })); loadList(); } catch (e) { FQ.fail(e); } } } }, 'Undo collected') : null)));
  };
  const lookup = async () => {
    const code = input.value.trim(); if (!code) return;
    try { show(await FQ.api('/claims/' + encodeURIComponent(code))); } catch (e) { result.replaceChildren(h('div', { class: 'claim-card bad' }, h('b', {}, e.status === 404 ? 'Code not found' : 'Error'), h('div', { class: 'muted' }, e.message))); }
  };
  const loadList = async () => {
    const r = await FQ.api(`/claims?status=${status}&page=${page}&page_size=15${gameId ? '&game_id=' + gameId : ''}`); const pages = Math.max(1, Math.ceil(r.total / r.page_size));
    listBox.replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, ['Code', 'Player', 'Game', 'Won', 'Status', ''].map(x => h('th', {}, x)))),
      h('tbody', {}, r.items.map(c => h('tr', {}, h('td', {}, h('code', {}, c.code)), h('td', {}, c.player_name || '—'), h('td', {}, c.game_name || '—'), h('td', {}, FQ.fmtDate(c.won_at)), h('td', {}, fmt(c)),
        h('td', { class: 'actions' }, h('button', { class: 'btn small', onclick: () => { input.value = c.code; show(c); window.scrollTo({ top: 0, behavior: 'smooth' }); } }, 'Open')))))),
      r.items.length ? '' : h('p', { class: 'muted' }, status === 'pending' ? 'No prizes waiting. Winners appear here when a game gives claim codes (Games → Edit → Event features).' : 'Nothing here yet.'),
      h('div', { class: 'pager' }, h('button', { class: 'btn small', disabled: page <= 1, onclick: () => { page--; loadList(); } }, '‹ Prev'), h('span', { class: 'muted' }, `Page ${page} / ${pages} · ${r.total} winner${r.total === 1 ? '' : 's'} · ${r.pending} waiting`), h('button', { class: 'btn small', disabled: page >= pages, onclick: () => { page++; loadList(); } }, 'Next ›')));
  };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') lookup(); });
  input.addEventListener('input', () => { input.value = input.value.toUpperCase().replace(/[^A-Z0-9-]/g, ''); });
  main.append(h('div', { class: 'head' }, h('div', {}, h('h1', {}, 'Prize claims'), h('p', { class: 'muted', style: { margin: 0 } }, 'A winner shows the code (or QR) on screen. Type or scan it here, check the details, then mark the prize as collected.'))),
    h('div', { class: 'panel claim-box' }, h('div', { class: 'row' }, input, h('button', { class: 'btn primary big', onclick: lookup }, 'Look up')), result),
    h('div', { class: 'head', style: { marginTop: '18px' } }, h('h2', { style: { margin: 0 } }, 'Winners'), h('div', { class: 'row' },
      games.length > 1 ? FQ.gameSelect(games, gameId, { attrs: { onchange: (e) => { gameId = e.target.value; FQ.gameScope.set(gameId); page = 1; loadList(); } } }) : null,
      FQ.select([['pending', 'Waiting for pickup'], ['collected', 'Collected'], ['all', 'All']], status, { style: { width: 'auto' }, onchange: (e) => { status = e.target.value; page = 1; loadList(); } }))), listBox);
  await loadList(); setTimeout(() => input.focus(), 50);
};

/* =========================================================== SYSTEM HEALTH CARD (dashboard, admins) */
FQ.systemCard = async function systemCard() {
  let s; try { s = await FQ.api('/system'); } catch (e) { return null; }
  const up = s.uptime_seconds, upTxt = up >= 86400 ? Math.floor(up / 86400) + ' d ' + Math.floor(up % 86400 / 3600) + ' h' : up >= 3600 ? Math.floor(up / 3600) + ' h ' + Math.floor(up % 3600 / 60) + ' min' : Math.max(1, Math.floor(up / 60)) + ' min';
  const free = s.disk_total_bytes ? Math.round(100 * s.disk_free_bytes / s.disk_total_bytes) : null;
  const lowDisk = free !== null && (free < 10 || s.disk_free_bytes < 500 * 1048576);
  const lb = s.last_server_backup ? Date.now() - new Date(s.last_server_backup).getTime() : null; const backupStale = lb !== null && lb > 36 * 3600 * 1000;
  const row = (k, v, tone) => h('div', { class: 'sys-row' }, h('span', { class: 'muted' }, k), h('b', { class: tone || '' }, v));
  return h('div', { class: 'panel' }, h('h2', {}, 'System health'),
    row('Running for', upTxt), row('Database', FQ.fmtBytes(s.db_bytes)), row('Pictures', `${s.uploads.files} files · ${FQ.fmtBytes(s.uploads.bytes)}`),
    row('Disk free', free === null ? '—' : `${FQ.fmtBytes(s.disk_free_bytes)} (${free}%)`, lowDisk ? 'bad-txt' : ''),
    row('Rounds in the last 24 h', String(s.rounds_24h)),
    row('Server nightly backup', s.last_server_backup ? FQ.fmtDate(s.last_server_backup) : 'not found on this server', backupStale || !s.last_server_backup ? 'bad-txt' : 'ok-txt'),
    h('div', { class: 'btn-row', style: { marginTop: '12px' } }, h('button', { class: 'btn small primary', onclick: () => FQ.download('/backup', 'fq-backup.zip').catch(FQ.fail) }, '⬇ Download a backup now')),
    h('p', { class: 'muted small', style: { marginBottom: 0 } }, 'Download a backup before every event and keep it off the server. For alerts, point an uptime monitor (e.g. UptimeRobot) at /healthz.'));
};
})();
