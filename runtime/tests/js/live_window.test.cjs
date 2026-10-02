const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/app.js', 'utf8');
const fn = source.slice(source.indexOf('function openLiveGuiWindow()'), source.indexOf('function openLerobotWindow()'));

test('Runtime IDE uses the shared separate-window launcher', () => {
  const html = fs.readFileSync('web/templates/index.html', 'utf8');
  assert.match(html, /id="btn-open-runtime-ide"[^>]*href="\/ide"/);
  assert.match(source, /"btn-open-knowledge", "btn-open-runtime-ide"/);
});

test('all seven workspace cells share generated icons with their documentation', () => {
  const html = fs.readFileSync('web/templates/index.html', 'utf8');
  const mappings = {printer:'device_bridges/printer_fleet_bridge',windows:'device_bridges/windows_pyautogui_bridge',lerobot:'device_bridges/lerobot_bridge',bo:'agents/bo_agent',plc:'device_bridges/plc_safety_bridge',camera:'device_bridges/utm_vision_bridge',knowledge:'agents/knowledge_agent'};
  assert.equal((html.match(/class="workspace-launch"/g)||[]).length, 7);
  for (const [icon,doc] of Object.entries(mappings)) {
    const path = `web/static/workspace_icons/${icon}.webp`;
    assert.ok(fs.existsSync(path));
    assert.ok(html.includes(`/static/workspace_icons/${icon}.webp`));
    assert.ok(fs.readFileSync(`docs/${doc}.md`,'utf8').includes(`../../${path}`));
  }
});

test('workspace popups never replace the main page when blocked', () => {
  const start = source.indexOf('function openWorkspaceWindow(');
  assert.notEqual(start, -1);
  const helper = source.slice(start, source.indexOf('function openLerobotWindow()', start));
  const paths = ['/printer','/equipment/windows','/lerobot','/bo','/plc','/device-bridge/vision-utm','/knowledge'];
  const opened = [];
  const context = { URL, window: {location:{origin:'http://localhost:7860',href:'http://localhost:7860/'},
    open:(...args)=>{opened.push(args);return null;},alert:()=>{}}};
  vm.runInNewContext(helper, context);
  paths.forEach(path => context.openWorkspaceWindow(path));
  assert.equal(opened.length, 7);
  assert.ok(opened.every(args=>args[1]==='_blank' && args[2].includes('popup=yes')));
  assert.equal(context.window.location.href, 'http://localhost:7860/');
});

test('Live GUI opens to available screen area without fullscreen', () => {
  let opened;
  const context = { URL, backendSelect: null, goalInput: null,
    window: { location: {origin:'http://localhost:7860'},
      screen: {availWidth:1920,availHeight:1040,availLeft:1920,availTop:0},
      open: (...args) => { opened=args; } } };
  vm.runInNewContext(fn + '\nopenLiveGuiWindow();', context);
  assert.match(opened[0], /\/live\?auto=1/);
  assert.match(opened[2], /width=1920,height=1040/);
  assert.match(opened[2], /left=1920,top=0/);
  assert.ok(!opened[2].includes('fullscreen'));
});
