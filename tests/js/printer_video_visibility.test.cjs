const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('hidden video disconnects, visible reconnects, and detached cards are released', () => {
  const events = {};
  const doc = {hidden:false, addEventListener:(name, fn) => events[name] = fn};
  let onIntersection;
  const observed = new Set();
  class Observer {
    constructor(fn) { onIntersection = fn; }
    observe(img) { observed.add(img); }
    unobserve(img) { observed.delete(img); }
  }
  const global = {document:doc, innerHeight:100, IntersectionObserver:Observer,
    addEventListener:(name, fn) => events[name] = fn};
  global.window = global;
  vm.runInNewContext(fs.readFileSync('web/static/printer_video_visibility.js','utf8'), global);
  const img = {isConnected:true, dataset:{}, src:'/api/printer/video-stream.mjpeg?t=1',
    getAttribute() { return this.src; }, removeAttribute() { this.src = ''; },
    getBoundingClientRect() { return {width:100,height:80,top:0,bottom:80}; }};
  global.ATRPrinterVideoVisibility.sync({querySelectorAll:()=>[img]});
  doc.hidden = true; events.visibilitychange(); assert.equal(img.src, '');
  doc.hidden = false; events.visibilitychange(); assert.match(img.src, /mjpeg/);
  onIntersection([{target:img,isIntersecting:false}]); assert.equal(img.src, '');
  onIntersection([{target:img,isIntersecting:true}]); assert.match(img.src, /mjpeg/);
  img.isConnected = false;
  global.ATRPrinterVideoVisibility.sync({querySelectorAll:()=>[]});
  assert.equal(img.src, ''); assert.equal(observed.size, 0);
});
