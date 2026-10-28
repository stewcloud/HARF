const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const {JSDOM}=require(process.env.HARF_JSDOM || 'jsdom');
function panel(){
  const dom=new JSDOM('',{runScripts:'outside-only',url:'http://localhost'});
  // Match the scoped custom-element registry polyfill used by HA.
  Object.defineProperty(dom.window.HTMLFormControlsCollection.prototype,Symbol.iterator,{configurable:true,value(){throw new Error('Method not implemented.');}});
  dom.window.eval(readFileSync(join(__dirname,'../custom_components/harf/frontend/panel.js'),'utf8'));
  const p=dom.window.document.createElement('harf-panel');
  p.state={library:{nodes:{},groups:{},commands:{},devices:{},effects:{}},rf_transmitters:['radio_frequency.rf_proxy_01_rf_transmitter'],magic_actions:[],nodes_online:{}};
  p.tab='Nodes';p.render();
  const form=p.shadowRoot.querySelector('form');
  form.elements.namedItem('id').value='rf-proxy-01';
  form.elements.namedItem('name').value='RF Proxy 01';
  form.elements.namedItem('rx').value='rf-proxy-01';
  const calls=[];
  p._hass={callWS:async msg=>{calls.push(msg);return p.state;}};
  return {p,form,calls,dom};
}
test('RF-only node saves without a MagicBand action',async()=>{
  const {p,form,calls,dom}=panel();
  form.elements.namedItem('tx').value='radio_frequency.rf_proxy_01_rf_transmitter';
  assert.equal(form.checkValidity(),true);
  await p.saveForm(form);
  assert.equal(calls[0].op,'save');
  assert.equal(calls[0].data.record.magic_action,'');
  assert.equal(calls[0].data.record.rx,'rf-proxy-01');
  dom.window.close();
});
test('node may be registered before a transmitter is selected',async()=>{
  const {p,form,calls,dom}=panel();
  await p.saveForm(form);
  assert.equal(calls[0].data.record.tx,'');
  dom.window.close();
});
test('missing required name produces a visible error without clearing the form',async()=>{
  const {p,form,calls,dom}=panel();
  form.elements.namedItem('name').value='';
  await p.saveForm(form);
  assert.equal(calls.length,0);
  assert.match(p.shadowRoot.querySelector('[role=alert]').textContent,/Name/);
  assert.equal(form.elements.namedItem('id').value,'rf-proxy-01');
  dom.window.close();
});
test('backend rejection preserves entered values and displays its message',async()=>{
  const {p,form,dom}=panel();
  p._hass={callWS:async()=>{throw new Error('Invalid receiver ID');}};
  await p.saveForm(form);
  assert.match(p.shadowRoot.querySelector('[role=alert]').textContent,/Invalid receiver ID/);
  assert.equal(p.shadowRoot.querySelector('form').elements.namedItem('name').value,'RF Proxy 01');
  assert.equal(p.busy,false);
  dom.window.close();
});

const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('Save click persists and displays the returned record even if submit is intercepted',async()=>{
  const {p,form,calls,dom}=panel();
  // A host page or browser extension can intercept native form submission.
  form.addEventListener('submit',event=>{event.preventDefault();event.stopImmediatePropagation();},true);
  p._hass={callWS:async msg=>{
    calls.push(msg);
    assert.equal(msg.op,'save');
    const saved=structuredClone(p.state);
    saved.library.nodes[msg.data.id]=msg.data.record;
    return saved;
  }};
  form.querySelector('button').click();
  assert.match(p.shadowRoot.querySelector('[role=status]').textContent,/Saving/);
  await settle();
  assert.equal(calls.length,1);
  assert.equal(calls[0].data.id,'rf-proxy-01');
  assert.match(p.shadowRoot.querySelector('article').textContent,/RF Proxy 01/);
  assert.match(p.shadowRoot.querySelector('[role=status]').textContent,/Saved RF Proxy 01/);
  assert.equal(p.busy,false);
  dom.window.close();
});
test('Enter saves a node without relying on native submit',async()=>{
  const {p,form,calls,dom}=panel();
  form.elements.namedItem('name').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
  await settle();
  assert.equal(calls.filter(c=>c.op==='save').length,1);
  dom.window.close();
});
test('a stalled save times out visibly, preserves input and permits retry',async()=>{
  const {p,form,dom}=panel();
  p.requestTimeout=10;
  p._hass={callWS:()=>new Promise(()=>{})};
  form.querySelector('button').click();
  await new Promise(resolve=>setTimeout(resolve,30));
  assert.match(p.shadowRoot.querySelector('[role=alert]').textContent,/did not respond/);
  assert.equal(form.elements.namedItem('name').value,'RF Proxy 01');
  assert.equal(form.querySelector('button').disabled,false);
  assert.equal(p.busy,false);
  dom.window.close();
});
test('double-click and background polling do not duplicate or erase an in-flight save',async()=>{
  const {p,form,calls,dom}=panel();
  let finish;
  p._hass={callWS:msg=>{calls.push(msg);return new Promise(resolve=>{finish=resolve;});}};
  const button=form.querySelector('button');
  button.click();button.click();
  await p.refresh(false);
  assert.equal(calls.length,1);
  assert.equal(p.shadowRoot.querySelector('form'),form);
  finish(p.state);
  await settle();
  assert.equal(p.busy,false);
  dom.window.close();
});
