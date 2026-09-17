/* Replay file references are matched exactly, never by basename or live fallback. */
(function(root) {
  'use strict';
  function safeUrl(value) {
    const text=String(value || '');
    if (!/^\/api\/review\/[A-Za-z0-9_.-]+\/(?:files|assets)\/.+/.test(text) || /[\\\r\n]/.test(text)) return '';
    try {
      const url=new URL(text,'http://archive.local');
      if (url.origin!=='http://archive.local' || !/^\/api\/review\/[A-Za-z0-9_.-]+\/(?:files|assets)\//.test(url.pathname)) return '';
      const decoded=decodeURIComponent(url.pathname);
      if(decoded.split('/').some(part=>part==='..' || part==='.') || decoded.includes('\\')) return '';
      return text;
    } catch (_) { return ''; }
  }
  function mapper(files, run, cycle, timestamp) {
    const references=new Map(), cutoff=Date.parse(timestamp);
    const ordered=[...files].filter(f=>f.run_id===run && safeUrl(f.url)).sort((a,b)=>(Date.parse(a.captured_at)||0)-(Date.parse(b.captured_at)||0));
    for (const file of ordered) {
      references.set(file.url,file.url);
      references.set(file.download_url,file.download_url);
      const captured=Date.parse(file.captured_at);
      if (file.loop_index != null && Number(file.loop_index)!==Number(cycle)) continue;
      if (Number.isFinite(captured) && Number.isFinite(cutoff) && captured>cutoff) continue;
      for (const alias of file.aliases || []) references.set(alias,file.url);
    }
    return value => {
      const text=String(value || '');
      if(references.has(text)) return references.get(text);
      // Only local artifact URLs can supply an encoded source-path reference.
      if(!text.startsWith('/api/')) return '';
      try {
        const url=new URL(text,'http://archive.local');
        const match=references.get(url.pathname) || references.get(url.searchParams.get('path'));
        return match ? match + (url.searchParams.get('download')==='1' ? '?download=1' : '') : '';
      } catch (_) {return '';}
    };
  }
  const api={safeUrl,mapper};
  if(typeof module!=='undefined') module.exports=api; else root.AX4LABReplayFiles=api;
})(typeof window!=='undefined'?window:this);
