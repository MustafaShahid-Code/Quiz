/* Live leaderboard (big screen). /game/leaderboard.html?game=<slug>&lang=en|ar&period=today|all&refresh=10 */
'use strict';
(() => {
const $ = (id) => document.getElementById(id);
const qs = new URLSearchParams(location.search);
const SLUG = qs.get('game') || '';
let lang = qs.get('lang') === 'ar' ? 'ar' : 'en';
const PERIOD = qs.get('period') === 'all' ? 'all' : 'today';
const REFRESH = Math.max(4, Math.min(120, Number(qs.get('refresh')) || 10));
const TZ = -new Date().getTimezoneOffset();
const T = {
  en: { top: 'Best scores', winners: 'Latest winners', win: 'WIN', today: 'today', rounds: 'rounds played', wins: 'winners', empty: 'Be the first!', off: 'The leaderboard is not switched on for this game.', pw: 'Password', unlock: 'Unlock', wrong: 'Wrong password', of: 'of' },
  ar: { top: 'أفضل النتائج', winners: 'آخر الفائزين', win: 'فوز', today: 'اليوم', rounds: 'جولة', wins: 'فائز', empty: 'كن الأول!', off: 'لوحة الصدارة غير مفعّلة لهذه اللعبة.', pw: 'كلمة المرور', unlock: 'فتح', wrong: 'كلمة المرور خاطئة', of: 'من' },
};
const tokKey = 'fq_gt_' + SLUG;
const getTok = () => { try { return sessionStorage.getItem(tokKey); } catch (e) { return null; } };
const setTok = (v) => { try { sessionStorage.setItem(tokKey, v); } catch (e) { /* ignore */ } };
let timer = null;

function applyTheme(t) {
  const r = document.documentElement.style, c = t.colors;
  const map = { '--bg-from': c.bg_from, '--bg-to': c.bg_to, '--bg-glow': c.bg_glow, '--text': c.text, '--text-muted': c.text_muted, '--title': c.title, '--accent-line': c.accent_line,
    '--btn-bg': c.button_bg, '--btn-text': c.button_text, '--btn-hover': c.button_hover, '--btn-sel': c.button_selected_border, '--card-bg': c.card_bg, '--correct': c.correct,
    '--incorrect': c.incorrect, '--burst-bg': c.burst_bg, '--burst-text': c.burst_text, '--btn-radius': t.shape.button_radius + 'px', '--card-radius': t.shape.card_radius + 'px', '--bg-overlay': t.effects.background_overlay };
  for (const k in map) r.setProperty(k, map[k]);
  let en = t.fonts.family_en, ar = t.fonts.family_ar;
  if (t.urls && t.urls.font) { $('theme-font').textContent = `@font-face{font-family:'ThemeFont';src:url('${t.urls.font}');font-display:swap}`; en = `'ThemeFont',${en}`; ar = `'ThemeFont',${ar}`; }
  r.setProperty('--font-en', en); r.setProperty('--font-ar', ar);
  $('bg').style.backgroundImage = t.urls && t.urls.background ? `url('${t.urls.background}')` : 'none';
  for (const [id, url] of [['logoLeft', t.urls && t.urls.logo_left], ['logoRight', t.urls && t.urls.logo_right]]) { const el = $(id); if (url) { el.src = url; el.hidden = false; } else el.hidden = true; }
}
function fit() { document.documentElement.style.setProperty('--s', Math.min(innerWidth / 1920, innerHeight / 1080)); }
addEventListener('resize', fit); fit();

const only = (id) => { for (const n of ['lb', 'lbLock', 'lbOff']) $(n).hidden = n !== id; };
async function http(path, headers = {}) {
  const r = await fetch(path, { headers }); let d = null; try { d = await r.json(); } catch (e) { /* none */ }
  if (!r.ok) { const e = new Error((d && d.detail) || r.statusText); e.status = r.status; throw e; } return d;
}
function setLang() { document.documentElement.lang = lang; document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr'; }
function row(i, r, kind) {
  const li = document.createElement('li'); li.style.animationDelay = (i * 0.05) + 's';
  const rank = Object.assign(document.createElement('span'), { className: 'rank', textContent: kind === 'win' ? '★' : String(i + 1) });
  const nm = Object.assign(document.createElement('span'), { className: 'nm', textContent: r.player_name });
  li.append(rank, nm);
  if (kind === 'top') { li.append(Object.assign(document.createElement('span'), { className: 'sub', textContent: `${r.correct_count}/${r.total_questions}` }), Object.assign(document.createElement('span'), { className: 'sc', textContent: String(r.score) })); if (r.outcome === 'win') li.classList.add('win'); }
  else { li.classList.add('win'); li.append(Object.assign(document.createElement('span'), { className: 'tag', textContent: T[lang].win }), Object.assign(document.createElement('span'), { className: 'sub', textContent: `${r.correct_count}/${r.total_questions}` })); }
  return li;
}
function fill(ol, rows, kind) {
  ol.replaceChildren();
  if (!rows.length) { ol.appendChild(Object.assign(document.createElement('li'), { className: 'empty', textContent: T[lang].empty })); return; }
  rows.forEach((r, i) => ol.appendChild(row(i, r, kind)));
}
async function refresh() {
  try {
    const tok = getTok(); const d = await http(`/api/game/leaderboard?game=${encodeURIComponent(SLUG)}&period=${PERIOD}&tz=${TZ}&limit=8`, tok ? { 'x-game-token': tok } : {});
    only('lb'); $('lbTitle').textContent = d['title_' + lang] || d.title_en; $('topHead').textContent = T[lang].top; $('winHead').textContent = T[lang].winners;
    $('winCol').hidden = !d.has_outcome; $('lbCols').classList.toggle('single', !d.has_outcome);
    fill($('topList'), d.top, 'top'); fill($('winList'), d.winners, 'win');
    $('lbStats').innerHTML = ''; const b1 = document.createElement('b'); b1.textContent = d.stats.rounds; const b2 = document.createElement('b'); b2.textContent = d.stats.wins;
    $('lbStats').append(b1, ` ${T[lang].rounds}${PERIOD === 'today' ? ' · ' + T[lang].today : ''}`); if (d.has_outcome) $('lbStats').append(' · ', b2, ` ${T[lang].wins}`);
  } catch (e) {
    if (e.status === 401) return showLock();
    only('lbOff'); $('offMsg').textContent = e.status === 404 ? T[lang].off : e.message;
  }
}
function showLock() {
  only('lbLock'); const inp = $('lockInput'), err = $('lockErr'); $('lockBtn').textContent = T[lang].unlock; inp.placeholder = T[lang].pw; inp.focus();
  const go = async () => {
    try { const r = await fetch(`/api/game/games/${encodeURIComponent(SLUG)}/unlock`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password: inp.value }) });
      const d = await r.json(); if (!r.ok) throw Object.assign(new Error(d.detail), { status: r.status }); setTok(d.token); refresh(); }
    catch (e) { err.textContent = e.status === 403 ? T[lang].wrong : e.message; inp.value = ''; }
  };
  $('lockBtn').onclick = go; inp.onkeydown = (e) => { if (e.key === 'Enter') go(); };
}
async function boot() {
  setLang();
  try {
    const cfg = await http(`/api/game/config?game=${encodeURIComponent(SLUG)}`, getTok() ? {} : {});
    applyTheme(cfg.theme); const s = cfg.settings; document.title = (s['title_' + lang] || s.title_en || 'Leaderboard') + ' · ' + (lang === 'ar' ? 'لوحة الصدارة' : 'Leaderboard');
    $('title').textContent = s['title_' + lang] || s.title_en || '';
    if (!s.enabled_languages.includes(lang)) lang = s.default_language; setLang();
  } catch (e) { only('lbOff'); $('offMsg').textContent = e.status === 404 ? 'Game not found' : e.message; return; }
  await refresh(); timer = setInterval(refresh, REFRESH * 1000);
}
boot();
})();
