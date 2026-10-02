/* One desktop fullscreen request per LIVE window; no runtime dependencies. */
(() => {
  if (window.location.pathname !== '/live' && window.location.pathname !== '/planning') return;
  if (document.body.classList.contains('run-replay-mode')) return;
  const key = 'ax4lab-live-fullscreen-attempted';
  try {
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, '1');
  } catch (_) { return; }
  const originalTitle = document.title;
  const token = Array.from(crypto.getRandomValues(new Uint8Array(16)),
    n => n.toString(16).padStart(2, '0')).join('');
  document.title = `AX4LAB LIVE [${token}]`;
  fetch('/api/ui/live-fullscreen', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({token}), signal: AbortSignal.timeout(6000),
  }).catch(() => {}).finally(() => {
    document.title = originalTitle;
  });
})();
