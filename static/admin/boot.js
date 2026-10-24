'use strict';
(() => {
const FQ = window.FQ, h = FQ.h;

async function loadBranding() {
  try { const b = await fetch('/api/admin/branding').then(r => r.json()); FQ.applyBranding(b); } catch (e) { /* defaults */ }
}

function changePassword(forced) {
  const cur = h('input', { type: 'password', autocomplete: 'current-password' }), n1 = h('input', { type: 'password', autocomplete: 'new-password' }), n2 = h('input', { type: 'password', autocomplete: 'new-password' }), err = h('div', { class: 'error', hidden: true });
  const m = FQ.modal({ title: forced ? 'Choose a new password' : 'Change password', width: 460, onClose: () => { if (forced && FQ.state.user && FQ.state.user.must_change_password) FQ.logout(); },
    body: [forced ? h('p', {}, 'You must change your password before continuing.') : null, FQ.field('Current password', cur), FQ.field('New password', n1, 'At least 10 characters, upper & lower case and a digit.'), FQ.field('Repeat new password', n2), err],
    footer: [h('button', { class: 'btn', onclick: () => m.close() }, 'Cancel'), h('button', { class: 'btn primary', onclick: async () => {
      if (n1.value !== n2.value) { err.textContent = 'Passwords do not match'; err.hidden = false; return; }
      try { await FQ.api('/me/password', { method: 'POST', body: { current_password: cur.value, new_password: n1.value } }); FQ.state.user.must_change_password = false; m.close(); FQ.toast('Password changed', 'ok'); } catch (e) { err.textContent = e.message; err.hidden = false; } } }, 'Change password')] });
}

async function enter(user) {
  FQ.state.user = user;
  FQ.$('#login').hidden = true; FQ.$('#app').hidden = false;
  FQ.$('#who').textContent = `${user.username} · ${user.role}`;
  if (!location.hash) location.hash = '#/dashboard';
  FQ.route();
  if (user.must_change_password) changePassword(true);
}

FQ.$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault(); const f = e.target, err = FQ.$('#loginError'); err.hidden = true;
  const btn = FQ.$('#loginBtn'); btn.disabled = true; btn.textContent = 'Signing in…';
  try { const r = await FQ.api('/login', { method: 'POST', body: { username: f.username.value, password: f.password.value }, noAuthRedirect: true });
    localStorage.setItem('fq_token', r.token); f.password.value = ''; await enter(r.user); }
  catch (x) { err.textContent = x.message; err.hidden = false; }
  finally { btn.disabled = false; btn.textContent = 'Sign in'; }
});
const pw = FQ.$('#loginForm').password;
FQ.$('#pwToggle').onclick = () => { const show = pw.type === 'password'; pw.type = show ? 'text' : 'password'; FQ.$('#pwToggle').textContent = show ? 'Hide' : 'Show'; };
pw.addEventListener('keyup', (e) => { FQ.$('#capsHint').hidden = !(e.getModifierState && e.getModifierState('CapsLock')); });
FQ.$('#logoutBtn').onclick = FQ.logout;
FQ.$('#pwBtn').onclick = () => changePassword(false);

(async () => {
  await loadBranding();
  if (new URLSearchParams(location.search).get('preview') === 'login') { FQ.$('#login').hidden = false; return; }
  if (FQ.token()) { try { await enter(await FQ.api('/me', { noAuthRedirect: true })); return; } catch (e) { localStorage.removeItem('fq_token'); } }
  FQ.$('#login').hidden = false;
})();
})();
