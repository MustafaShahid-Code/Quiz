/* Admin core: DOM helper, API client, modal/toast, asset picker, router. Every dynamic string goes through textContent. */
'use strict';
window.FQ = window.FQ || { pages: {}, state: { user: null, settings: null } };
(() => {
const FQ = window.FQ;

FQ.h = function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'hidden' || k === 'required' || k === 'multiple') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
};
const h = FQ.h;
FQ.$ = (s, r = document) => r.querySelector(s);
FQ.fmtDate = (s) => { if (!s) return '—'; const d = new Date(s); return isNaN(d) ? s : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }); };
FQ.can = (role) => ({ viewer: 1, editor: 2, admin: 3 }[FQ.state.user.role] >= { viewer: 1, editor: 2, admin: 3 }[role]);

/* ---------- API */
FQ.token = () => localStorage.getItem('fq_token');
FQ.api = async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (FQ.token()) headers.Authorization = 'Bearer ' + FQ.token();
  let body = opts.body;
  if (body && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
  const r = await fetch('/api/admin' + path, { method: opts.method || 'GET', headers, body });
  let data = null; try { data = await r.json(); } catch (e) { /* empty */ }
  if (r.status === 401 && !opts.noAuthRedirect) { FQ.logout(); throw new Error('Session expired'); }
  if (!r.ok) {
    const d = data && data.detail; let msg = r.statusText;
    if (typeof d === 'string') msg = d;
    else if (d && d.message) msg = d.message + (d.errors ? '\n• ' + d.errors.join('\n• ') : '');
    else if (Array.isArray(d)) msg = d.map(e => (e.loc ? e.loc.slice(1).join('.') + ': ' : '') + e.msg).join('\n');
    const err = new Error(msg); err.status = r.status; err.data = data; throw err;
  }
  return data;
};

/* ---------- toast / modal / confirm */
FQ.toast = (msg, kind = '') => { const t = h('div', { class: 'toast ' + kind }, msg); FQ.$('#toasts').appendChild(t); setTimeout(() => t.remove(), kind === 'bad' ? 7000 : 3500); };
FQ.fail = (e) => FQ.toast(e.message || String(e), 'bad');
FQ.modal = function modal({ title, body, footer, width, onClose }) {
  const overlay = h('div', { class: 'overlay' });
  const close = () => { overlay.remove(); onClose && onClose(); };
  const box = h('div', { class: 'modal', style: width ? { '--w': width + 'px' } : {} },
    h('header', {}, h('h2', {}, title), h('button', { class: 'x', type: 'button', onclick: close, 'aria-label': 'Close' }, '×')),
    h('div', { class: 'body' }, body), footer ? h('footer', {}, footer) : null);
  overlay.appendChild(box); overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });
  FQ.$('#modalRoot').appendChild(overlay); return { close, box };
};
FQ.confirm = (msg, okLabel = 'Delete', danger = true) => new Promise((res) => {
  const m = FQ.modal({ title: 'Please confirm', width: 440, body: h('p', {}, msg), onClose: () => res(false),
    footer: [h('button', { class: 'btn', onclick: () => { m.close(); } }, 'Cancel'),
             h('button', { class: 'btn ' + (danger ? 'danger' : 'primary'), onclick: () => { res(true); m.box.parentElement.remove(); } }, okLabel)] });
});

/* ---------- form helpers */
FQ.field = (label, input, hint) => h('label', { class: 'f' }, h('span', {}, label), input, hint ? h('small', {}, hint) : null);
FQ.select = (opts, value, props = {}) => h('select', props, opts.map(([v, l]) => h('option', { value: v, selected: String(v) === String(value) }, l)));
FQ.badge = (text, cls = '') => h('span', { class: 'badge ' + (cls || String(text).toLowerCase()) }, text);

/* ---------- small dropdown ("more actions") menu */
FQ.menu = function menu(label, items) {
  const wrap = h('div', { class: 'menu' }); const list = h('div', { class: 'menu-list', hidden: true });
  const close = () => { list.hidden = true; document.removeEventListener('click', away, true); };
  const away = (e) => { if (!wrap.contains(e.target)) close(); };
  items.filter(Boolean).forEach(it => list.appendChild(h(it.href ? 'a' : 'button', { type: 'button', class: it.danger ? 'danger' : '', href: it.href, target: it.href ? '_blank' : null, rel: it.href ? 'noopener' : null, onclick: () => { close(); it.onclick && it.onclick(); } }, it.label)));
  wrap.append(h('button', { class: 'btn small', type: 'button', 'aria-haspopup': 'true', onclick: () => { if (list.hidden) { list.hidden = false; document.addEventListener('click', away, true); } else close(); } }, label), list);
  return wrap;
};

/* ---------- asset picker (thumbnail + choose / upload / clear) */
FQ.assetPicker = function assetPicker({ value, kind = 'image', onChange, label = 'Image' }) {
  const state = { id: value || null, url: null };
  const pv = h('div', { class: 'pv' }); const name = h('div', { class: 'muted' });
  const render = () => {
    pv.replaceChildren(state.url ? (kind === 'font' ? h('span', {}, 'Aa') : h('img', { src: state.url, alt: '' })) : h('span', { class: 'muted' }, '—'));
    name.textContent = state.id ? `#${state.id}` : 'None selected';
  };
  const set = (a) => { state.id = a ? a.id : null; state.url = a ? a.url : null; render(); onChange && onChange(state.id); };
  const open = async () => {
    const list = await FQ.api('/assets?kind=' + kind).catch(FQ.fail); if (!list) return;
    const grid = h('div', { class: 'picker-grid' });
    const m = FQ.modal({ title: 'Choose a file', width: 760, body: [FQ.can('editor') ? h('div', { class: 'row', style: { marginBottom: '12px' } }, h('input', { type: 'file', accept: kind === 'font' ? '.woff2,.woff,.ttf,.otf' : 'image/*', id: 'pickUp' }),
        h('button', { class: 'btn primary small', type: 'button', onclick: async () => {
          const f = FQ.$('#pickUp').files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f);
          try { const a = await FQ.api('/assets', { method: 'POST', body: fd }); m.close(); set(a); FQ.toast('Uploaded', 'ok'); } catch (e) { FQ.fail(e); } } }, 'Upload & use')) : null, grid] });
    list.forEach(a => grid.appendChild(h('div', { class: 'it', title: a.original_name || '', onclick: () => { m.close(); set(a); } },
      kind === 'font' ? h('b', {}, a.original_name || 'font') : h('img', { src: a.url, alt: '' }))));
    if (!list.length) grid.appendChild(h('p', { class: 'muted' }, 'Nothing uploaded yet.'));
  };
  if (state.id) FQ.api('/assets?kind=' + kind).then(l => { const a = l.find(x => x.id === state.id); if (a) { state.url = a.url; render(); } }).catch(() => {});
  render();
  const el = h('div', { class: 'pick' }, pv, h('div', {}, h('div', { class: 'row' },
    h('button', { class: 'btn small', type: 'button', onclick: open }, 'Choose / upload…'),
    h('button', { class: 'btn small', type: 'button', onclick: () => set(null) }, 'Clear')), name));
  el.getValue = () => state.id; return el;
};

/* ---------- router & session */
const ICON = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  questions: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8"/><circle cx="12" cy="17" r=".6"/>',
  characters: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
  assets: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-8 8"/>',
  schemes: '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/>',
  slides: '<rect x="2" y="5" width="20" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>',
  themes: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.8 1.8-1.7 0-1.4-1.2-1.5-1.2-2.7 0-1 .8-1.6 1.8-1.6H16a5 5 0 0 0 5-5c0-3.9-4-7-9-7Z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7" r="1"/><circle cx="15.5" cy="7.5" r="1"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
  sensor: '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4M19 5a10 10 0 0 1 0 14M5 19A10 10 0 0 1 5 5"/>',
  results: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2.2.6 3.5 2.4 3.5 5"/>',
};
FQ.icon = (name, size = 18) => { const w = h('span', { class: 'ico' }); w.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name] || ''}</svg>`; return w; };
FQ.nav = [
  ['dashboard', 'Dashboard', 'viewer', null], ['questions', 'Questions', 'viewer', 'Content'], ['characters', 'Characters', 'viewer', 'Content'], ['assets', 'Media library', 'viewer', 'Content'],
  ['schemes', 'Interaction schemes', 'viewer', 'Content'], ['slides', 'Branding slides', 'viewer', 'Look & feel'], ['themes', 'Themes & colours', 'viewer', 'Look & feel'],
  ['settings', 'Game settings', 'viewer', 'System'], ['sensor', 'Sensor & calibration', 'viewer', 'System'], ['results', 'Results', 'viewer', 'System'], ['users', 'Users', 'admin', 'System'],
];
FQ.go = (page) => { location.hash = '#/' + page; };
FQ.route = async function route() {
  if (!FQ.state.user) return;
  const page = (location.hash.replace(/^#\//, '') || 'dashboard').split('?')[0];
  const nav = FQ.$('#nav'); const items = []; let grp = undefined;
  FQ.nav.filter(n => FQ.can(n[2])).forEach(([id, label, , g]) => { if (g !== grp) { grp = g; if (g) items.push(h('div', { class: 'nav-group' }, g)); }
    items.push(h('a', { class: id === page ? 'on' : '', tabindex: 0, role: 'link', onclick: () => FQ.go(id), onkeydown: (e) => { if (e.key === 'Enter') FQ.go(id); } }, FQ.icon(id), h('span', {}, label))); });
  nav.replaceChildren(...items);
  const main = FQ.$('#main'); main.replaceChildren(h('p', { class: 'muted' }, 'Loading…'));
  const fn = FQ.pages[page] || FQ.pages.dashboard;
  try { main.replaceChildren(); await fn(main); } catch (e) { FQ.fail(e); main.replaceChildren(h('div', { class: 'error' }, e.message)); }
};
addEventListener('hashchange', FQ.route);
FQ.logout = () => { localStorage.removeItem('fq_token'); FQ.state.user = null; FQ.$('#app').hidden = true; FQ.$('#login').hidden = false; };
FQ.applyBranding = (b) => {
  document.documentElement.style.setProperty('--primary', b.primary_color || '#2b44ff');
  const name = b.product_name || 'Admin'; document.title = name + (b.client_name ? ' – ' + b.client_name : '');
  FQ.$('#brandName').textContent = name;
  const L = b.login || {}, lg = FQ.$('#login');
  lg.className = 'login ' + (L.layout === 'centered' ? 'centered' : 'split') + (lg.hidden ? '' : '');
  lg.style.setProperty('--l1', b.primary_color || '#2b44ff'); lg.style.setProperty('--l2', L.color_2 || '#0b1238');
  lg.style.setProperty('--lbg', L.bg_url ? `url("${L.bg_url}")` : 'none');
  FQ.$('#loginBrandName').textContent = name; FQ.$('#loginClient').textContent = b.client_name || '';
  FQ.$('#loginClient').hidden = !b.client_name;
  FQ.$('#loginTitle').textContent = L.headline || 'Welcome back'; FQ.$('#loginSub').textContent = L.subtext || '';
  FQ.$('#loginFooter').textContent = L.footer || ''; FQ.$('#loginFooterSmall').textContent = L.footer || '';
  FQ.$('#loginFeatures').replaceChildren(...(L.features || []).slice(0, 4).map(t => { const li = document.createElement('li'); li.textContent = t; return li; }));
  for (const id of ['brandLogo', 'loginLogo', 'loginLogoSmall']) { const el = FQ.$('#' + id); if (b.logo_url) { el.src = b.logo_url; el.hidden = false; } else el.hidden = true; }
  if (L.layout === 'centered') FQ.$('#loginLogoSmall').hidden = !b.logo_url;
  if (b.favicon_url) FQ.$('#favicon').href = b.favicon_url;
};
})();
