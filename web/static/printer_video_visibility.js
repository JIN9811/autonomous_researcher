/* Bound printer video work to visible cards; never buffer frames in JavaScript. */
(function (global) {
  "use strict";
  const images = new Set();
  const visible = new WeakMap();
  function update(img) {
    if (!img.isConnected) {
      img.removeAttribute("src");
      observer?.unobserve(img);
      images.delete(img);
      return;
    }
    const show = !document.hidden && visible.get(img) !== false;
    if (!show) img.removeAttribute("src");
    else if (!img.getAttribute("src") && img.dataset.printerVideoSrc) img.src = img.dataset.printerVideoSrc;
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
      img.dataset.printerVideoSrc = src;
      images.add(img);
      const rect = img.getBoundingClientRect();
      visible.set(img, rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < global.innerHeight);
      observer?.observe(img);
      update(img);
    }
  }
  document.addEventListener("visibilitychange", () => { for (const img of images) update(img); });
  global.addEventListener("pagehide", () => { for (const img of images) img.removeAttribute("src"); });
  global.addEventListener("pageshow", () => { for (const img of images) update(img); });
  global.ATRPrinterVideoVisibility = Object.freeze({ sync });
})(window);
