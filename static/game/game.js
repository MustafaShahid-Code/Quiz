/* Football Challenge - player screen. Vanilla JS, no build step.
   Flow: Branding/sponsors -> Welcome -> Questions (select -> confirm -> judged) -> Result -> back to Branding.
   Inputs: mouse, touch, keyboard, LiDAR/simulator touch events (WebSocket) and pose events. */
'use strict';
(() => {
const $ = (id) => document.getElementById(id);
const qs = new URLSearchParams(location.search);
const PREVIEW = qs.get('preview');            // 'question' | 'scheme' | 'theme' (admin only)
const PREVIEW_ID = qs.get('id');

const T = {
  en: { start: 'Start Game', play_again: 'Play Again', home: 'Home', next: 'Next', finish: 'See Results', score: 'Score',
        final_score: 'Final Score', correct_line: (c, a, t) => `${c} of ${t} correct`,
        perfect: 'PERFECT SCORE!', high: 'Great job, champion!', normal: 'Good effort! Play again?',
        sensor_lidar: 'LiDAR touch active', sensor_lidar_unval: 'LiDAR (not validated)', sensor_sim: 'Simulator input',
        sensor_off: 'Sensor offline – mouse / touch active', loading: 'Loading…', no_q: 'No questions are available in this language yet.',
        error: 'Something went wrong. Touch to try again.', preview: 'PREVIEW' },
  ar: { start: 'ابدأ اللعبة', play_again: 'العب مرة أخرى', home: 'الرئيسية', next: 'التالي', finish: 'عرض النتيجة', score: 'النقاط',
        final_score: 'النتيجة النهائية', correct_line: (c, a, t) => `الإجابات الصحيحة: ${c} من ${t}`,
        perfect: 'نتيجة كاملة!', high: 'أحسنت يا بطل!', normal: 'مجهود جيد! العب مرة أخرى؟',
        sensor_lidar: 'لمس LiDAR فعّال', sensor_lidar_unval: 'LiDAR (غير معتمد)', sensor_sim: 'إدخال محاكاة',
        sensor_off: 'الحساس غير متصل – اللمس/الفأرة متاح', loading: 'جارٍ التحميل…', no_q: 'لا توجد أسئلة بهذه اللغة حالياً.',
        error: 'حدث خطأ. المس الشاشة للمحاولة مرة أخرى.', preview: 'معاينة' },
};
const LANG_NAMES = { en: 'English', ar: 'العربية' };

const S = {
  cfg: null, settings: {}, theme: null, lang: 'en', screen: 'branding', sensor: { state: 'disabled' },
  session: null, q: null, index: 0, total: 0, score: 0, results: [],
  phase: 'idle', selected: null, selectedAt: 0, selectedSrc: 'mouse', shownAt: 0, resp: null,
  confirmTimer: null, autoTimer: null, idleTimer: null, slideTimer: null, lastHandled: 0, wrongIds: new Set(), audio: null,
};

/* ------------------------------------------------------------------ API (real or local preview) */
async function http(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const r = await fetch(path, { ...opts, headers });
  let body = null; try { body = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) { const err = new Error((body && (body.detail && body.detail.message || body.detail)) || r.statusText); err.status = r.status; throw err; }
  return body;
}
function adminHeaders() { const t = localStorage.getItem('fq_token'); return t ? { Authorization: 'Bearer ' + t } : {}; }

const FOOTBALL_SVG = 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><circle cx="200" cy="200" r="180" fill="#fff" stroke="#1b1b1b" stroke-width="8"/><polygon points="200,120 262,165 238,238 162,238 138,165" fill="#1b1b1b"/></svg>');
let previewState = null;
const api = {
  async start(lang) {
    if (PREVIEW) { previewState = { done: false, score: 0, q: await previewQuestion(lang) }; return { session_id: 'preview', total: 1, lang }; }
    return http('/api/game/sessions', { method: 'POST', body: JSON.stringify({ lang }) });
  },
  async question(sid) {
    if (PREVIEW) return previewState.done ? { finished: true, score: previewState.score, total: 1 }
      : { finished: false, index: 0, total: 1, score: previewState.score, question: stripCorrect(previewState.q), retries_left: S.settings.retries_per_question };
    return http(`/api/game/sessions/${sid}/question`);
  },
  async answer(sid, body) {
    if (PREVIEW) {
      const q = previewState.q, o = q.options.find(x => x.id === body.option_id), c = q.options.find(x => x.is_correct);
      const ok = !!(o && o.is_correct); previewState.done = true; if (ok) previewState.score = 10;
      return { correct: ok, final: true, can_retry: false, score: previewState.score, points: ok ? 10 : 0, is_last: true, correct_option_id: c.id,
               explanation: q.explanation, reveal_url: q.reveal_url || q.image_url, selected_option_id: body.option_id };
    }
    return http(`/api/game/sessions/${sid}/answer`, { method: 'POST', body: JSON.stringify(body) });
  },
  async timeout(sid, body) {
    if (PREVIEW) { const c = previewState.q.options.find(x => x.is_correct); previewState.done = true;
      return { correct: false, final: true, timed_out: true, score: previewState.score, points: 0, is_last: true, correct_option_id: c.id, explanation: previewState.q.explanation, selected_option_id: null }; }
    return http(`/api/game/sessions/${sid}/timeout`, { method: 'POST', body: JSON.stringify(body) });
  },
  async result(sid) {
    if (PREVIEW) return { score: previewState.score, max_score: 10, correct: previewState.score ? 1 : 0, attempted: 1, total: 1, percent: previewState.score ? 100 : 0, tier: previewState.score ? 'perfect' : 'normal' };
    return http(`/api/game/sessions/${sid}/result`);
  },
};
function stripCorrect(q) { return { ...q, options: q.options.map(o => ({ id: o.id, label: o.label })) }; }
async function previewQuestion(lang) {
  if (PREVIEW === 'question') return (await http(`/api/admin/questions/${PREVIEW_ID}/preview?lang=${lang}`, { headers: adminHeaders() })).question;
  if (PREVIEW === 'scheme') return (await http(`/api/admin/schemes/${PREVIEW_ID}/preview?lang=${lang}`, { headers: adminHeaders() })).question;
  const en = lang === 'en';
  return { question_id: 0, text: en ? 'What is shown in this picture?' : 'ماذا تظهر هذه الصورة؟', image_url: FOOTBALL_SVG, reveal_url: FOOTBALL_SVG, explanation: '', scheme: null,
           options: (en ? ['Basketball', 'Football', 'Tennis Ball', 'Volleyball'] : ['كرة سلة', 'كرة قدم', 'كرة تنس', 'كرة طائرة']).map((l, i) => ({ id: i + 1, label: l, is_correct: i === 1 })) };
}

/* ------------------------------------------------------------------ theme */
function applyTheme(t) {
  S.theme = t; const r = document.documentElement.style, c = t.colors;
  const map = { '--bg-from': c.bg_from, '--bg-to': c.bg_to, '--bg-glow': c.bg_glow, '--text': c.text, '--text-muted': c.text_muted, '--title': c.title,
    '--accent-line': c.accent_line, '--btn-bg': c.button_bg, '--btn-text': c.button_text, '--btn-hover': c.button_hover, '--btn-sel': c.button_selected_border,
    '--card-bg': c.card_bg, '--correct': c.correct, '--incorrect': c.incorrect, '--burst-bg': c.burst_bg, '--burst-text': c.burst_text,
    '--burst-stroke': c.burst_stroke, '--branding-bg': c.branding_bg, '--btn-radius': t.shape.button_radius + 'px', '--card-radius': t.shape.card_radius + 'px',
    '--bg-overlay': t.effects.background_overlay };
  for (const k in map) r.setProperty(k, map[k]);
  let en = t.fonts.family_en, ar = t.fonts.family_ar;
  if (t.urls && t.urls.font) {
    $('theme-font').textContent = `@font-face{font-family:'ThemeFont';src:url('${t.urls.font}');font-display:swap}`;
    en = `'ThemeFont',${en}`; ar = `'ThemeFont',${ar}`;
  } else $('theme-font').textContent = '';
  r.setProperty('--font-en', en); r.setProperty('--font-ar', ar);
  $('viewport').dataset.btn = t.shape.button_style;
  $('bg').style.backgroundImage = t.urls && t.urls.background ? `url('${t.urls.background}')` : 'none';
  document.body.classList.toggle('no-swoosh', !t.effects.swoosh);
  document.body.classList.toggle('no-lights', !t.effects.stadium_lights);
  for (const [id, url] of [['logoLeft', t.urls && t.urls.logo_left], ['logoRight', t.urls && t.urls.logo_right]]) {
    const el = $(id); if (url) { el.src = url; el.hidden = false; } else { el.removeAttribute('src'); el.hidden = true; }
  }
}
function fit() { const s = Math.min(innerWidth / 1920, innerHeight / 1080); document.documentElement.style.setProperty('--s', s); }
addEventListener('resize', fit);

function setLang(lang) {
  S.lang = lang; document.documentElement.lang = lang; document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  const s = S.settings;
  $('title').textContent = s['title_' + lang] || s.title_en;
  $('tagline').textContent = s['tagline_' + lang] || '';
  $('instructions').textContent = s['instructions_' + lang] || '';
  $('startBtn').textContent = T[lang].start; $('againBtn').textContent = T[lang].play_again; $('homeBtn').textContent = T[lang].home;
  renderChip(); renderLangButtons();
}
const t = (k, ...a) => { const v = T[S.lang][k]; return typeof v === 'function' ? v(...a) : v; };
const pick = (arr) => arr && arr.length ? arr[Math.floor(Math.random() * arr.length)] : '';

/* ------------------------------------------------------------------ screens */
function show(name) {
  S.screen = name;
  for (const n of ['welcome', 'question', 'result']) $('screen-' + n).hidden = n !== name;
  $('screen-branding').hidden = name !== 'branding';
  $('brandbar').hidden = name === 'branding';
  $('miniDot').hidden = name === 'branding' || name === 'welcome';
  if (name !== 'branding') stopSlides();
  clearTimers(); resetIdle();
}
function clearTimers() { clearTimeout(S.confirmTimer); clearTimeout(S.autoTimer); stopAnswerTimer(); }

// ---- answer countdown: the player must pick an answer before it reaches zero ----
function stopAnswerTimer(hide = true) { clearInterval(S.tick); S.tick = null; if (hide) $('timer').hidden = true; }
function startAnswerTimer() {
  stopAnswerTimer();
  if (!S.settings.answer_timer_enabled) return;
  const total = Math.max(2000, S.settings.answer_time_limit_ms || 5000), t0 = performance.now(), el = $('timer'), ring = el.querySelector('.tring'), num = $('timerNum');
  el.hidden = false; el.classList.remove('warn', 'frozen');
  const draw = () => {
    if (S.phase !== 'answering') return stopAnswerTimer();       // selecting an answer hands over to the confirm bar
    const left = Math.max(0, total - (performance.now() - t0));
    num.textContent = Math.ceil(left / 1000); ring.style.strokeDashoffset = String(276.46 * (1 - left / total));
    el.classList.toggle('warn', left <= 2000);
    if (left <= 0) { stopAnswerTimer(); timedOut(); }
  };
  draw(); S.tick = setInterval(draw, 100);
}
async function timedOut() {
  if (S.phase !== 'answering') return;
  S.phase = 'submitting'; $('viewport').classList.add('locked'); S.selected = null;
  try { const r = await api.timeout(S.session.session_id, { question_id: S.q.question_id }); S.resp = r; S.score = r.score; showFeedback(r); }
  catch (e) {
    if (e.status === 409) { S.phase = 'idle'; return loadQuestion().catch(() => goWelcome()); }
    toast(t('error')); S.phase = 'answering'; $('viewport').classList.remove('locked'); startAnswerTimer();
  }
}

function goBranding() {
  S.session = null; S.phase = 'idle'; S.lang = S.settings.default_language;
  const slides = (S.cfg && S.cfg.slides) || [];
  if (!slides.length || PREVIEW === 'question' || PREVIEW === 'scheme') return goWelcome();
  show('branding'); startSlides(slides);
  setLang(S.settings.default_language);
}
function goWelcome() {
  show('welcome'); setLang(S.lang);
  const n = S.cfg.available_questions[S.lang] || 0;
  $('welcomeNote').textContent = n ? '' : t('no_q');
  $('startBtn').hidden = !n; renderChip();
}

/* ---- branding slides */
function startSlides(slides) {
  const wrap = $('slides'), dots = $('slideDots'); wrap.innerHTML = ''; dots.innerHTML = '';
  slides.forEach((s) => {
    const d = document.createElement('div'); d.className = 'slide'; d.style.background = s.bg_color;
    if (s.image_url) { d.classList.add('hasimg'); const im = document.createElement('img'); im.src = s.image_url; im.alt = ''; im.style.objectFit = s.fit; d.appendChild(im); }
    const tx = document.createElement('div'); tx.className = 'stext';
    for (const [h, p] of [[s.title_en, s.body_en], [s.title_ar, s.body_ar]]) {
      if (s.image_url && !p) continue;   // on image slides the title is only an admin label; captions (body) are shown
      if (h) { const e = document.createElement('h2'); e.textContent = h; tx.appendChild(e); }
      if (p) { const e = document.createElement('p'); e.textContent = p; tx.appendChild(e); }
    }
    if (tx.childNodes.length) d.appendChild(tx);
    wrap.appendChild(d); dots.appendChild(document.createElement('i'));
  });
  $('hintA').textContent = S.settings.branding_hint_en || ''; $('hintB').textContent = S.settings.branding_hint_ar || '';
  dots.hidden = slides.length < 2;
  let i = 0;
  const step = () => {
    [...wrap.children].forEach((e, k) => e.classList.toggle('on', k === i));
    [...dots.children].forEach((e, k) => e.classList.toggle('on', k === i));
    const ms = slides[i].duration_ms || S.settings.branding_default_duration_ms || 6000;
    i = (i + 1) % slides.length; S.slideTimer = setTimeout(step, ms);
  };
  step();
}
function stopSlides() { clearTimeout(S.slideTimer); S.slideTimer = null; }

/* ---- language buttons & sensor chip */
function renderLangButtons() {
  const box = $('langs'); box.innerHTML = '';
  const langs = S.settings.enabled_languages || ['en', 'ar'];
  if (langs.length < 2) return;
  for (const lg of langs) {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'lang' + (lg === S.lang ? ' on' : '');
    b.dataset.action = 'lang'; b.dataset.lang = lg; b.textContent = LANG_NAMES[lg];
    if (!(S.cfg.available_questions[lg] > 0)) b.disabled = true;
    box.appendChild(b);
  }
}
function sensorView() {
  const s = S.sensor || {};
  if (!['ok', 'stale'].includes(s.state) || s.state === 'stale') return ['off', t('sensor_off')];
  if (s.source === 'simulated') return ['sim', t('sensor_sim')];
  return s.validated ? ['ok', t('sensor_lidar')] : ['warn', t('sensor_lidar_unval')];
}
function renderChip() {
  const [cls, text] = sensorView(), chip = $('chip');
  chip.className = 'chip ' + cls; chip.querySelector('span').textContent = text;
  const d = $('miniDot'); d.className = 'dot ' + cls; d.title = text;
}

/* ------------------------------------------------------------------ game flow */
async function startGame(lang) {
  try {
    S.lang = lang; setLang(lang); S.results = []; S.score = 0;
    S.session = await api.start(lang); show('question'); await loadQuestion();
  } catch (e) { toast(e.status === 409 ? t('no_q') : t('error')); goWelcome(); }
}
async function loadQuestion() {
  clearTimers(); S.phase = 'loading';
  const r = await api.question(S.session.session_id);
  if (r.finished) return showResult();
  S.q = r.question; S.index = r.index; S.total = r.total; S.score = r.score; S.wrongIds = new Set(); S.selected = null; S.resp = null;
  renderQuestion(); S.phase = 'answering'; S.shownAt = performance.now(); startAnswerTimer();
}
function renderQuestion() {
  const q = S.q;
  $('reveal').hidden = true; $('explanation').hidden = true; $('nextBtn').hidden = true; $('autobar').hidden = true; $('confirmBar').hidden = true;
  $('card').hidden = !q.image_url; if (q.image_url) $('qimg').src = q.image_url;
  $('viewport').classList.toggle('noimg', !q.image_url);   // text-only question: bigger text, no picture card
  setQText(q.text);
  const box = $('options'); box.innerHTML = ''; box.className = ''; box.removeAttribute('style');
  const sch = q.scheme, cfg = sch && sch.config || {};
  if (sch && sch.type === 'touch_zones' && cfg.layout === 'custom') box.classList.add('custom');
  else if (sch && sch.type === 'touch_zones' && ['row', 'column'].includes(cfg.layout)) box.classList.add(cfg.layout);
  else if (sch && sch.type === 'pose_mapping') box.classList.add('pose');
  q.options.forEach((o, i) => {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'opt'; b.dataset.action = 'option'; b.dataset.id = o.id; b.textContent = o.label;
    b.style.animationDelay = (i * 70) + 'ms';
    if (box.classList.contains('custom')) {
      const z = (cfg.zones || []).find(z => z.option_index === i);
      if (z) Object.assign(b.style, { position: 'absolute', left: (z.x * 1920 - 340) + 'px', top: (z.y * 1080 - 749) + 'px', width: z.w * 1920 + 'px', height: z.h * 1080 + 'px' });
    } else if (sch && sch.type === 'pose_mapping') {
      const m = (cfg.mappings || []).find(m => m.option_index === i);
      if (m) { const h = document.createElement('span'); h.className = 'hint'; h.textContent = m.pose.replace(/_/g, ' '); b.appendChild(h); }
    }
    box.appendChild(b);
  });
  $('score').textContent = `${t('score')}: ${S.score}`;
  const dots = $('dots'); dots.innerHTML = '';
  for (let i = 0; i < S.total; i++) { const d = document.createElement('i'); const r = S.results[i]; d.className = i === S.index ? 'now' : r === true ? 'done' : r === false ? 'miss' : ''; dots.appendChild(d); }
  $('viewport').classList.remove('locked');
}
function setQText(text, confirm = false) { const e = $('qtext'); e.textContent = text; e.classList.toggle('confirm', confirm); }

function optEl(id) { return document.querySelector(`#options .opt[data-id="${id}"]`); }

function selectOption(id, source) {
  if (!['answering', 'confirming'].includes(S.phase) || S.wrongIds.has(id)) return;
  const now = performance.now();
  if (S.selected === id) {                       // touching the highlighted answer again locks it in
    if (S.settings.confirm_retouch_locks && now - S.selectedAt > 800) submit(); return;
  }
  document.querySelectorAll('#options .opt.selected').forEach(e => e.classList.remove('selected'));
  S.selected = id; S.selectedAt = now; S.selectedSrc = source; optEl(id).classList.add('selected'); tone('tick');
  if (!S.settings.confirm_enabled) return submit();
  S.phase = 'confirming'; clearTimeout(S.confirmTimer);
  setQText(S.settings['confirm_text_' + S.lang] || '', true);
  const bar = $('confirmBar'), fill = bar.firstElementChild, ms = S.settings.confirm_delay_ms;
  bar.hidden = false; fill.style.animation = 'none'; void fill.offsetWidth; fill.style.animation = `shrink ${ms}ms linear forwards`;
  S.confirmTimer = setTimeout(submit, ms);
}

async function submit() {
  if (S.phase !== 'confirming' && S.phase !== 'answering') return; if (S.selected == null) return;
  clearTimeout(S.confirmTimer); S.phase = 'submitting'; $('confirmBar').hidden = true; $('viewport').classList.add('locked');
  try {
    const resp = await api.answer(S.session.session_id, { question_id: S.q.question_id, option_id: S.selected, input_source: S.selectedSrc,
      response_ms: Math.round(performance.now() - S.shownAt) });
    S.resp = resp; S.score = resp.score; showFeedback(resp);
  } catch (e) {
    if (e.status === 409) { S.phase = 'idle'; return loadQuestion().catch(() => goWelcome()); }  // stale or duplicate: resync
    toast(t('error')); S.phase = 'answering'; $('viewport').classList.remove('locked');
  }
}

function showFeedback(r) {
  stopAnswerTimer();
  const sel = optEl(r.selected_option_id);
  if (!r.final) {                                 // wrong, but a retry is allowed
    S.wrongIds.add(r.selected_option_id); sel.classList.remove('selected'); sel.classList.add('wrong', 'dim'); S.selected = null; tone('wrong');
    setQText(S.settings['retry_message_' + S.lang] || ''); S.phase = 'answering'; $('viewport').classList.remove('locked'); startAnswerTimer(); return;
  }
  S.phase = 'feedback'; S.results[S.index] = r.correct;
  document.querySelectorAll('#options .opt').forEach(e => e.classList.remove('selected'));
  const reveal = $('reveal'); reveal.className = r.correct ? 'correct' : 'wrong'; reveal.hidden = false;
  $('card').hidden = true; $('qtext').textContent = ''; $('qtext').classList.remove('confirm');
  const url = r.reveal_url || S.q.image_url; $('sticker').hidden = !url; if (url) $('revealImg').src = url;
  $('burstTitle').textContent = r.correct ? (S.settings['correct_title_' + S.lang] || '') : '';
  $('burstMsg').textContent = r.timed_out ? (S.settings['timeout_message_' + S.lang] || '') : r.correct ? pick(S.settings['correct_messages_' + S.lang]) : pick(S.settings['incorrect_messages_' + S.lang]);
  drawBurst(r.correct ? 18 : 12);
  const opts = [...document.querySelectorAll('#options .opt')];
  if (r.correct) { optEl(r.selected_option_id).classList.add('correct', 'solo'); opts.forEach(e => { if (e.dataset.id != r.selected_option_id) e.classList.add('gone'); }); celebrate(false); tone('correct'); }
  else { if (sel) sel.classList.add('wrong'); const c = optEl(r.correct_option_id); if (c) c.classList.add('correct'); opts.forEach(e => { if (!e.classList.contains('wrong') && !e.classList.contains('correct')) e.classList.add('dim'); }); tone('wrong'); }
  if (r.explanation) { const e = $('explanation'); e.textContent = r.explanation; e.hidden = false; }
  $('score').textContent = `${t('score')}: ${r.score}`;
  const dots = $('dots').children; if (dots[S.index]) dots[S.index].className = r.correct ? 'done' : 'miss';
  const nb = $('nextBtn'); nb.textContent = r.is_last ? t('finish') : t('next'); nb.hidden = false; $('dots').hidden = true;
  if (S.settings.auto_advance) {
    const ms = S.settings.auto_advance_delay_ms, bar = $('autobar'), fill = bar.firstElementChild;
    bar.hidden = false; fill.style.animation = 'none'; void fill.offsetWidth; fill.style.animation = `shrink ${ms}ms linear forwards`;
    S.autoTimer = setTimeout(next, ms);
  }
}
function next() {
  if (S.phase !== 'feedback') return; clearTimers(); $('dots').hidden = false;
  S.phase = 'loading'; loadQuestion().catch(() => { toast(t('error')); goWelcome(); });
}
async function showResult() {
  const r = await api.result(S.session.session_id); show('result'); S.phase = 'result';
  $('trophy').innerHTML = r.tier === 'normal' ? BALL : TROPHY;
  $('resTitle').textContent = t(r.tier); $('resLine').textContent = t('correct_line', r.correct, r.attempted, r.total);
  countUp($('resScore'), r.score, r.max_score); tone(r.tier === 'normal' ? 'wrong' : 'fanfare');
  if (r.tier !== 'normal') celebrate(r.tier === 'perfect');
}
function countUp(el, to, max) {
  const t0 = performance.now(), dur = 1200; const fmt = (v) => `${v} / ${max}`;
  const tick = (now) => { const p = Math.min(1, (now - t0) / dur); el.textContent = fmt(Math.round(to * (1 - Math.pow(1 - p, 3)))); if (p < 1) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}
const BALL = `<svg viewBox="0 0 400 400"><circle cx="200" cy="200" r="180" fill="#fff" stroke="#1b1b1b" stroke-width="8"/><polygon points="200,120 262,165 238,238 162,238 138,165" fill="#1b1b1b"/><g stroke="#1b1b1b" stroke-width="8" stroke-linecap="round"><line x1="200" y1="120" x2="200" y2="40"/><line x1="262" y1="165" x2="330" y2="130"/><line x1="238" y1="238" x2="290" y2="310"/><line x1="162" y1="238" x2="110" y2="310"/><line x1="138" y1="165" x2="70" y2="130"/></g></svg>`;
const TROPHY = `<svg viewBox="0 0 400 400"><path d="M120 60h160v90c0 55-35 95-80 95s-80-40-80-95z" fill="#f5b800" stroke="#a87800" stroke-width="6"/><path d="M120 80H70c0 60 25 90 62 98M280 80h50c0 60-25 90-62 98" fill="none" stroke="#f5b800" stroke-width="16" stroke-linecap="round"/><rect x="180" y="245" width="40" height="55" fill="#e0a500"/><rect x="130" y="300" width="140" height="28" rx="6" fill="#a87800"/><rect x="110" y="328" width="180" height="34" rx="8" fill="#6b4a00"/><ellipse cx="170" cy="110" rx="14" ry="38" fill="#ffe27a" opacity=".7"/></svg>`;

function drawBurst(spikes) {
  const pts = [];
  for (let i = 0; i < spikes * 2; i++) {
    const a = (i / (spikes * 2)) * Math.PI * 2, outer = i % 2 === 0, k = outer ? 1 : 0.82 + Math.random() * 0.04;
    pts.push((50 + Math.cos(a) * 49 * k).toFixed(2) + ',' + (30 + Math.sin(a) * 29 * k).toFixed(2));
  }
  $('burstPoly').setAttribute('points', pts.join(' '));
}

/* ------------------------------------------------------------------ input handling */
function activate(el, source) {
  const now = performance.now(); if (now - S.lastHandled < 250) return; S.lastHandled = now; resetIdle();
  const a = el.dataset.action;
  if (a === 'enter') return goWelcome();
  if (a === 'lang') { if (el.disabled) return; S.lang = el.dataset.lang; setLang(S.lang); goWelcomeKeep(); return; }
  if (a === 'start') return startGame(S.lang);
  if (a === 'option') return selectOption(Number(el.dataset.id), source);
  if (a === 'next') return next();
  if (a === 'again') return startGame(S.lang);
  if (a === 'home') return goBranding();
}
function goWelcomeKeep() { const n = S.cfg.available_questions[S.lang] || 0; $('welcomeNote').textContent = n ? '' : t('no_q'); $('startBtn').hidden = !n; }

addEventListener('pointerdown', (e) => {
  const el = e.target.closest && e.target.closest('[data-action]'); resetIdle();
  if (new URLSearchParams(location.search).get('fullscreen') === '1' && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
  ensureAudio(); if (el) activate(el, e.pointerType === 'touch' ? 'touch' : 'mouse');
});
addEventListener('keydown', (e) => {
  resetIdle(); ensureAudio();
  if (e.key === 'f' || e.key === 'F') { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {}); return; }
  if (e.key === 'Escape') { if (!document.fullscreenElement) goBranding(); return; }
  if (S.screen === 'branding' && (e.key === 'Enter' || e.key === ' ')) return goWelcome();
  if (S.screen === 'welcome' && (e.key === 'Enter' || e.key === ' ') && !$('startBtn').hidden) return startGame(S.lang);
  if (S.screen === 'question') {
    if (e.key === 'Enter' || e.key === ' ') { if (S.phase === 'feedback') return next(); if (S.phase === 'confirming') return submit(); }
    const idx = '1234ABCDabcd'.indexOf(e.key); if (idx >= 0 && S.q) { const o = S.q.options[idx % 4]; if (o) selectOption(o.id, 'keyboard'); }
  }
  if (S.screen === 'result' && (e.key === 'Enter' || e.key === ' ')) startGame(S.lang);
});

function hitTest(u, v, source) {
  if (S.settings.show_touch_cursor) ripple(u * innerWidth, v * innerHeight);
  const el = document.elementFromPoint(Math.max(0, Math.min(innerWidth - 1, u * innerWidth)), Math.max(0, Math.min(innerHeight - 1, v * innerHeight)));
  const target = el && el.closest && el.closest('[data-action]'); resetIdle(); if (target) activate(target, source);
}
function ripple(x, y) { const r = document.createElement('div'); r.className = 'ripple'; r.style.left = x + 'px'; r.style.top = y + 'px'; $('touchLayer').appendChild(r); setTimeout(() => r.remove(), 750); }

let ws, wsDelay = 1000;
function connectWS() {
  try { ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/input'); } catch (e) { return; }
  ws.onopen = () => { wsDelay = 1000; };
  ws.onmessage = (m) => {
    let d; try { d = JSON.parse(m.data); } catch (e) { return; }
    if (d.type === 'status') { S.sensor = d; renderChip(); }
    else if (d.type === 'touch' && d.u != null && d.v != null) { S.sensor = { ...S.sensor, state: 'ok', source: d.source, validated: d.validated }; hitTest(d.u, d.v, d.source === 'simulated' ? 'simulated' : 'lidar'); }
    else if (d.type === 'pose') onPose(d);
  };
  ws.onclose = () => { S.sensor = { ...S.sensor, state: 'error' }; renderChip(); setTimeout(connectWS, wsDelay); wsDelay = Math.min(wsDelay * 2, 10000); };
  ws.onerror = () => ws.close();
}
function onPose(d) {
  const sch = S.q && S.q.scheme; if (!sch || sch.type !== 'pose_mapping' || S.screen !== 'question') return;
  if (d.confidence < (sch.config.min_confidence ?? 0.7)) return;
  const m = (sch.config.mappings || []).find(m => m.pose === d.label); if (!m) return;
  const o = S.q.options[m.option_index]; if (o) { resetIdle(); selectOption(o.id, 'pose'); }
}

/* ------------------------------------------------------------------ idle -> back to the sponsors screen */
function resetIdle() {
  clearTimeout(S.idleTimer); const s = S.settings.idle_reset_seconds;
  if (!s || PREVIEW || S.screen === 'branding') return;
  S.idleTimer = setTimeout(goBranding, s * 1000);
}

/* ------------------------------------------------------------------ effects */
const cv = $('confetti'), ctx = cv.getContext('2d'); let parts = [], raf = 0;
function sizeCanvas() { cv.width = innerWidth; cv.height = innerHeight; } addEventListener('resize', sizeCanvas); sizeCanvas();
function celebrate(big) {
  if (!S.theme || !S.theme.effects) return;
  if (S.theme.effects.stadium_lights) for (const l of document.querySelectorAll('.light')) { l.classList.remove('go'); void l.offsetWidth; l.classList.add('go'); }
  if (!S.theme.effects.confetti) return;
  const c = S.theme.colors, cols = [c.confetti_1, c.confetti_2, c.confetti_3, c.confetti_4], n = big ? 320 : 150;
  for (let i = 0; i < n; i++) parts.push({ x: Math.random() * cv.width, y: -20 - Math.random() * cv.height * .5, vx: (Math.random() - .5) * 4, vy: 3 + Math.random() * 5,
    w: 10 + Math.random() * 14, h: 6 + Math.random() * 12, r: Math.random() * 6, vr: (Math.random() - .5) * .3, col: cols[i % 4], shape: i % 3 });
  if (!raf) raf = requestAnimationFrame(loop);
}
function loop() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  parts = parts.filter(p => p.y < cv.height + 40);
  for (const p of parts) {
    p.x += p.vx + Math.sin(p.y / 40) * .8; p.y += p.vy; p.r += p.vr; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.col;
    if (p.shape === 0) ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); else if (p.shape === 1) { ctx.beginPath(); ctx.arc(0, 0, p.h / 2 + 2, 0, 7); ctx.fill(); }
    else { ctx.beginPath(); ctx.moveTo(0, -p.h); ctx.lineTo(p.w / 2, p.h / 2); ctx.lineTo(-p.w / 2, p.h / 2); ctx.fill(); }
    ctx.restore();
  }
  raf = parts.length ? requestAnimationFrame(loop) : 0; if (!raf) ctx.clearRect(0, 0, cv.width, cv.height);
}

/* ---- synthesised sounds (no audio files needed). Browsers need a first gesture, or Chrome's --autoplay-policy flag in kiosk mode. */
function ensureAudio() { if (!S.audio) { try { S.audio = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { /* none */ } } if (S.audio && S.audio.state === 'suspended') S.audio.resume(); }
function tone(kind) {
  if (!S.settings.sound_enabled || !S.audio) return;
  const seq = { tick: [[660, .05]], correct: [[523, .12], [659, .12], [784, .12], [1046, .3]], wrong: [[220, .25], [185, .35]],
    fanfare: [[523, .14], [523, .14], [523, .14], [659, .22], [784, .14], [659, .14], [784, .5]] }[kind]; let t0 = S.audio.currentTime;
  for (const [f, d] of seq) { const o = S.audio.createOscillator(), g = S.audio.createGain(); o.type = kind === 'wrong' ? 'sawtooth' : 'triangle'; o.frequency.value = f;
    g.gain.setValueAtTime(.0001, t0); g.gain.exponentialRampToValueAtTime(.18, t0 + .02); g.gain.exponentialRampToValueAtTime(.0001, t0 + d); o.connect(g).connect(S.audio.destination); o.start(t0); o.stop(t0 + d + .02); t0 += d; }
}
function toast(msg) { const e = $('toast'); e.textContent = msg; e.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => e.hidden = true, 3500); }

/* ------------------------------------------------------------------ boot */
async function boot() {
  fit();
  try {
    S.cfg = await http('/api/game/config'); S.settings = S.cfg.settings; S.sensor = S.cfg.sensor; S.lang = S.settings.default_language;
    let theme = S.cfg.theme;
    if (PREVIEW === 'theme') theme = await http(`/api/admin/themes/${PREVIEW_ID}/resolved`, { headers: adminHeaders() });
    applyTheme(theme);
    if (qs.get('lang') && S.settings.enabled_languages.includes(qs.get('lang'))) { S.settings.default_language = qs.get('lang'); S.lang = qs.get('lang'); }
    if (PREVIEW) { $('ribbon').hidden = false; $('ribbon').textContent = T.en.preview + ' · ' + T.ar.preview; S.cfg.available_questions = { en: 1, ar: 1 }; }
    if (!PREVIEW && qs.get('hidecursor') === '1') document.body.classList.add('hide-cursor');
    setLang(S.lang);
    if (PREVIEW === 'question' || PREVIEW === 'scheme') { await startGame(S.lang); } else goBranding();
  } catch (e) { toast('Cannot reach the server'); setTimeout(boot, 4000); return; }
  if (!PREVIEW) connectWS();
}
boot();
})();
