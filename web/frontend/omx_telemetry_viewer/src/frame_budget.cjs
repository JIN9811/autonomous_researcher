// Presentation budget only; never throttles received robot telemetry.
function frameBudget(now, previous, visible) {
  if (!visible || now - previous < 1000 / 15 - 0.5) return null;
  const elapsed = Math.min(250, Math.max(0, now - previous));
  return { timestamp: now, alpha: 1 - Math.pow(1 - 0.28, elapsed / (1000 / 60)) };
}
module.exports = { frameBudget };
