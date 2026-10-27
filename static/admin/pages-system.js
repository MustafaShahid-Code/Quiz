/* Admin pages: dashboard, sensor & calibration, results, users */
'use strict';
(() => {
const FQ = window.FQ, h = FQ.h;

/* =========================================================== DASHBOARD */
FQ.pages.dashboard = async (main) => {
  const games = await FQ.loadGames(); let scope = FQ.gameScope.get(); if (!games.some(g => String(g.id) === scope)) scope = '';
  const restricted = !FQ.state.user.all_games && FQ.state.user.role !== 'admin'; if (restricted && !scope && games[0]) scope = String(games[0].id);
  const [st, sensor] = await Promise.all([FQ.api('/stats' + (scope ? '?game_id=' + scope : '')), FQ.api('/sensor/status')]);
  const hour = new Date().getHours(); const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const stat = (icon, tone, label, value, sub) => h('div', { class: 'stat-card ' + tone }, h('div', { class: 'stat-ico' }, FQ.icon(icon, 22)), h('div', {}, h('span', { class: 'stat-label' }, label), h('b', {}, value), h('span', { class: 'stat-sub' }, sub)));
  const pct = st.responses.total ? Math.round(100 * st.responses.correct / st.responses.total) : null;
  const days = st.sessions_per_day, maxd = Math.max(1, ...days.map(d => d.sessions));
  const chart = days.length ? h('div', { class: 'bars' }, days.map(d => h('div', { class: 'bar', title: `${d.day}: ${d.sessions} game(s)` }, h('i', { style: { height: Math.max(6, d.sessions / maxd * 100) + '%' } }), h('span', {}, d.day.slice(5)))))
    : h('p', { class: 'muted' }, 'No games played yet. Open the game and play one round to see activity here.');
  const sensorTone = sensor.state === 'ok' ? 'ok' : sensor.state === 'disabled' ? 'off' : 'bad';
  const checks = [
    [st.questions.published > 0, 'Publish at least one question', 'questions'],
    [null, 'Set the client’s colours, logos and fonts', 'themes'],
    [null, 'Add the client’s sponsor slides', 'slides'],
    [sensor.source_type === 'none' ? null : sensor.calibrated, 'Calibrate the touch sensor (only when using the LiDAR)', 'sensor'],
  ];
  main.append(
    h('div', { class: 'head' }, h('div', {}, h('h1', {}, `${greet}, ${FQ.state.user.username}`), h('p', { class: 'muted', style: { margin: 0 } }, 'Here is how the game is doing.')),
      h('div', { class: 'row' }, games.length > 1 ? FQ.gameSelect(games, scope, { all: !restricted, attrs: { onchange: (e) => { FQ.gameScope.set(e.target.value); FQ.route(); } } }) : null, FQ.can('editor') ? h('button', { class: 'btn', onclick: () => FQ.go('questions') }, '+ Add question') : null, h('a', { class: 'btn primary', href: '/game/' + (scope ? '?game=' + encodeURIComponent((games.find(g => String(g.id) === scope) || {}).slug) : ''), target: '_blank', rel: 'noopener' }, '▶  Open the game'))),
    st.questions.published === 0 ? h('div', { class: 'error' }, 'No published questions: the game cannot start. Publish at least one question.') : '',
    h('div', { class: 'stat-grid' },
      stat('questions', 'blue', 'Published questions', st.questions.published, `${st.questions.draft} draft · ${st.questions.unpublished} unpublished`),
      stat('results', 'green', 'Games played', st.sessions.total, `${st.sessions.finished} finished`),
      stat('characters', 'amber', 'Average result', st.avg_percent_correct == null ? '—' : st.avg_percent_correct + '%', 'of questions answered correctly'),
      stat('assets', 'violet', 'Answers recorded', st.responses.total, pct == null ? 'no answers yet' : `${pct}% correct`)),
    h('div', { class: 'dash-grid' },
      h('div', { class: 'panel' }, h('h2', {}, 'Games per day'), h('p', { class: 'muted', style: { marginTop: '-6px' } }, 'Last 14 days with activity'), chart),
      h('div', { class: 'panel' }, h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h2', { style: { margin: 0 } }, 'Touch sensor'), FQ.badge(sensor.state, sensorTone)),
        h('dl', { class: 'kv', style: { marginTop: '14px', gridTemplateColumns: '150px 1fr' } },
          h('dt', {}, 'Source'), h('dd', {}, sensor.source_type + (sensor.source === 'simulated' && sensor.source_type !== 'none' ? ' (simulated)' : '')),
          h('dt', {}, 'Calibrated'), h('dd', {}, sensor.calibrated ? 'yes' : 'no'), h('dt', {}, 'Hardware validated'), h('dd', {}, sensor.validated ? 'yes' : 'no')),
        h('p', { class: 'muted' }, 'Mouse, touch screen and keyboard always work as a fallback.'), h('button', { class: 'btn small', onclick: () => FQ.go('sensor') }, 'Sensor & calibration →'))),
    h('div', { class: 'dash-grid' },
      h('div', { class: 'panel' }, h('h2', {}, 'Hardest questions'), st.hardest_questions.length ? st.hardest_questions.map(q => h('div', { class: 'meter-row' }, h('div', { class: 'meter-top' }, h('span', { class: 'qt' }, q.question_text), h('b', {}, q.pct_correct + '%')),
        h('div', { class: 'meter' }, h('i', { style: { width: q.pct_correct + '%' } })), h('span', { class: 'muted small' }, q.answers + ' answers'))) : h('p', { class: 'muted' }, 'Appears once a question has at least three answers.')),
      h('div', { class: 'panel' }, h('h2', {}, 'Getting ready for a client'), h('div', { class: 'checklist' }, checks.map(([ok, label, page]) => h('a', { class: 'check-item' + (ok ? ' done' : ''), onclick: () => FQ.go(page) }, h('span', { class: 'tick' + (ok === null ? ' na' : '') }, ok ? '✓' : ok === null ? '›' : ''), h('span', {}, label)))),
        h('h3', { style: { marginTop: '18px' } }, 'Input sources used'), Object.keys(st.input_sources).length ? h('div', { class: 'row tight' }, Object.entries(st.input_sources).map(([k, v]) => h('span', {}, FQ.badge(k, k === 'simulated' ? 'sim' : ''), ' ' + v))) : h('p', { class: 'muted' }, 'No answers yet.'))));
};

/* =========================================================== RESULTS */
FQ.pages.results = async (main) => {
  let page = 1, lang = '', gameId = FQ.gameScope.get(); const games = await FQ.loadGames(); if (!games.some(g => String(g.id) === gameId)) gameId = '';
  const box = h('div', { class: 'panel tbl-wrap' });
  const load = async () => {
    const r = await FQ.api(`/sessions?page=${page}&page_size=20&lang=${lang}${gameId ? '&game_id=' + gameId : ''}`); const pages = Math.max(1, Math.ceil(r.total / r.page_size));
    box.replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, ['Started', 'Game', 'Player', 'Language', 'Score', 'Correct', 'Result', 'Input', 'Finished', ''].map(x => h('th', {}, x)))),
      h('tbody', {}, r.items.map(s => h('tr', {}, h('td', {}, FQ.fmtDate(s.started_at)), h('td', {}, s.game_name || '—'), h('td', {}, s.player_name || '—'), h('td', {}, s.lang), h('td', {}, s.score), h('td', {}, `${s.correct_count} / ${s.total_questions}`),
        h('td', {}, s.outcome ? FQ.badge(s.outcome === 'win' ? 'WIN' : 'LOSE', s.outcome === 'win' ? 'ok' : 'bad') : '—'),
        h('td', {}, (s.sources || '').split(',').filter(Boolean).map(x => FQ.badge(x, x === 'simulated' ? 'sim' : ''))), h('td', {}, s.finished_at ? FQ.badge('yes', 'ok') : FQ.badge('abandoned', 'off')),
        h('td', { class: 'actions' }, h('button', { class: 'btn small', onclick: () => detail(s.id) }, 'Details')))))),
      r.items.length ? '' : h('p', { class: 'muted' }, 'No games played yet.'),
      h('div', { class: 'pager' }, h('button', { class: 'btn small', disabled: page <= 1, onclick: () => { page--; load(); } }, '‹ Prev'), h('span', { class: 'muted' }, `Page ${page} / ${pages} · ${r.total} games`), h('button', { class: 'btn small', disabled: page >= pages, onclick: () => { page++; load(); } }, 'Next ›')));
  };
  const detail = async (id) => {
    const d = await FQ.api('/sessions/' + id).catch(FQ.fail); if (!d) return;
    FQ.modal({ title: 'Game details', width: 900, body: [h('p', {}, `${d.player_name ? 'Player: ' + d.player_name + ' · ' : ''}Score ${d.score} · ${d.correct_count}/${d.total_questions} correct · ${d.lang}${d.outcome ? ' · ' + d.outcome.toUpperCase() : ''}`),
      h('table', {}, h('thead', {}, h('tr', {}, ['#', 'Question', 'Answer', 'Result', 'Prize', 'Attempt', 'Input'].map(x => h('th', {}, x)))),
        h('tbody', {}, d.responses.map((r, i) => h('tr', {}, h('td', {}, i + 1), h('td', {}, r.question_text), h('td', {}, r.selected_text || '—'), h('td', {}, FQ.badge(r.is_correct ? 'correct' : 'wrong', r.is_correct ? 'ok' : 'bad')), h('td', {}, r.prize_name || '—'), h('td', {}, r.attempt_no), h('td', {}, FQ.badge(r.input_source, r.input_source === 'simulated' ? 'sim' : ''))))))] });
  };
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Results'), h('div', { class: 'row' }, FQ.gameSelect(games, gameId, { attrs: { onchange: (e) => { gameId = e.target.value; FQ.gameScope.set(gameId); page = 1; load(); } } }), FQ.select([['', 'All languages'], ['en', 'English'], ['ar', 'العربية']], '', { onchange: (e) => { lang = e.target.value; page = 1; load(); } }))), box);
  await load();
};

/* =========================================================== USERS */
FQ.pages.users = async (main) => {
  const box = h('div', { class: 'panel tbl-wrap' });
  const load = async () => {
    const list = await FQ.api('/users'); const games = await FQ.loadGames();
    const gn = (u) => u.all_games ? FQ.badge('all games', 'off') : h('div', { class: 'row tight' }, u.game_ids.map(id => { const g = games.find(x => x.id === id); return FQ.badge(g ? (g.name_en || g.name_ar) : '#' + id, 'ok'); }));
    box.replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, ['User', 'Role', 'Games', 'Active', 'Last sign-in', ''].map(x => h('th', {}, x)))),
      h('tbody', {}, list.map(u => h('tr', {}, h('td', {}, u.username), h('td', {}, FQ.badge(u.role)), h('td', {}, gn(u)), h('td', {}, u.is_active ? 'yes' : 'no'), h('td', { class: 'muted' }, FQ.fmtDate(u.last_login_at)),
        h('td', { class: 'actions' }, h('button', { class: 'btn small', onclick: () => edit(u).catch(FQ.fail) }, 'Edit'), u.id === FQ.state.user.id ? null : h('button', { class: 'btn small danger', onclick: async () => { if (await FQ.confirm(`Delete user “${u.username}”?`)) { await FQ.api('/users/' + u.id, { method: 'DELETE' }).catch(FQ.fail); load(); } } }, 'Delete')))))));
  };
  const edit = async (u) => {
    const games = await FQ.loadGames();
    const access = FQ.select([['all', 'All games'], ['some', 'Only the games ticked below']], !u || u.all_games ? 'all' : 'some');
    const gBoxes = games.map(g => h('label', { class: 'check' }, h('input', { type: 'checkbox', value: g.id, checked: !!u && u.game_ids.includes(g.id) }), g.name_en || g.name_ar));
    const gBox = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '6px', margin: '4px 0 12px' } }, gBoxes);
    const syncAccess = () => { gBox.hidden = access.value === 'all' || role.value === 'admin'; access.disabled = role.value === 'admin'; };
    const un = h('input', { value: u ? u.username : '', disabled: !!u }), pw = h('input', { type: 'password', autocomplete: 'new-password' }), role = FQ.select([['viewer', 'Viewer – read only'], ['editor', 'Editor – content & branding'], ['admin', 'Admin – everything']], u ? u.role : 'editor');
    const act = h('input', { type: 'checkbox', checked: u ? u.is_active : true }), err = h('div', { class: 'error', hidden: true });
    access.addEventListener('change', syncAccess); role.addEventListener('change', syncAccess); syncAccess();
    const access_body = () => ({ all_games: access.value === 'all' || role.value === 'admin', game_ids: gBoxes.map(b => b.firstChild).filter(i => i.checked).map(i => Number(i.value)) });
    const m = FQ.modal({ title: u ? 'Edit user' : 'New user', width: 480, body: [FQ.field('Username', un), FQ.field(u ? 'New password (leave empty to keep)' : 'Temporary password', pw, 'At least 10 characters with upper case, lower case and a digit. The user must change it at first sign-in.'), FQ.field('Role', role), FQ.field('Game access', access, 'Staff for one customer should only see that customer’s game, questions, slides and results. Admins always see everything.'), gBox, u ? h('label', { class: 'check' }, act, 'Active') : null, err],
      footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), h('button', { class: 'btn primary', onclick: async () => {
        try { if (u) await FQ.api('/users/' + u.id, { method: 'PUT', body: { role: role.value, is_active: act.checked, password: pw.value || null, ...access_body() } }); else await FQ.api('/users', { method: 'POST', body: { username: un.value, password: pw.value, role: role.value, ...access_body() } });
          m.close(); load(); FQ.toast('Saved', 'ok'); } catch (e) { err.textContent = e.message; err.hidden = false; } } }, 'Save')] });
  };
  main.append(h('div', { class: 'head' }, h('h1', {}, 'Users'), h('button', { class: 'btn primary', onclick: () => edit(null).catch(FQ.fail) }, '+ New user')), box);
  await load();
};

/* =========================================================== SENSOR */
FQ.pages.sensor = async (main) => {
  const admin = FQ.can('admin');
  const [cfg, st] = await Promise.all([FQ.api('/sensor/config'), FQ.api('/sensor/status')]);
  const statusBox = h('div', { class: 'panel' }), canvas = h('canvas', { class: 'diag', width: 1000, height: 420 });
  const renderStatus = (s) => statusBox.replaceChildren(h('h2', {}, 'Sensor status'), h('dl', { class: 'kv' },
    h('dt', {}, 'State'), h('dd', {}, FQ.badge(s.state, s.state === 'ok' ? 'ok' : s.state === 'disabled' ? 'off' : 'bad'), s.last_error ? h('span', { class: 'warn-text' }, '  ' + s.last_error) : null),
    h('dt', {}, 'Source'), h('dd', {}, `${s.source_type}${s.source === 'simulated' ? ' — SIMULATED, not real sensor input' : ''}`),
    h('dt', {}, 'Scan rate'), h('dd', {}, s.scan_hz + ' Hz · last scan ' + (s.last_scan_age_s == null ? '—' : s.last_scan_age_s + ' s ago')),
    h('dt', {}, 'Touches / reconnects'), h('dd', {}, `${s.touches_total} / ${s.reconnects}`),
    h('dt', {}, 'Calibrated'), h('dd', {}, s.calibrated ? `yes (error ${(s.calibration_rmse * 100).toFixed(2)}% of screen)` : 'no'),
    h('dt', {}, 'Hardware validated'), h('dd', {}, s.validated ? FQ.badge('validated', 'ok') : FQ.badge('not validated', 'off'))),
    s.hardware_note ? h('p', { class: 'muted' }, s.hardware_note) : null,
    h('p', { class: 'muted' }, 'A LiDAR is a distance scanner. Touch is only reported after calibration and an accuracy test on the real screen; pose recognition needs a camera and is not provided by the LiDAR.'));
  renderStatus(st);

  /* --- configuration */
  const f = { name: h('input', { value: cfg.name, disabled: !admin }), model: FQ.select([['S2', 'Slamtec RPLIDAR S2'], ['S3', 'Slamtec RPLIDAR S3'], ['other', 'Other']], cfg.sensor_model, { disabled: !admin }),
    src: FQ.select([['none', 'Disabled (mouse / keyboard / touchscreen only)'], ['simulator', 'Simulator (development)'], ['serial', 'Serial driver (rplidar-roboticia, A-series protocol – unverified for S2/S3)'], ['subprocess', 'Official-SDK bridge program (JSON lines)'], ['replay', 'Replay a recorded scan file']], cfg.source_type, { disabled: !admin }),
    port: h('input', { value: cfg.params.port || '', placeholder: '/dev/ttyUSB0 or COM3', disabled: !admin }), baud: h('input', { type: 'number', value: cfg.params.baudrate || 1000000, disabled: !admin }),
    cmd: h('input', { value: cfg.params.command || '', placeholder: '/opt/fq/sdk_bridge --port /dev/ttyUSB0', disabled: !admin }), path: h('input', { value: cfg.params.path || '', placeholder: 'recorded.jsonl', disabled: !admin }) };
  const th = cfg.thresholds; const thInputs = {}; const thDefs = [['min_dist_mm', 'Ignore closer than (mm)'], ['max_dist_mm', 'Ignore farther than (mm)'], ['cluster_gap_mm', 'Cluster gap (mm)'], ['max_cluster_width_mm', 'Max object width (mm)'], ['min_cluster_points', 'Min points per object'], ['confirm_scans', 'Scans to confirm a touch'], ['release_scans', 'Scans to release'], ['debounce_ms', 'Debounce (ms)'], ['background_tolerance_mm', 'Background tolerance (mm)'], ['uv_margin', 'Margin outside screen (0–0.2)']];
  thDefs.forEach(([k]) => thInputs[k] = h('input', { type: 'number', step: 'any', value: th[k], disabled: !admin }));
  const useBg = h('input', { type: 'checkbox', checked: th.use_background, disabled: !admin });
  const cfgErr = h('div', { class: 'error', hidden: true });
  const configPanel = h('div', { class: 'panel' }, h('h2', {}, 'Configuration'),
    h('div', { class: 'grid2' }, FQ.field('Name', f.name), FQ.field('Sensor model', f.model), FQ.field('Source', f.src, cfg.subprocess_allowed ? null : 'The SDK-bridge option is disabled on this server (start with FQ_ALLOW_SUBPROCESS_SOURCE=1).'),
      FQ.field('Serial port', f.port), FQ.field('Baud rate', f.baud, 'S2: 1,000,000 · S3: 1,000,000 (check the sensor datasheet)'), FQ.field('Bridge command', f.cmd), FQ.field('Replay file', f.path)),
    h('h3', { style: { marginTop: '18px' } }, 'Detection thresholds'), h('div', { class: 'grid4' }, thDefs.map(([k, l]) => FQ.field(l, thInputs[k]))),
    h('label', { class: 'check', style: { marginTop: '12px' } }, useBg, 'Ignore static background (learn it with the screen clear)'), cfgErr,
    admin ? h('div', { class: 'row', style: { marginTop: '14px' } }, h('button', { class: 'btn primary', onclick: async () => {
      try { cfgErr.hidden = true; const thresholds = {}; thDefs.forEach(([k]) => thresholds[k] = Number(thInputs[k].value)); thresholds.use_background = useBg.checked;
        await FQ.api('/sensor/config', { method: 'PUT', body: { name: f.name.value, sensor_model: f.model.value, source_type: f.src.value, params: { port: f.port.value, baudrate: Math.round(Number(f.baud.value)), command: f.cmd.value, path: f.path.value }, thresholds } });
        FQ.toast('Saved. Changing source or thresholds clears the hardware validation.', 'ok'); FQ.route(); } catch (e) { cfgErr.textContent = e.message; cfgErr.hidden = false; } } }, 'Save & apply'),
      h('button', { class: 'btn', onclick: async () => { await FQ.api('/sensor/restart', { method: 'POST' }).catch(FQ.fail); FQ.toast('Restarting sensor connection'); } }, 'Restart sensor')) : null);

  /* --- live view */
  const ctx = canvas.getContext('2d'); let last = null, quad = st.screen_quad_mm;
  const draw = () => { const W = canvas.width, H = canvas.height; ctx.fillStyle = '#0b1030'; ctx.fillRect(0, 0, W, H);
    const R = 3000, sc = Math.min(W / 2, H) / R * 0.95, ox = W / 2, oy = H - 14; // sensor at bottom-centre, x right, y forward (approx. viewing)
    const P = (x, y) => [ox + x * sc, oy - y * sc * 1]; ctx.strokeStyle = '#26307a'; ctx.fillStyle = '#6a77c8'; ctx.font = '12px sans-serif';
    for (let r = 500; r <= R; r += 500) { ctx.beginPath(); ctx.arc(ox, oy, r * sc, Math.PI, 2 * Math.PI); ctx.stroke(); ctx.fillText(r / 1000 + ' m', ox + r * sc + 2, oy - 4); }
    if (quad) { ctx.strokeStyle = '#3ddc84'; ctx.lineWidth = 2; ctx.beginPath(); quad.forEach(([x, y], i) => { const [px, py] = P(x, y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.closePath(); ctx.stroke(); ctx.lineWidth = 1; }
    if (last) { ctx.fillStyle = '#9fb2ff'; last.points.forEach(([x, y]) => { const [px, py] = P(x, y); ctx.fillRect(px - 1, py - 1, 2, 2); });
      ctx.strokeStyle = '#ffd814'; last.candidates.forEach(c => { const [px, py] = P(c.x, c.y); ctx.beginPath(); ctx.arc(px, py, 9, 0, 6.3); ctx.stroke(); });
      ctx.fillStyle = '#fff'; ctx.fillText(`${last.hz} Hz · ${last.points.length} points · ${last.candidates.length} candidate(s)`, 10, 18); }
    else { ctx.fillStyle = '#9aa4e0'; ctx.fillText('Waiting for scan data… (the sensor must be connected and enabled)', 10, 18); } };
  draw();
  let ws; const connect = () => { ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/admin/sensor/ws?token=${encodeURIComponent(FQ.token())}`);
    ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === 'scan') { last = m; draw(); } }; };
  connect();
  const poll = setInterval(async () => { if (!document.body.contains(canvas)) { clearInterval(poll); ws && ws.close(); return; } try { const s = await FQ.api('/sensor/status'); quad = s.screen_quad_mm; renderStatus(s); } catch (e) { /* ignore */ } }, 3000);

  /* --- simulator pad */
  let simPanel = null;
  if (st.source_type === 'simulator' && FQ.can('editor')) {
    const pad = h('div', { class: 'sim-screen' }); pad.addEventListener('click', async (e) => { const r = pad.getBoundingClientRect(); const u = (e.clientX - r.left) / r.width, v = (e.clientY - r.top) / r.height;
      const d = h('div', { class: 'dot', style: { left: u * 100 + '%', top: v * 100 + '%' } }); pad.appendChild(d); setTimeout(() => d.remove(), 600); await FQ.api('/sensor/simulate-touch', { method: 'POST', body: { u, v } }).catch(FQ.fail); });
    simPanel = h('div', { class: 'panel' }, h('h2', {}, 'Simulator pad ', FQ.badge('simulated', 'sim')), h('p', { class: 'muted' }, 'Click to inject a synthetic scan touch. Answers given this way are recorded as “simulated” and never count as hardware validation.'), pad);
  }

  /* --- calibration & validation (full screen target overlay on the projector) */
  const calInfo = h('div', { class: 'muted' });
  const showCal = (c) => calInfo.textContent = c.calibrated ? `Calibrated, error ${(c.calibration_rmse * 100).toFixed(2)}% of the screen width.` : 'Not calibrated: touches cannot be mapped to the screen yet.';
  showCal(st);
  const targetOverlay = (title) => { const o = h('div', { style: { position: 'fixed', inset: 0, background: '#000', zIndex: 1000, color: '#fff', cursor: 'none' } });
    const msg = h('div', { style: { position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', textAlign: 'center', font: '600 22px sans-serif', opacity: .85, whiteSpace: 'pre-line' } }, title);
    const dot = h('div', { style: { position: 'absolute', width: '56px', height: '56px', margin: '-28px', border: '5px solid #ffd814', borderRadius: '50%', display: 'none' } }, h('div', { style: { position: 'absolute', inset: '20px', background: '#ffd814', borderRadius: '50%' } }));
    const x = h('button', { class: 'btn', style: { position: 'absolute', right: '16px', top: '16px', cursor: 'pointer' } }, 'Cancel (Esc)'); o.append(msg, dot, x);
    const api = { el: o, msg, setTarget: (u, v) => { dot.style.display = 'block'; dot.style.left = u * 100 + '%'; dot.style.top = v * 100 + '%'; }, hideTarget: () => dot.style.display = 'none', cancelled: false, close: () => { document.removeEventListener('keydown', key); o.remove(); } };
    const key = (e) => { if (e.key === 'Escape') { api.cancelled = true; api.close(); } }; x.onclick = () => { api.cancelled = true; api.close(); }; document.addEventListener('keydown', key);
    document.body.appendChild(o); (o.requestFullscreen && o.requestFullscreen().catch(() => {})); return api; };
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const TARGETS = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9], [0.5, 0.5], [0.3, 0.7], [0.7, 0.3]];
  const runCalibration = async () => {
    if (!await FQ.confirm('Move this browser window to the projector / touch display. The overlay shows a target; touch its centre with your finger. Keep the area otherwise clear. Start?', 'Start', false)) return;
    const ov = targetOverlay('Calibration\nTouch the yellow target when it appears'); const pts = [];
    try { for (const [u, v] of TARGETS) { if (ov.cancelled) return; ov.setTarget(u, v); let raw = null;
        for (let tries = 0; tries < 2 && !raw; tries++) { try { raw = await FQ.api('/sensor/calibration/capture', { method: 'POST' }); } catch (e) { if (ov.cancelled) return; if (tries) throw e; } }
        pts.push({ target: [u, v], raw: [raw.x_mm, raw.y_mm] }); ov.hideTarget(); await sleep(700); }
      const r = await FQ.api('/sensor/calibration', { method: 'POST', body: { points: pts } }); ov.close(); FQ.toast(`Calibrated. Error ${(r.rmse * 100).toFixed(2)}% of screen.${r.warning ? ' ' + r.warning : ''}`, r.warning ? '' : 'ok'); FQ.route();
    } catch (e) { ov.close(); FQ.fail(e); }
  };
  const runValidation = async () => {
    if (!await FQ.confirm('Accuracy test: 15 random targets appear on the display. Touch each one. Start?', 'Start', false)) return;
    const ov = targetOverlay('Accuracy test\nTouch each target as it appears'); const trials = []; let pending = null;
    const ws2 = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/input`);
    ws2.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === 'touch' && pending && m.source === 'lidar' && !pending.hit) pending.hit = [m.u, m.v], pending.t1 = performance.now(), pending.done(); else if (m.type === 'touch' && pending && !pending.hit && m.source === 'simulated') pending.hit = [m.u, m.v], pending.t1 = performance.now(), pending.done(); };
    await new Promise(r => { ws2.onopen = r; setTimeout(r, 1500); });
    try { for (let i = 0; i < 15; i++) { if (ov.cancelled) return; const u = 0.1 + Math.random() * 0.8, v = 0.1 + Math.random() * 0.8; ov.setTarget(u, v);
        const tr = { target: [u, v], hit: null, latency_ms: null }; pending = { hit: null, t0: performance.now() }; await new Promise(res => { pending.done = res; setTimeout(res, 8000); });
        if (pending.hit) { tr.hit = pending.hit; tr.latency_ms = Math.round(pending.t1 - pending.t0); } trials.push(tr); pending = null; ov.hideTarget(); await sleep(500); }
      ov.close(); const r = await FQ.api('/sensor/validation', { method: 'POST', body: { trials } });
      FQ.modal({ title: 'Accuracy test result', width: 560, body: [h('p', {}, r.passed ? FQ.badge('PASSED', 'ok') : FQ.badge('FAILED', 'bad')), h('dl', { class: 'kv' },
        h('dt', {}, 'Detected'), h('dd', {}, `${r.detected}/${r.trials} (need ≥ ${r.limits.detection_rate * 100}%)`), h('dt', {}, 'Mean error'), h('dd', {}, r.mean_error == null ? '—' : (r.mean_error * 100).toFixed(2) + '% (limit ' + r.limits.mean_error * 100 + '%)'),
        h('dt', {}, '95th percentile'), h('dd', {}, r.p95_error == null ? '—' : (r.p95_error * 100).toFixed(2) + '% (limit ' + r.limits.p95_error * 100 + '%)'), h('dt', {}, 'Mean latency'), h('dd', {}, r.mean_latency_ms == null ? '—' : Math.round(r.mean_latency_ms) + ' ms (limit ' + r.limits.mean_latency_ms + ')')),
        h('p', { class: r.validated_hardware ? 'ok-text' : 'warn-text' }, r.validated_hardware ? 'Real hardware validated.' : r.passed ? 'Passed, but the source is not real hardware (simulator/replay), so the installation is NOT marked validated.' : 'Not validated. Re-calibrate, adjust thresholds, or check mounting.')] }); FQ.route();
    } catch (e) { ov.close(); FQ.fail(e); } finally { ws2.close(); }
  };
  const v = cfg.validation || {};
  const calPanel = h('div', { class: 'panel' }, h('h2', {}, 'Calibration & validation'), calInfo,
    h('p', { class: 'muted' }, 'Calibration maps the sensor plane to the projected screen using 7 touched targets. The accuracy test then touches random targets and must meet the limits before the setup is called validated.'),
    v.at ? h('p', {}, 'Last accuracy test: ', v.passed ? FQ.badge('passed', 'ok') : FQ.badge('failed', 'bad'), ` ${FQ.fmtDate(v.at)} · source ${v.source_type} · mean error ${(v.mean_error * 100).toFixed(2)}%`) : h('p', { class: 'muted' }, 'No accuracy test recorded.'),
    admin ? h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: runCalibration }, 'Calibrate…'), h('button', { class: 'btn', onclick: runValidation }, 'Accuracy test…'),
      h('button', { class: 'btn', onclick: async () => { if (!await FQ.confirm('The screen and play area must be completely clear while the sensor learns the static background. Learn now?', 'Learn', false)) return; try { const r = await FQ.api('/sensor/background/learn', { method: 'POST' }); FQ.toast(`Background learned (${r.bins} angle bins)`, 'ok'); FQ.route(); } catch (e) { FQ.fail(e); } } }, cfg.has_background ? 'Re-learn background' : 'Learn background'),
      cfg.has_background ? h('button', { class: 'btn danger', onclick: async () => { await FQ.api('/sensor/background', { method: 'DELETE' }).catch(FQ.fail); FQ.route(); } }, 'Clear background') : null,
      cfg.calibration && cfg.calibration.homography ? h('button', { class: 'btn danger', onclick: async () => { if (await FQ.confirm('Remove calibration?', 'Remove')) { await FQ.api('/sensor/calibration', { method: 'DELETE' }).catch(FQ.fail); FQ.route(); } } }, 'Clear calibration') : null) : h('p', { class: 'muted' }, 'Administrators only.'));

  /* --- pose input key */
  const keyBox = h('div', { class: 'panel' }, h('h2', {}, 'Pose / camera input'), h('p', { class: 'muted' }, 'Poses cannot be derived from the LiDAR. An external camera service may post recognised pose labels to POST /api/input/pose with the header x-input-key. Pose schemes stay disabled until such a service is connected.'),
    admin ? [h('div', { class: 'row' }, h('code', {}, cfg.params.input_key ? cfg.params.input_key.slice(0, 6) + '…' : 'no key yet'), h('button', { class: 'btn small', onclick: async () => { const r = await FQ.api('/sensor/input-key/rotate', { method: 'POST' }).catch(FQ.fail); if (r) FQ.modal({ title: 'New input key', width: 520, body: [h('p', {}, 'Copy it now; it is only shown in full here.'), h('code', { style: { wordBreak: 'break-all' } }, r.input_key)] }); } }, 'Generate new key'))] : null);

  main.append(h('div', { class: 'head' }, h('h1', {}, 'Sensor & calibration')), statusBox, h('div', { class: 'panel' }, h('h2', {}, 'Live scan view'), canvas, h('p', { class: 'muted' }, 'Blue: scan points · yellow rings: touch candidates · green: calibrated screen outline.')), simPanel, calPanel, configPanel, keyBox);
};
})();
