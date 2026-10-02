/* Cosmetic startup cover only; never gates runtime or device controls. */
(() => {
  const cover = document.getElementById('live-boot-cover');
  if (!cover) return;
  let dismissed = false, ready = false, animationDone = false, started = false;
  const main = cover.dataset?.bootMode === 'main';
  const workspace = cover.dataset?.bootMode === 'workspace';
  const compact = main || workspace || cover.dataset?.bootMode === 'ide';
  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    clearTimeout(deadline);
    cover.classList.add('is-leaving');
    setTimeout(() => cover.remove(), 550);
  };
  const deadline = setTimeout(dismiss, 10000);
  const finish = () => { if ((ready || main || workspace) && animationDone) dismiss(); };
  const start = () => {
    if (started || dismissed) return;
    started = true;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { animationDone = true; finish(); return; }
    // Begin only after the actual logo has decoded, not at network start.
    setTimeout(() => { if (!dismissed) cover.classList.add('is-colored'); }, 600);
    setTimeout(() => { animationDone = true; finish(); }, compact ? 1700 : 2100);
  };
  window.addEventListener('ax4lab:live-ready', () => { ready = true; finish(); }, {once:true});
  window.addEventListener('keydown', event => { if (event.key === 'Escape') dismiss(); });
  const logo = cover.querySelector('img');
  const decoded = () => Promise.resolve(logo.decode?.()).then(start, start);
  logo.addEventListener('error', dismiss);
  if (logo.complete && logo.naturalWidth) decoded();
  else logo.addEventListener('load', decoded, {once:true});
})();
