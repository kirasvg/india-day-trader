// Test observable notification behavior without a browser or notification permission prompt.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../india_trader/web/app.js'), 'utf8');
const start = source.indexOf('function notifyChanges(){');
const end = source.indexOf('function metrics(', start);
assert(start >= 0 && end > start);
const sent = [];
function Notification(title, options) { sent.push({title, ...options}); }
Notification.permission = 'granted';
const ctx = vm.createContext({Notification, window:{Notification}, money:String, clean:String, toast:()=>{}});
vm.runInContext('let alertsEnabled=true; const seenAlerts=new Set(); let state={origin:"BROKER_RESEARCH",candidates:[],alerts:[]};' + source.slice(start, end), ctx);
vm.runInContext('state.candidates=[{id:"v1",state:"PLANNED",plan:{instrument:"NSE:INFY",entry_time:"2026-10-30T09:35:00+05:30",entry:1500,stop:1490},context:{risk:{status:"BLOCK"}}}];notifyChanges();',ctx);
assert.equal(sent.length,0,'Blocked candidates must not trigger entry notifications');
vm.runInContext('state.candidates[0].context.risk.status="PASS";notifyChanges();notifyChanges();state.candidates[0].id="v2";notifyChanges();',ctx);
assert.equal(sent.length,1,'Same entry condition across refreshes/versions must be deduplicated');
vm.runInContext('state.alerts=[{instrument:"NSE:INFY",event:"STOP"}];notifyChanges();notifyChanges();',ctx);
assert.equal(sent.length,2,'New stop conditions notify once');
vm.runInContext('state.paused=true;state.candidates[0].plan.entry_time="later";notifyChanges();',ctx);
assert.equal(sent.length,2,'Paused entries must not notify');
vm.runInContext('state.alerts=[{instrument:"NSE:INFY",event:"DATA_STALE"}];state.origin="SYNTHETIC";notifyChanges();',ctx);
assert.equal(sent.length,2,'Synthetic fixtures must not emit trading notifications');
vm.runInContext('state.origin="BROKER_RESEARCH";alertsEnabled=false;notifyChanges();alertsEnabled=true;notifyChanges();',ctx);
assert.equal(sent.length,2,'Enabling alerts must not replay old conditions');
console.log('Browser alert behavior passed: gating, deduplication, stop, pause, synthetic and backlog handling.');
