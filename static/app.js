'use strict';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {plumbing:'Plumbing', electrical:'Electrical', ac:'AC servicing', cleaning:'Home cleaning'};
const paths = {
  plumbing:'M4 10h16M6 10V7h8v3m-4-3V4m-3 0h6M5 10v5h4v-2h6v5h4v-8M16 21h2',
  electrical:'m13 2-8 12h6l-1 8 9-13h-7l1-7Z',
  ac:'M3 5h18v10H3zM6 9h12M7 15v4m5-4v6m5-6v4',
  cleaning:'m14 3 2 2-7 11M5 13l7 4-4 5-6-3 3-6ZM18 9v4m-2-2h4',
  home:'m3 11 9-8 9 8M5 9v12h14V9M9 21v-7h6v7',
  check:'m5 12 4 4L19 6',
  clock:'M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z'
};
const icon = (name, cls='') => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.home}"/></svg>`;
const money = value => new Intl.NumberFormat('en-IN', {style:'currency',currency:'INR',maximumFractionDigits:0}).format(Number(value) || 0);
const datePart = slot => { const d = new Date(slot); return Number.isNaN(d.valueOf()) ? String(slot || 'To be decided') : new Intl.DateTimeFormat('en-IN',{weekday:'short',day:'numeric',month:'short',timeZone:'Asia/Kolkata'}).format(d); };
const timePart = slot => { const d = new Date(slot); return Number.isNaN(d.valueOf()) ? '' : new Intl.DateTimeFormat('en-IN',{hour:'numeric',minute:'2-digit',timeZone:'Asia/Kolkata'}).format(d); };
const slotLabel = slot => `${datePart(slot)}${timePart(slot) ? `, ${timePart(slot)}` : ''}`;
let state = null;
let busy = false;
let panel = null;
let previousFocus = null;
let toastTimer;
let lastReviewed = null;
let renderedMessages = [];
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
function enter(element, delay=0) {
  if (!element || reducedMotion.matches) return;
  element.animate([{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}], {duration:320,delay,easing:'cubic-bezier(.22,1,.36,1)',fill:'backwards'});
}
function mountHTML(element, html, selector) {
  if (element.dataset.rendered === html) return false;
  element.getAnimations({subtree:true}).forEach(a=>a.cancel());
  element.innerHTML=html;
  element.dataset.rendered=html;
  const children=selector? $$(selector,element):[element];
  children.forEach((child,i)=>enter(child,Math.min(i*35,140)));
  return true;
}
function scrollConversation(target) {
  const stream=$('.conversation-stream');
  stream.scrollTo({top:target ? target.offsetTop-stream.offsetTop : stream.scrollHeight,behavior:reducedMotion.matches?'instant':'smooth'});
}
let sessionId;
try {sessionId = localStorage.getItem('orange-session');} catch {sessionId = null;}

function toast(message) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 5500);
}

function setBusy(value, event) {
  busy = value;
  $('#send-button').disabled = value;
  $('#new-errand').disabled = value;
  $('#composer-input').disabled = value;
  $$('.primary-button').forEach(b => {b.disabled = value || b.dataset.unavailable === 'true';});
  $('#request-progress').hidden=!value;
  const progress={chat:'Understanding your request',facts:'Updating the options',select:'Checking the exact quote',approve:'Confirming with the provider',recover:'Verifying the booking status',memory:'Updating your preferences'};
  $('#progress-label').textContent=progress[event]||'Checking the details';
  $('#composer-note').classList.toggle('pending-dots',value);
  $('#composer-note').textContent = value ? 'Checking the details' : 'A plan first. Your approval always.';
}

async function request(event, payload = {}) {
  if (busy) return null;
  setBusy(true,event);
  if(event==='chat') {
    appendMessage({role:'user',text:payload.text});
    $('#suggestions').hidden=true;
    scrollConversation();
  }
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    let response;
    try {
      response = await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,event,payload}),signal:controller.signal});
    } finally {clearTimeout(timeout);}
    if (!response.ok) throw new Error('The request could not be processed. Try again.');
    const snapshot = await response.json();
    if (!snapshot.session_id) throw new Error(snapshot.error || 'The server returned an incomplete response.');
    accept(snapshot);
    if (snapshot.error) toast(typeof snapshot.error === 'string' ? snapshot.error : 'Please review the details and try again.');
    return snapshot;
  } catch (error) {
    if(event==='chat' && state) {
      renderMessages();
      $('#suggestions').hidden=(state.messages||[]).some(m=>m.role==='user')||!!state.facts?.service;
    }
    toast(error.name === 'AbortError' ? 'The connection timed out. Check activity and recover before trying another booking.' : error.message || 'Cannot reach your local concierge. Start the server and try again.');
    return null;
  } finally {setBusy(false);}
}

function accept(snapshot) {
  if (state?.proposal && state.state === 'awaiting_approval') lastReviewed = {...state.proposal};
  if (state && state.session_id !== snapshot.session_id) {lastReviewed = null;renderedMessages=[];$('#messages').replaceChildren();}
  state = snapshot;
  sessionId = snapshot.session_id;
  try {localStorage.setItem('orange-session',sessionId);} catch {}
  render();
}

function readableMessage(message) {
  let text=message.text??message.content??'';
  if(message.role==='user') return text;
  const review=text.match(/^Review (book|cancel|reschedule): (.*), ([0-9T:+.-]+), INR (\d+)\./);
  if(review) return `${review[1]==='book'?'Ready for your review':review[1]==='cancel'?'Review this cancellation':'Review the new time'}: ${review[2]}, ${slotLabel(review[3])}, ${money(review[4])}. Nothing changes until you approve.`;
  if(text==='Compare providers and choose an exact slot.') return 'These professionals fit your request. Choose a time to get an exact quote.';
  if(text==='Verified receipt: book completed successfully.') return 'You’re booked. The provider has confirmed your appointment.';
  if(text==='Verified receipt: cancel completed successfully.') return 'Your cancellation is confirmed. The appointment has been released.';
  if(text==='Verified receipt: reschedule completed successfully.') return 'Your new time is confirmed. The original slot has been released.';
  if(text.startsWith('Mock scenario set to ')) return `Demo scenario: ${scenarioOptions[text.slice(21,-1)]||text.slice(21,-1).replaceAll('_',' ')}.`;
  return text;
}
function appendMessage(message) {
  const node=document.createElement('div');node.className=`message ${message.role==='user'?'user':'assistant'}`;
  const paragraph=document.createElement('p');paragraph.textContent=readableMessage(message);node.append(paragraph);
  $('#messages').append(node);renderedMessages.push(JSON.stringify(message));enter(node);
}
function renderMessages() {
  const messages=state.messages?.length?state.messages:[{role:'assistant',text:'What can I take off your list?'}];
  let common=0;
  while(common<messages.length && renderedMessages[common]===JSON.stringify(messages[common])) common++;
  if(!renderedMessages.length) $('#messages').replaceChildren();
  while($('#messages').children.length>common) $('#messages').lastElementChild.remove();
  renderedMessages=renderedMessages.slice(0,common);
  messages.slice(common).forEach(appendMessage);
  if(common<messages.length) scrollConversation();
}

function factRow(label,value,oldValue) {const changed=oldValue&&value&&oldValue!==value;return `<div><dt>${escapeHTML(label)}</dt><dd class="${value ? changed ? 'changed-value' : '' : 'unknown'}">${changed?`<span class="previous-value">${escapeHTML(oldValue)}</span>`:''}${escapeHTML(value || 'To be decided')}</dd></div>`;}

function renderTicket() {
  const facts = state.facts || {};
  const proposal = state.proposal;
  const hasFacts = !!(facts.service || facts.area || facts.budget || facts.date_range);
  const done = state.state === 'completed';
  const needsApproval = state.state === 'awaiting_approval' && proposal;
  const labels = {collecting:hasFacts ? 'Taking shape' : 'A fresh start',choosing:'Your choice',awaiting_approval:'Ready for review',executing:'In progress',reconciling:'Verifying',completed:'Verified',blocked:'Needs attention'};
  $('#ticket-state').textContent = labels[state.state] || 'Taking shape';
  $('#ticket-state').className = `state-tag${needsApproval ? ' ready' : ''}${done ? ' complete' : ''}`;
  $('#step-request').className = done || needsApproval ? 'done' : 'current';
  $('#step-review').className = done ? 'done' : needsApproval ? 'current' : '';
  $('#step-done').className = done ? 'current done' : '';
  if (!hasFacts && !proposal) {
    mountHTML($('#ticket'), `<div class="ticket-body ticket-empty"><div class="ticket-illustration">${icon('home')}</div><h2>One less thing<br>on your mind.</h2><p>Your request will take shape here.<br>You approve the final details.</p></div><div class="ticket-bottom empty-bottom"><span>No booking without your say.</span><span class="barcode" aria-hidden="true"></span></div>`);
    return;
  }
  const service = proposal?.service || facts.service;
  const actionLabel = proposal?.action === 'cancel' ? 'Cancellation' : proposal?.action === 'reschedule' ? 'A change of plans' : done ? 'All taken care of.' : 'Your home, in good hands.';
  const title = proposal ? names[service] || service || 'Home service' : names[service] || 'Your next errand';
  const price = proposal?.price;
  const previous = !done && lastReviewed?.id !== proposal?.id && lastReviewed?.action === proposal?.action ? lastReviewed : null;
  const changedQuote = previous && previous.price !== proposal?.price;
  const fields = proposal ? [factRow('Professional',proposal.provider_name || proposal.provider_id,previous?.provider_name),factRow('Date',datePart(proposal.slot),previous?datePart(previous.slot):null),factRow('Time',timePart(proposal.slot),previous?timePart(previous.slot):null),factRow('Area',facts.area),...(proposal.previous_slot ? [factRow('Moving from',slotLabel(proposal.previous_slot))] : [])] : [factRow('Where',facts.area),factRow('When',typeof facts.date_range === 'object' ? `${facts.date_range.start || ''} – ${facts.date_range.end || ''}` : facts.date_range),factRow('Time',facts.earliest_time ? `${facts.time_window || 'Any time'}, after ${facts.earliest_time}` : facts.time_window),factRow('Budget',facts.budget ? `Up to ${money(facts.budget)}` : '')];
  let bottom;
  if (done && proposal) {
    bottom = `<div class="ticket-total"><span>${proposal.action==='cancel'?'Original booking':'Confirmed total'}</span><strong>${money(price)}</strong></div><div class="receipt-status">${icon('check')}<span>${proposal.action === 'cancel' ? 'Cancellation confirmed' : proposal.action === 'reschedule' ? 'New time confirmed' : 'Booking confirmed'}</span></div><p class="receipt-id">Receipt ${escapeHTML(proposal.booking_id || 'Verified with the provider')}</p><div class="ticket-action-row"><button class="text-button" data-panel="bookings">View your errands</button><button class="text-button" data-action="new">Start another</button></div>`;
  } else if (proposal && needsApproval) {
    const action = proposal.action === 'cancel' ? 'Confirm cancellation' : proposal.action === 'reschedule' ? 'Confirm new time' : 'Approve & book';
    bottom = `<div class="ticket-total"><span>${proposal.action === 'cancel' ? 'Original booking price' : 'Your exact quote'}</span><strong class="${changedQuote?'changed-value':''}">${changedQuote?`<span class="previous-value">${money(previous.price)}</span>`:''}${money(price)}</strong></div><button class="primary-button orange" id="approve-button" data-action="approve">${action}</button><p class="ticket-disclaimer ${previous?'changed':''}">${previous ? 'Details changed. This ticket needs a fresh approval.' : proposal.action === 'cancel' ? 'Cancels only this booking. No cancellation fee in this demo.' : 'Only these details are approved. Changes need your say.'}</p>${proposal.expires_at ? `<p class="ticket-disclaimer">Held until ${escapeHTML(timePart(proposal.expires_at))} IST</p>` : ''}`;
  } else if (['executing','reconciling','blocked'].includes(state.state)) {
    bottom = `<p class="ticket-disclaimer changed">${state.state === 'blocked' ? 'Nothing new will be booked until the pending action is resolved.' : 'We’re verifying the result before calling it done.'}</p><button class="primary-button" data-action="recover" style="margin-top:12px">Check booking status</button>`;
  } else {
    bottom = `<button class="primary-button" data-action="edit">${state.state === 'choosing' ? 'Refine the details' : 'Add the details'}</button><p class="ticket-disclaimer">${state.state === 'choosing' ? 'Choose a professional from the options to see your exact quote.' : 'We only need what’s missing.'}</p>`;
  }
  mountHTML($('#ticket'), `<div class="ticket-body"><div class="ticket-title-row"><span class="service-glyph">${icon(service)}</span>${!done ? `<button class="text-button" data-action="edit">Edit details</button>` : ''}</div><p class="ticket-kicker">${escapeHTML(actionLabel)}</p><h2>${escapeHTML(title)}</h2><dl class="ticket-facts">${fields.join('')}</dl></div><div class="ticket-bottom">${bottom}</div>`,'.ticket-title-row,.ticket-kicker,h2,.ticket-facts>div,.ticket-bottom');
  if(done&&!reducedMotion.matches){const path=$('.receipt-status path');if(path){const length=path.getTotalLength();path.animate([{strokeDasharray:length,strokeDashoffset:length},{strokeDasharray:length,strokeDashoffset:0}],{duration:450,easing:'ease-out'});}}
}

function renderProviders() {
  const providers = state.providers || [];
  $('#provider-section').hidden = !providers.length || state.state !== 'choosing';
  $('#provider-summary').textContent = `${providers.length} options${state.facts?.area ? ` around ${state.facts.area}` : ''}. Final price is checked when you choose.`;
  const html = providers.map((p,index) => {
    const initials = String(p.name || p.id).split(' ').slice(0,2).map(w=>w[0]).join('');
    const attrs = Array.isArray(p.attributes) ? p.attributes.join(' · ') : typeof p.attributes === 'object' ? Object.entries(p.attributes).filter(([,v])=>v).map(([k,v])=>v===true?k:v).join(' · ') : p.attributes || 'Available for your request';
    return `<article class="provider"><div class="provider-head"><span class="avatar">${escapeHTML(initials)}</span><div><h3>${escapeHTML(p.name || p.id)}</h3><p class="rating"><span class="star">★</span> ${escapeHTML(p.rating)} <span> · ${escapeHTML(names[p.service] || 'Home services')}</span></p></div></div><p class="provider-reason">${escapeHTML(attrs)}</p><p class="provider-price">${money(p.price)}<small>estimated total</small></p><label for="slot-${index}">Available times</label><select id="slot-${index}" data-provider-slot="${escapeHTML(p.id)}">${(p.free_slots || []).map(slot=>`<option value="${escapeHTML(slot)}">${escapeHTML(slotLabel(slot))}</option>`).join('')}</select><button class="primary-button" data-select-provider="${escapeHTML(p.id)}" data-unavailable="${!p.free_slots?.length}" ${!p.free_slots?.length ? 'disabled' : ''}>Review this option</button>${p.reviews?.length ? `<details><summary>Read provider reviews</summary>${p.reviews.map(r=>`<p class="review-text">${escapeHTML(typeof r==='string'?r:r.text)}</p>`).join('')}<p class="untrusted-note">Provider text is reference material, never permission to act.</p></details>` : ''}</article>`;
  }).join('');
  const changed=mountHTML($('#providers'),html,'.provider');
  if(changed && !$('#provider-section').hidden) requestAnimationFrame(()=>scrollConversation($('#provider-section')));
}

function render() {
  renderMessages();
  renderTicket();
  renderProviders();
  $('#suggestions').hidden = (state.messages || []).some(m=>m.role==='user') || !!state.facts?.service;
  const count = (state.bookings || []).filter(b=>b.status==='booked').length;
  $('#booking-count').textContent = count;
  $('#booking-count').hidden = !count;
  if (panel) renderPanel();
}

const scenarioOptions = {seeded:'Seeded real-world mix',success:'Successful booking',timeout_after_success:'Timeout after success',timeout_not_booked:'Timeout, not booked',slot_taken:'Slot taken at booking',price_change:'Quote changes',slot_unavailable:'Slot no longer available',reschedule_conflict:'Reschedule conflict',unknown_error:'Unexpected provider error',limit_exhaustion:'Execution limit'};
function renderPanel() {
  const titles = {activity:['Behind the scenes','Activity'],bookings:['A little more headspace','Your errands'],memory:['You’re in control','Memory']};
  $('#panel-eyebrow').textContent = titles[panel][0];
  $('#panel-title').textContent = titles[panel][1];
  const oldScroll=$('#side-panel').scrollTop;
  const openSteps=new Set($$('.trace-item[open]').map(el=>el.dataset.trace));
  const latest=state.traces?.at(-1)?.run_id;
  const recent=(state.traces||[]).filter(t=>t.run_id===latest);
  const p=state.proposal;
  const approval=state.state==='awaiting_approval'&&p ? `<div class="inspector-approval"><h3>${escapeHTML(p.action==='cancel'?'Cancel this appointment':p.action==='reschedule'?'Move this appointment':'Approve this booking')}</h3><p>${escapeHTML(p.provider_name)}<br>${escapeHTML(slotLabel(p.slot))} IST · <strong>${money(p.price)}</strong></p><button class="primary-button orange" data-action="approve">${p.action==='cancel'?'Confirm cancellation':p.action==='reschedule'?'Confirm new time':'Approve & book'}</button></div>` : state.state==='completed' ? `<div class="trace-outcome">${icon('check')}<span>${p?.action==='cancel'?'Cancellation confirmed':p?.action==='reschedule'?'New time confirmed':'Booking confirmed'} · ${money(p?.price)}</span></div>` : '';
  if (panel === 'activity') {
    $('#panel-content').innerHTML = `<p class="panel-note">The latest request, as it happened. Open any step to inspect the response.</p>${approval}<details class="scenario-box" ${state.state!=='completed'?'open':''}><summary>Demo settings</summary><div><label for="scenario-select">Try a different outcome</label><select id="scenario-select">${Object.entries(scenarioOptions).map(([key,label])=>`<option value="${key}" ${state.scenario===key?'selected':''}>${label}</option>`).join('')}</select><p>These scenarios affect the local mock provider. No real appointments are made.</p><button class="primary-button" id="apply-scenario">Use this scenario</button><p class="scenario-active">Current: ${escapeHTML(scenarioOptions[state.scenario] || state.scenario || 'Seeded real-world mix')}</p></div></details><div class="trace-toolbar"><button id="download-trace">Download trace</button><button data-action="recover">Check pending booking</button></div><div id="trace-list">${recent.length ? recent.map(t=>`<details data-trace="${escapeHTML(t.id)}" class="trace-item ${escapeHTML(t.kind)}" ${openSteps.has(t.id) || (t.kind==='tool' && /status|book|cancel|reschedule/.test(t.name)) ? 'open':''}><summary><span class="trace-name">${escapeHTML(t.name || t.kind)}</span><span class="trace-meta">${t.latency_ms!==undefined ? `${Number(t.latency_ms).toFixed(1)} ms` : escapeHTML(t.kind)}</span></summary><p>${escapeHTML(traceSummary(t))}</p><pre>${escapeHTML(JSON.stringify({...(t.args!==undefined?{args:t.args}:{}),...(t.result!==undefined?{result:t.result}:{}),run_id:t.run_id,at:t.at},null,2))}</pre></details>`).join('') : `<div class="panel-empty">${icon('clock')}A quiet start.<br>Your next request will leave a trace here.</div>`}</div>`;
  } else if (panel === 'bookings') {
    $('#panel-content').innerHTML = `<p class="panel-note">Every confirmed errand, in one place. Moving or cancelling always gets its own review.</p>${(state.bookings || []).length ? state.bookings.map(b=>`<article class="booking-row"><h3>${escapeHTML(names[b.service] || b.service)} <span class="memory-badge">${escapeHTML(b.status)}</span></h3><p>${escapeHTML(b.provider_name || b.provider || b.provider_id)}<br>${escapeHTML(slotLabel(b.slot))}<br>${money(b.price)}</p>${b.status==='booked' ? `<div class="row-actions"><button class="text-button" data-move-booking="${escapeHTML(b.id)}" data-slot="${escapeHTML(b.slot)}">Find another time</button><button class="text-button" data-cancel-booking="${escapeHTML(b.id)}">Cancel this errand</button></div>` : ''}</article>`).join('') : `<div class="panel-empty">${icon('home')}Nothing on the calendar yet.<br>Your confirmed bookings will appear here.</div>`}`;
  } else {
    const friendly = {area:'Your area',earliest_time:'Not before',preferred_technician:'Preferred professional'};
    $('#panel-content').innerHTML = `<p class="panel-note">A few things that make next time easier. Inferred preferences stay unused until you confirm them.</p>${(state.memory || []).length ? state.memory.map(m=>`<article class="memory-row"><h3>${escapeHTML(friendly[m.key] || m.key)}</h3><p>${escapeHTML(m.value)}</p><span class="memory-badge">${m.source==='inferred' ? m.confirmed ? 'Inferred · confirmed by you' : 'Inferred · needs confirmation' : 'Stated by you'}</span><div class="row-actions">${m.source==='inferred'&&!m.confirmed?`<button class="text-button" data-confirm-memory="${escapeHTML(m.key)}">Confirm preference</button>`:''}<button class="text-button" data-edit-memory="${escapeHTML(m.key)}">Correct</button><button class="text-button" data-forget-memory="${escapeHTML(m.key)}">Forget</button></div></article>`).join('') : '<div class="panel-empty">A fresh slate.<br>Nothing remembered unless you choose.</div>'}<form id="memory-form" class="memory-form"><h3>Remember for next time</h3><label>Preference<select name="key"><option value="area">Area</option><option value="earliest_time">Earliest time (HH:MM)</option><option value="preferred_technician">Preferred professional</option></select></label><label>Value<input name="value" placeholder="e.g. Indiranagar" maxlength="100" required></label><button class="primary-button" type="submit">Save preference</button></form>`;
  }
  $('#side-panel').scrollTop=oldScroll;
}

function traceSummary(t) {
  if (t.kind === 'transition') return typeof t.result === 'string' ? t.result : t.result?.to || 'Workflow state updated';
  if (t.result?.error) return `Provider returned: ${t.result.error}`;
  if (t.kind === 'approval') return 'Exact action reviewed';
  if (t.kind === 'model') return 'Offline interpreter · no model API cost';
  if (t.result?.status) return `Status: ${t.result.status}`;
  return t.kind === 'tool' ? 'Local provider response' : 'Recorded for this run';
}

function openPanel(name) {
  if (!state) return;
  previousFocus = document.activeElement;
  panel = name;
  $('#side-panel').hidden = false;
  $('.ticket-stage').classList.add('inspector-open');
  $('.ticket-stage').scrollTop=0;
  $('#ticket').inert=true;
  $('#ticket').setAttribute('aria-hidden','true');
  $$('.nav-button,.activity-button').forEach(b=>b.classList.toggle('active',b.dataset.panel===name));
  renderPanel();
  enter($('#side-panel'));
  $('#side-panel').scrollTop=0;
  $('#close-panel').focus({preventScroll:true});
  if(innerWidth<=760) $('.ticket-stage').scrollIntoView({behavior:reducedMotion.matches?'instant':'smooth',block:'start'});
}
function closePanel() {
  panel = null;
  $('#side-panel').hidden = true;
  $('.ticket-stage').classList.remove('inspector-open');
  $('#ticket').inert=false;
  $('#ticket').removeAttribute('aria-hidden');
  $$('.nav-button,.activity-button').forEach(b=>b.classList.toggle('active',b.id==='home-button'));
  enter($('#ticket'));
  previousFocus?.focus?.({preventScroll:true});
}
function editDetails() {
  const form = $('#edit-form');
  const facts = state?.facts || {};
  for (const key of ['service','area','date_range','time_window','budget','earliest_time']) {
    form.elements[key].value = typeof facts[key] === 'object' ? '' : facts[key] ?? (key==='time_window'?'any':'');
  }
  $('#edit-dialog').showModal();
}

document.addEventListener('click',async event=>{
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  if (button.dataset.panel) {openPanel(button.dataset.panel);return;}
  if (button.hasAttribute('data-close-dialog')) {button.closest('dialog').close();return;}
  if (button.dataset.prompt) {await request('chat',{text:button.dataset.prompt});$('#composer-input').focus();return;}
  if (button.dataset.action==='edit') {editDetails();return;}
  if (button.dataset.action==='approve') {const p = state?.proposal;if(p) await request('approve',{proposal_id:p.id,fingerprint:p.fingerprint});return;}
  if (button.dataset.action==='recover') {await request('recover');return;}
  if (button.dataset.action==='new' || button.id==='new-errand') {await request('new');$('#composer-input').focus();return;}
  if (button.dataset.selectProvider) {
    const id = button.dataset.selectProvider;
    const select = $$('[data-provider-slot]').find(e=>e.dataset.providerSlot===id);
    if (select?.value) {await request('select',{provider_id:id,slot:select.value});if(innerWidth<=760) $('#ticket').scrollIntoView({behavior:reducedMotion.matches?'instant':'smooth',block:'center'});}
    return;
  }
  if (button.dataset.cancelBooking) {closePanel();await request('cancel',{booking_id:button.dataset.cancelBooking});return;}
  if (button.dataset.moveBooking) {
    const form = $('#move-form');form.elements.booking_id.value=button.dataset.moveBooking;form.elements.slot.value=button.dataset.slot?.slice(0,16)||'';$('#move-dialog').showModal();return;
  }
  if (button.dataset.forgetMemory) {await request('memory',{op:'forget',key:button.dataset.forgetMemory});return;}
  if (button.dataset.confirmMemory) {await request('memory',{op:'confirm',key:button.dataset.confirmMemory});return;}
  if (button.dataset.editMemory) {const form=$('#memory-form');form.elements.key.value=button.dataset.editMemory;form.elements.value.value=(state.memory||[]).find(m=>m.key===button.dataset.editMemory)?.value || '';form.elements.value.focus();return;}
  if (button.id==='apply-scenario') {const name=$('#scenario-select').value;await request('scenario',{name});toast(`Scenario set: ${scenarioOptions[name]}`);return;}
  if (button.id==='download-trace') {const blob=new Blob([JSON.stringify(state.traces||[],null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='orange-trace.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
  if (button.id==='close-panel' || button.id==='home-button') {closePanel();return;}
  if (button.id==='demo-button') {openPanel('activity');$('#scenario-select').value='timeout_after_success';$('#apply-scenario').focus();}
});

document.addEventListener('submit',async event=>{
  const form = event.target;
  if (!['composer','edit-form','move-form','memory-form'].includes(form.id)) return;
  event.preventDefault();
  if (busy) return;
  if (form.id==='composer') {
    const input=$('#composer-input');const text=input.value.trim();if(!text)return;
    input.value='';input.style.height='auto';const result=await request('chat',{text});if(!result)input.value=text;input.focus();
  } else if (form.id==='edit-form') {
    const data=Object.fromEntries(new FormData(form));const changes=Object.fromEntries(Object.entries(data).filter(([,v])=>v!==''));if(changes.budget)changes.budget=Number(changes.budget);if(!data.earliest_time&&state?.facts?.earliest_time)changes.earliest_time=null;
    $('#edit-dialog').close();await request('facts',{changes});
  } else if (form.id==='move-form') {
    const data=Object.fromEntries(new FormData(form));$('#move-dialog').close();closePanel();await request('reschedule',{booking_id:data.booking_id,slot:`${data.slot}:00+05:30`});
  } else if (form.id==='memory-form') {
    const data=Object.fromEntries(new FormData(form));await request('memory',{op:'set',key:data.key,value:data.value.trim()});
  }
});

$('#composer-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('#composer').requestSubmit();}});
$('#composer-input').addEventListener('input',event=>{event.target.style.height='auto';event.target.style.height=`${Math.min(event.target.scrollHeight,100)}px`;});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&panel&&!$('dialog[open]'))closePanel();});
$('.ticket-stage').append($('#side-panel'));
$$('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon);});

async function init() {
  try {
    const response=await fetch(`/api/state${sessionId?`?session_id=${encodeURIComponent(sessionId)}`:''}`);
    if(!response.ok)throw new Error('Could not load your session.');
    accept(await response.json());
  } catch(error) {
    $('#messages').innerHTML='<div class="message assistant"><p>Your concierge is offline.</p><p>Start the local server, then refresh this page.</p></div>';
    $('#suggestions').hidden=true;
    toast(error.message);
  }
}
init();
