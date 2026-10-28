const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const {JSDOM}=require(process.env.HARF_JSDOM || 'jsdom');
function panel(){
  const dom=new JSDOM('',{runScripts:'outside-only',url:'http://localhost'});
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
