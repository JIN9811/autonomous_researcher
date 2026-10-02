/* Bound printer video work to visible cards; never buffer frames in JavaScript. */
(function (global) {
  "use strict";
  const images = new Set();
  const visible = new WeakMap();
  const sources = new WeakMap();
  const retries = new WeakMap();
  const handlers = new WeakMap();
  function cancelRetry(img) {
    if (retries.has(img)) global.clearTimeout(retries.get(img));
    retries.delete(img);
  }
  function retry(img) {
    if (retries.has(img) || !images.has(img) || !img.isConnected || document.hidden || visible.get(img) === false) return;
    retries.set(img, global.setTimeout(() => {
      retries.delete(img);
      if (!images.has(img) || !img.isConnected || document.hidden || visible.get(img) === false) return;
      const src = sources.get(img);
      if (src) img.src = `${src}${src.includes('?') ? '&' : '?'}video_retry=${Date.now()}`;
    }, 1000));
  }
  function update(img) {
    if (!img.isConnected || (img.matches && !img.matches('.printer-video-stream, .ar-spm-video-stream'))) {
      cancelRetry(img);
      if ((img.getAttribute('src') || '').includes('/api/printer/video-stream.mjpeg')) img.removeAttribute("src");
      observer?.unobserve(img);
      const callbacks = handlers.get(img);
      if (callbacks) {
        img.removeEventListener('error', callbacks.error);
        img.removeEventListener('load', callbacks.load);
      }
      images.delete(img);
      return;
    }
    const show = !document.hidden && visible.get(img) !== false;
    const current = img.getAttribute('src') || '';
    if (current.includes('/api/printer/video-stream.mjpeg') && !current.includes('video_retry=')) sources.set(img, current);
    if (!show) { cancelRetry(img); img.removeAttribute("src"); }
    else if (!current && sources.get(img)) img.src = sources.get(img);
  }
  const observer = typeof IntersectionObserver === "function" ? new IntersectionObserver(entries => {
    for (const entry of entries) {
      visible.set(entry.target, entry.isIntersecting);
      update(entry.target);
    }
  }) : null;
  function sync(root) {
    for (const img of images) update(img);
    for (const img of root?.querySelectorAll(".printer-video-stream, .ar-spm-video-stream") || []) {
      if (images.has(img)) continue;
      const src = img.getAttribute("src") || "";
      if (!src.includes("/api/printer/video-stream.mjpeg")) continue;
      sources.set(img, src); // Live report patches may remove DOM data attributes.
      images.add(img);
      const callbacks = {error: () => retry(img), load: () => { if (img.complete) retry(img); }};
      handlers.set(img, callbacks);
      img.addEventListener?.('error', callbacks.error);
      img.addEventListener?.('load', callbacks.load);
      const rect = img.getBoundingClientRect();
      visible.set(img, rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < global.innerHeight);
      observer?.observe(img);
      update(img);
    }
  }
  document.addEventListener("visibilitychange", () => { for (const img of images) update(img); });
  global.addEventListener("pagehide", () => { for (const img of images) { cancelRetry(img); img.removeAttribute("src"); } });
  global.addEventListener("pageshow", () => { for (const img of images) update(img); });
  global.ATRPrinterVideoVisibility = Object.freeze({ sync });
})(window);
