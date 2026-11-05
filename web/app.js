const workspace=document.querySelector('#workspace');
let bundle,stage='current',configuration={available:false,deployment:'preview'};
const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clip=(value,size=12)=>value?value.slice(0,size)+'…':'Awaiting check';
function notify(text){document.querySelector('#toast').textContent=text;setTimeout(()=>{document.querySelector('#toast').textContent='';},4000);}
function renderReference(){
  if(!bundle)return;const r=bundle.release,m=r.manifest,old=stage==='stale';
  workspace.innerHTML=`<div class="desk-grid"><aside class="room-feed"><div class="panel-heading"><span>Example room sequence</span><small>4 steps</small></div><div class="feed-message"><b class="avatar human">Y</b><div><strong>Example reviewer</strong><p>Make the CTA an invitation to build together.</p></div></div><div class="feed-message"><b class="avatar builder">B</b><div><strong>Scripted builder fixture</strong><p>Proposed “Build together.” The earlier release was reviewed.</p></div></div><div class="feed-message"><b class="avatar human">Y</b><div><strong>Example reviewer</strong><p>Use “Join the build night” instead.</p></div></div><div class="feed-message"><b class="avatar tester">T</b><div><strong>Independent local checker</strong><p>New content checked. The previous approval no longer applies.</p></div></div><div class="feed-message last"><b class="avatar ship">↗</b><div><strong>Local release engine</strong><p>Published the newly approved artifact to local staging.</p></div></div><div class="feed-foot">This is a recorded test sequence. Live conversations appear through your connected Switch room.</div></aside><section class="release-panel"><div class="panel-heading"><span>Community page / revision ${r.revision}</span><span class="badge ${old?'warn':'pass'}">${old?'Earlier approval blocked':'Checked reference release'}</span></div><div class="release-body"><p class="eyebrow">The change you are reviewing</p><h3>A better invitation to build.</h3><div class="content-diff"><div><span>Earlier CTA</span><del>${esc(bundle.earlier.content.cta)}</del><small>Revision ${bundle.earlier.revision} · earlier approval</small></div><div><span>Current CTA</span><strong>${esc(r.content.cta)}</strong><small>Revision ${r.revision} · new approval required</small></div></div><div class="checks"><div><h4>Independent checks</h4><span>${r.report.tests.filter(t=>t.passed).length}/${r.report.tests.length} pass</span></div>${r.report.tests.map(t=>`<p class="check-row"><i>${t.passed?'✓':'×'}</i><span>${esc(t.name.replaceAll('_',' '))}</span><small>${t.passed?'Pass':'Blocked'}</small></p>`).join('')}</div>${old?`<div class="blocked"><strong>That approval belongs to the earlier revision.</strong><p>Recorded engine response: ${esc(bundle.stale_approval_rejection)}</p><p>The current content, commit and evidence require a fresh review.</p></div>`:`<div class="approved"><span>✓</span><div><strong>Recorded local approval matches this artifact.</strong><p>The test reviewer approved the current full fingerprint. Local staging serves the same bytes.</p></div></div>`}<div class="release-actions"><button class="button secondary" data-act="${old?'current':'stale'}">${old?'Back to current release':'Inspect stale approval'}</button><a class="button primary" href="/examples/reference-site.html" target="_blank" rel="noopener noreferrer">Open checked staging fixture ↗</a></div></div></section><aside class="proof-panel"><p class="eyebrow">What a yes is tied to</p><h3>The release fingerprint.</h3><p>Commit, artifact and checker evidence travel together.</p><dl><dt>Git commit</dt><dd>${esc(clip(m.git_commit))}</dd><dt>Artifact SHA256</dt><dd>${esc(clip(m.artifact_sha256))}</dd><dt>Check policy</dt><dd>${esc(clip(m.policy_sha256))}</dd><dt>Test evidence</dt><dd>${esc(clip(m.test_evidence_sha256))}</dd></dl><div class="fingerprint"><span>Complete approval fingerprint</span><code>${esc(r.digest)}</code></div><p class="proof-note">Fingerprints bind bytes. They do not attest the host, replace a code review or prove the request’s meaning was correctly understood.</p><button class="button secondary full" data-act="download">Download recorded evidence ↓</button><button class="proof-verify" data-act="verify">Check bundle integrity in this browser ↗</button><p id="integrity" role="status"></p></aside></div>`;
}
function stable(value){if(value===null||typeof value!=='object')return JSON.stringify(value);if(Array.isArray(value))return '['+value.map(stable).join(',')+']';return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stable(value[k])).join(',')+'}';}
async function hash(text){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(b=>b.toString(16).padStart(2,'0')).join('');}
async function verify(){
  const {payload_sha256,...payload}=bundle;
  const valid=await hash(stable(payload))===payload_sha256&&await hash(bundle.artifact)===bundle.release.manifest.artifact_sha256&&await hash(stable(bundle.release.manifest))===bundle.release.digest;
  document.querySelector('#integrity').textContent=valid?'✓ Recorded bundle, manifest and artifact fingerprints agree.':'The recorded bundle does not match its fingerprints.';
}
async function live(){
  const result=await fetch('/api/releases',{credentials:'same-origin'});const data=await result.json();if(!result.ok)throw new Error(data.error);
  document.querySelector('.example-note').textContent='Live team releases · requests and approvals are handled by your configured Switch participants.';
  workspace.innerHTML=`<section class="live-panel"><h3>Your team’s releases</h3>${data.releases.length?data.releases.map(r=>`<article><span class="badge">${esc(r.state)}</span><h4>Revision ${r.revision}</h4><p>${esc(r.request)}</p><p>${esc(r.content.cta||'Awaiting builder')}</p><code>${esc(r.digest||'Checks pending')}</code>${r.receipt?'<a class="button primary" href="/staging/" target="_blank" rel="noopener noreferrer">View current verified staging ↗</a>':''}</article>`).join(''):'<p>Request your first release in the connected Switch room.</p>'}<p>To request work, address the builder with <code>[releaseroom] request ...</code>. The release agent asks for a full-fingerprint approval in the same room.</p><button class="button secondary" data-act="refresh-live">Refresh room releases ↻</button></section>`;
}
document.addEventListener('click',async event=>{
  if(!(event.target instanceof Element))return;
  const target=event.target.closest('[data-act]');if(!target)return;const action=target.dataset.act;
  if(action==='stale'||action==='current'){stage=action;renderReference();}
  if(action==='verify')await verify();
  if(action==='download'){
    const blob=new Blob([JSON.stringify(bundle,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='releaseroom-recorded-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  if(action==='team')document.querySelector('#team-dialog').showModal();
  if(action==='close-team')document.querySelector('#team-dialog').close();
  if(action==='refresh-live'){try{await live();}catch(error){notify(error.message);}}
});
document.querySelector('#team-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,field=form.querySelector('input');
  try{const result=await fetch('/api/session',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_code:field.value})});field.value='';const data=await result.json();if(!result.ok)throw new Error(data.error);await live();document.querySelector('#team-dialog').close();}
  catch(error){document.querySelector('#team-error').textContent=error.message;}
});
async function start(){
  try{configuration=await (await fetch('/api/config')).json();document.querySelector('#connection').textContent=configuration.available?'Switch & builder connected':'Live Switch connection pending';}
  catch{document.querySelector('#connection').textContent='Connection status unavailable';}
  try{bundle=await (await fetch('/examples/reference-release.json')).json();renderReference();}
  catch{workspace.innerHTML='<div class="load-error">Recorded release evidence is unavailable. Open the repository to run the local demo.</div>';}
  if(configuration.authenticated)await live();
}
void start();
