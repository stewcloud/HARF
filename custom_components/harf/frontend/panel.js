const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
class HARFPanel extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); this.tab='Learn'; this.busy=false; this.error=''; this.draft=null; }
  set hass(value) { this._hass=value; if(!this.started && this.isConnected) this.start(); }
  connectedCallback() { if(this._hass && !this.started) this.start(); }
  disconnectedCallback() { clearInterval(this.timer); this.started=false; }
  async start() { this.started=true; await this.refresh(); this.timer=setInterval(()=>this.refresh(false),3000); }
  async request(op,data={}) { return this._hass.callWS({type:'harf/request',op,data}); }
  async refresh(render=true) {
    try { this.state=await this.request('snapshot'); if(render || (!this.dirty && !this.shadowRoot.activeElement)) this.render(); }
    catch(e) { this.error=e.message || String(e); this.render(); }
  }
  opts(records,selected='',filter=()=>true) { return Object.entries(records).filter(([,r])=>filter(r)).map(([id,r])=>`<option value="${esc(id)}" ${selected===id?'selected':''}>${esc(r.name)}</option>`).join(''); }
  field(name,label,type='text',value='') { return `<label>${label}<input name="${name}" type="${type}" value="${esc(value)}" ${type==='checkbox' && value?'checked':''} ${type==='text'?'required':''}></label>`; }
  select(name,label,options,multiple=false) { return `<label>${label}<select name="${name}" ${multiple?'multiple size="5"':''} required>${options}</select></label>`; }
  form(section,fields) { return `<form data-section="${section}">${fields}<button type="submit">Save ${section.replace(/s$/,'')}</button><button type="reset">Clear</button></form>`; }
  records(section) {
    const lib=this.state.library;
    return Object.entries(lib[section]).map(([id,r])=>`<article><strong>${esc(r.name)}</strong><small>${esc(id)} ${section==='nodes'?(this.state.nodes_online[id]?' · RF online':' · RF unavailable'):''}</small>
      ${section==='commands'?`<button data-send="${esc(id)}">Send to group</button>`:''}
      <button data-edit="${section}" data-id="${esc(id)}">Edit</button><button class="quiet" data-delete="${section}" data-id="${esc(id)}">Delete</button></article>`).join('') || '<p class="muted">Nothing saved yet.</p>';
  }
  render() {
    const root=this.shadowRoot;
    this.dirty=false;
    if(!this.state) { root.innerHTML=`<p>${esc(this.error || 'Connecting to HARF…')}</p>`; return; }
    const s=this.state,l=s.library, ids=this.field('id','Stable ID (letters, numbers, - or _)'),name=this.field('name','Name');
    let body='';
    if(this.tab==='Nodes') {
      body=`<h2>Proxy nodes</h2><p>Add each ESPHome node once. Receiver ID must match its firmware node_name. Enable MagicBand on the physical node as well.</p>`+
        this.form('nodes',ids+name+this.select('tx','RF transmitter','<option value="">No RF transmitter</option>'+s.rf_transmitters.map(t=>`<option>${esc(t)}</option>`).join(''))+
        this.field('rx','Receiver node ID')+this.select('magic_action','MagicBand action','<option value="">No MagicBand action</option>'+s.magic_actions.map(t=>`<option>${esc(t)}</option>`).join(''))+
        this.field('enabled','Node enabled','checkbox',true)+this.field('rf_enabled','RF enabled','checkbox',true)+this.field('magic_enabled','MagicBand enabled for group dispatch','checkbox',false))+this.records('nodes');
    } else if(this.tab==='Groups') {
      body='<h2>Coverage groups</h2><p>RF and MagicBand groups are independent. A command is submitted concurrently to all enabled members.</p>'+
        this.form('groups',ids+name+this.select('kind','System','<option value="rf">RF</option><option value="magicband">MagicBand+</option>')+this.select('nodes','Member nodes',this.opts(l.nodes),true))+this.records('groups');
    } else if(this.tab==='Learn') {
      const receivers=Object.values(l.nodes).filter(n=>n.enabled&&n.rf_enabled).map(n=>`<option value="${esc(n.rx)}">${esc(n.name)} · ${esc(n.rx)}</option>`).join('');
      body=`<h2>Capture a remote</h2><p>Choose a receiver, start learning, then press one remote button. Captures are temporary until saved. Listening is fixed at 433.92 MHz in this firmware.</p>
        <form id="learn">${this.select('rx','Receiver',receivers)}<button>Listen for 30 seconds</button><button type="button" id="stop-learn">Stop listening</button></form>
        <p>${s.capture&&s.capture.remaining>0?`Listening on ${esc(s.capture.rx)} · ${Math.ceil(s.capture.remaining)}s remaining`:'Not learning'}</p>
        <div class="captures">${s.sniffer.map(c=>`<article><strong>${new Date(c.time*1000).toLocaleTimeString()}</strong><small>${esc(c.node)} · ${c.signal.timings.length} timings</small><button data-use="${c.id}">Use capture</button></article>`).join('')||'<p class="muted">Your captures will appear here.</p>'}</div>
        <h2>Save a command</h2>`+this.commandForm(ids,name)+this.records('commands');
    } else if(this.tab==='Devices') {
      body='<h2>Create a switch or light</h2><p>Map distinct On and Off commands. State is assumed; this does not confirm the fixture received the signal.</p>'+
        this.form('devices',ids+name+this.select('kind','Entity type','<option value="switch">Switch</option><option value="light">Light (On/Off)</option>')+this.select('on','On command',this.opts(l.commands))+this.select('off','Off command',this.opts(l.commands)))+this.records('devices');
    } else if(this.tab==='MagicBand') {
      body=`<h2>MagicBand+ broadcasts</h2><p>Selected nodes broadcast concurrently. Stop ends advertising; it does not guarantee an animation already running on a band stops immediately.</p>
        <form id="magic">${this.select('group_id','MagicBand group',this.opts(l.groups,'',r=>r.kind==='magicband'))}${this.select('effect_id','Effect',this.opts(l.effects))}${this.field('duration_ms','Broadcast duration (ms, 100–60000)','number',5000)}<button>Broadcast to group</button><button type="button" id="stop-magic">Stop group broadcast</button></form>
        <h2>Effect library</h2>`+this.form('effects',ids+name+this.field('payload','Manufacturer payload hex (exclude 0183)')+this.field('wake','Wake band first','checkbox',true))+this.records('effects');
    } else if(this.tab==='History') {
      body='<h2>Transmission history</h2><p>Submitted means the action was handed to a proxy, not acknowledged by the fixture.</p>'+s.history.map(h=>`<article><strong>${esc(h.kind)} · ${new Date(h.time*1000).toLocaleTimeString()}</strong><pre>${esc(JSON.stringify(h.nodes,null,2))}</pre></article>`).join('');
    } else {
      body='<h2>Backup and move your library</h2><p>Exports contain nodes, groups, commands, device mappings and effects. Import replaces the library atomically and does not transmit anything.</p><button id="export">Download JSON backup</button><label>Import library JSON<input type="file" id="import" accept="application/json,.json"></label>';
    }
    root.innerHTML=`<style>
      :host{display:block;height:100%;overflow:auto;background:var(--primary-background-color,#f6f7fa);color:var(--primary-text-color,#192b3d);font:15px system-ui}main{max-width:1100px;margin:auto;padding:24px}header{display:flex;align-items:center;gap:14px}h1{font-size:28px;margin:0}.brand-icon{object-fit:contain;flex-shrink:0}header span{color:var(--secondary-text-color,#64748b)}nav{display:flex;gap:8px;flex-wrap:wrap;margin:25px 0}button{font:inherit;padding:10px 15px;border:1px solid var(--divider-color,#d3dbe4);border-radius:9px;background:var(--card-background-color,white);color:inherit;cursor:pointer}nav button.active,button[type=submit]{background:#206e76;color:white}button:hover{border-color:#288b92}.quiet{color:#b74343}form{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;padding:20px;background:var(--card-background-color,white);border-radius:14px;margin:15px 0 25px}label{display:flex;flex-direction:column;gap:7px;font-size:13px}input,select,textarea{box-sizing:border-box;padding:10px;border-radius:7px;border:1px solid var(--divider-color,#cad3df);font:inherit;background:var(--primary-background-color,#fff);color:inherit;max-width:100%}input[type=checkbox]{width:22px;height:22px}textarea{min-height:100px}article{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dde3ea);border-radius:10px;padding:14px;margin:10px 0}article strong{min-width:150px}small,.muted{color:var(--secondary-text-color,#667788)}small{flex:1}pre{white-space:pre-wrap;width:100%;font-size:13px}.error{background:#fee7e7;color:#8d2222;padding:12px;border-radius:9px}.captures{max-height:280px;overflow:auto}p{line-height:1.6}h2{margin-top:30px;font-size:21px}@media(max-width:600px){main{padding:16px}form{grid-template-columns:1fr}}
    </style><main><header><img class="brand-icon" src="/harf_static/icon.png" alt="HARF" width="48" height="48"><h1>HARF</h1><span>Local RF + MagicBand controls · v0.1</span></header><nav>${['Learn','Nodes','Groups','Devices','MagicBand','History','Backup'].map(t=>`<button data-tab="${t}" class="${t===this.tab?'active':''}">${t}</button>`).join('')}</nav>${this.error?`<p class="error" role="alert">${esc(this.error)}</p>`:''}${body}</main>`;
    root.querySelectorAll('form').forEach(form=>form.addEventListener('input',()=>{this.dirty=true;}));
    root.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{this.tab=b.dataset.tab;this.error='';this.render();});
    root.querySelectorAll('form[data-section]').forEach(form=>form.onsubmit=e=>{e.preventDefault();this.saveForm(form);});
    root.querySelectorAll('[data-send]').forEach(b=>b.onclick=()=>this.act('send',{command_id:b.dataset.send}));
    root.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>this.edit(b.dataset.edit,b.dataset.id));
    root.querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>{if(confirm('Delete this record? Referenced records must be removed from devices/groups first.'))this.act('delete',{section:b.dataset.delete,id:b.dataset.id});});
    root.querySelectorAll('[data-use]').forEach(b=>b.onclick=()=>{this.draft=s.sniffer.find(c=>c.id===b.dataset.use).signal;this.render();});
    const learn=root.querySelector('#learn');if(learn)learn.onsubmit=e=>{e.preventDefault();this.act('learn',{rx:learn.elements.rx.value});};
    root.querySelector('#stop-learn')?.addEventListener('click',()=>this.act('stop_learn'));
    const magic=root.querySelector('#magic');if(magic)magic.onsubmit=e=>{e.preventDefault();this.act('magicband',{group_id:magic.elements.group_id.value,effect_id:magic.elements.effect_id.value,duration_ms:Number(magic.elements.duration_ms.value)});};
    root.querySelector('#stop-magic')?.addEventListener('click',()=>this.act('stop_magicband',{group_id:magic.elements.group_id.value}));
    root.querySelector('#export')?.addEventListener('click',async()=>{const data=await this.request('export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='harf-library.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    root.querySelector('#import')?.addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;if(file.size>2000000){this.error='Import exceeds 2 MB';this.render();return;}try{const data=JSON.parse(await file.text());if(confirm('Replace the current library with this backup?'))await this.act('import',{library:data});}catch(err){this.error=err.message;this.render();}});
  }
  commandForm(ids,name) { const l=this.state.library;return this.form('commands',ids+name+
    this.select('group','RF proxy group',this.opts(l.groups,'',r=>r.kind==='rf'))+
    `<label>Signed pulse timings (µs)<textarea name="timings" required>${esc(this.draft?.timings.join(',')||'')}</textarea></label>`+
    this.field('frequency','Frequency (Hz)','number',433920000)+this.field('repeats','Total sends (1–10)','number',this.draft?.repeats||3)+this.field('gap_ms','Gap between sends (ms)','number',15)+
    this.field('trigger','Create received-command event','checkbox',true)+this.field('repeat_sensitive','Toggle / Next / relative command','checkbox',false)); }
  edit(section,id) { const record=this.state.library[section][id];const form=this.shadowRoot.querySelector(`form[data-section="${section}"]`);if(!form)return;
    for(const [key,value] of Object.entries({id,...record,...(record.signal||{})})){const input=form.elements.namedItem(key);if(!input)continue;if(input.type==='checkbox')input.checked=value;else if(input.multiple)for(const option of input.options)option.selected=value.includes(option.value);else input.value=Array.isArray(value)?value.join(','):value;}
    this.dirty=true;
    form.scrollIntoView({behavior:'smooth'});
  }
  async saveForm(form) { const section=form.dataset.section,values={};for(const input of form.elements){if(!input.name)continue;values[input.name]=input.type==='checkbox'?input.checked:input.multiple?[...input.selectedOptions].map(o=>o.value):input.type==='number'?Number(input.value):input.value;}
    const id=values.id;delete values.id;
    if(section==='commands'){values.signal={timings:values.timings,frequency:values.frequency,repeats:values.repeats,gap_ms:values.gap_ms};for(const key of ['timings','frequency','repeats','gap_ms'])delete values[key];}
    await this.act('save',{section,id,record:values});
  }
  async act(op,data={}) { if(this.busy)return;this.busy=true;this.error='';try{await this.request(op,data);await this.refresh();}catch(e){this.error=e.message||String(e);this.render();}finally{this.busy=false;} }
}
if(!customElements.get('harf-panel'))customElements.define('harf-panel',HARFPanel);
