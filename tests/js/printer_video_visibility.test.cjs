const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('report patch cannot erase reconnect state and an ended stream retries only while visible', () => {
  const events = {}, timers = new Map(); let serial = 0;
  const doc = {hidden:false, addEventListener:(name, fn) => events[name] = fn};
  const global = {document:doc, innerHeight:100, Date,
    setTimeout:fn => { timers.set(++serial, fn); return serial; },
    clearTimeout:id => timers.delete(id), addEventListener:() => {}};
  global.window = global;
  vm.runInNewContext(fs.readFileSync('web/static/printer_video_visibility.js','utf8'), global);
  const listeners = {};
  const img = {isConnected:true, dataset:{}, src:'/api/printer/video-stream.mjpeg?t=1', complete:true,
    addEventListener:(name, fn) => listeners[name] = fn,
    removeEventListener:() => {}, matches:() => true,
    getAttribute() { return this.src; }, removeAttribute() { this.src = ''; },
    getBoundingClientRect() { return {width:100,height:80,top:0,bottom:80}; }};
  global.ATRPrinterVideoVisibility.sync({querySelectorAll:()=>[img]});
  delete img.dataset.printerVideoSrc; // Live report attribute reconciliation.
  doc.hidden = true; events.visibilitychange();
  doc.hidden = false; events.visibilitychange();
  assert.match(img.src, /video-stream.mjpeg/);
  const original = img.src;
  listeners.error(); listeners.error();
  assert.equal(timers.size, 1);
  const run = [...timers.values()][0]; timers.clear(); run();
  assert.notEqual(img.src, original);
  listeners.load(); assert.equal(timers.size, 1);
  doc.hidden = true; events.visibilitychange();
  assert.equal(timers.size, 0); assert.equal(img.src, '');
});

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
    addEventListener() {}, removeEventListener() {},
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
