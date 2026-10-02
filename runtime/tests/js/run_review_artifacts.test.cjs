const test=require('node:test');
const assert=require('node:assert/strict');
const {safeUrl,mapper}=require('../../web/static/run_review_artifacts.js');
const file=(path,extra={})=>({run_id:'run',url:`/api/review/run/files/${path}`,download_url:`/api/review/run/files/${path}?download=1`,aliases:[`/api/runs/run/artifact-file/${path}`,`/data/${path}`],...extra});
test('only local read-only file and image URLs are openable',()=>{
  for(const value of ['javascript:alert(1)','https://elsewhere/file.csv','/api/run/start','/api/review/run/points/000001','/api/review/run/files/%2e%2e/%2e%2e/secret','/api/review/run/files/a%5cb']) assert.equal(safeUrl(value),'');
  assert.equal(safeUrl('/api/review/run/files/a.csv?download=1'),'/api/review/run/files/a.csv?download=1');
  assert.equal(safeUrl('/api/review/run/assets/abc.png'),'/api/review/run/assets/abc.png');
});
test('exact artifact references map to read-only URLs; download stays a download',()=>{
  const resolve=mapper([file('data.csv')],'run',0,'2026-09-18T01:00:00Z');
  assert.equal(resolve('/api/runs/run/artifact-file/data.csv'),'/api/review/run/files/data.csv');
  assert.equal(resolve('/api/runs/run/artifact-file/data.csv?download=1'),'/api/review/run/files/data.csv?download=1');
  assert.equal(resolve('/api/lerobot/visualization/file?path=%2Fdata%2Fdata.csv'),'/api/review/run/files/data.csv');
  assert.equal(resolve('/elsewhere/data.csv'),'');
  assert.equal(resolve('/api/run/start'),'');
});
test('source references never select another cycle, future capture or another run',()=>{
  const artifacts=[file('old.png',{loop_index:0,captured_at:'2026-09-18T00:00:00Z',aliases:['/capture.png']}),
    file('future.png',{loop_index:0,captured_at:'2026-09-18T02:00:00Z',aliases:['/capture.png']}),
    file('other-cycle.png',{loop_index:1,aliases:['/capture.png']}),file('foreign.png',{run_id:'other',aliases:['/capture.png']})];
  const resolve=mapper(artifacts,'run',0,'2026-09-18T01:00:00Z');
  assert.equal(resolve('/capture.png'),'/api/review/run/files/old.png');
  // Session files remain explicitly browsable, without claiming snapshot identity.
  assert.equal(resolve('/api/review/run/files/future.png'),'/api/review/run/files/future.png');
});
