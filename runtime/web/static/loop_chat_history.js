/* Read-only transcript history, independent of the bounded live-message cache.
 * Keep text/identity only; never retain agent payloads, geometry or image blobs.
 */
(function (root) {
  let run = "", sessionId = "", generation = 0, total = 0;
  let records = new Map(), loaded = false, loading = false, retryAt = 0;
  const fields = ["role", "content", "timestamp", "ok", "message_id", "transcript_index",
    "cycle_index", "cycle", "total_cycles", "event_fields", "event_type", "message_class",
    "message_type", "surface", "surfaces", "visibility", "agent_id", "model", "run_id"];
  function index(message) {
    return message && message.transcript_index != null ? Number(message.transcript_index) : NaN;
  }
  function ingest(messages) {
    for (const message of messages || []) {
      const id = index(message);
      if (!Number.isFinite(id) || (message.run_id && message.run_id !== run)) continue;
      const small = {_loopArchive: true};
      for (const key of fields) if (message[key] !== undefined) small[key] = message[key];
      records.set(id, small);
    }
  }
  function reset(nextRun = "", nextSession = "") {
    generation += 1; run = nextRun; sessionId = nextSession;
    records = new Map(); loaded = false; loading = false; retryAt = 0; total = 0;
  }
  async function sync(session, changed) {
    const nextRun = String(session?.state?.run_id || "");
    const nextSession = String(session?.planning_session_id || "");
    if (nextRun !== run || nextSession !== sessionId || Number(session.message_total || 0) < total) reset(nextRun, nextSession);
    total = Number(session.message_total || 0);
    ingest(session.messages);
    if (!run || loaded || loading || Date.now() < retryAt) return;
    if (!session.has_more_messages) { loaded = true; return; }
    loading = true;
    const token = generation;
    let before = Number(session.next_before);
    try {
      while (Number.isFinite(before) && before > 0) {
        const query = new URLSearchParams({session_id: sessionId, before: String(before), limit: "240"});
        const response = await fetch(`/api/planning/messages?${query}`);
        if (!response.ok) throw new Error(`Transcript HTTP ${response.status}`);
        const page = await response.json();
        if (token !== generation) return;
        if (!String(page.transcript_path || "").replaceAll("\\", "/").split("/").includes(run)) throw new Error("Transcript run mismatch");
        ingest(page.messages);
        const next = Number(page.next_before);
        if (!page.has_more_messages) { loaded = true; break; }
        if (!Number.isFinite(next) || next >= before || next < 0) throw new Error("Transcript cursor did not advance");
        before = next;
      }
      if (before === 0) loaded = true;
      if (token === generation) changed();
    } catch (error) {
      if (token === generation) retryAt = Date.now() + 15000;
    } finally {
      if (token === generation) loading = false;
    }
  }
  function merge(messages) {
    if (root.AX4LABReplay) return Array.isArray(messages) ? messages : [];
    const merged = new Map(records);
    const extra = [];
    for (const message of messages || []) {
      const id = index(message);
      if (Number.isFinite(id)) merged.set(id, message);
      else extra.push(message);
    }
    // Pre-workflow conversation stays in the live cache. Only loop history is
    // kept outside it, with explicit cycle identities for page-boundary stability.
    let cycle = 0;
    const ordered = [...merged.values()].sort((a, b) => index(a) - index(b)).filter(message => {
      const fields = message.event_fields || {};
      const match = String(message.content || "").match(/\bcycle\s*[=:]?\s*(\d+)/i);
      cycle = Number(message.cycle_index || message.cycle || fields.cycle_index || fields.cycle || match?.[1] || cycle);
      if (!message._loopArchive) return true;
      if (cycle > 0) { message.cycle_index = cycle; return true; }
      return false;
    });
    return [...ordered, ...extra];
  }
  root.AX4LABLoopChatHistory = {sync, merge, reset};
})(window);
