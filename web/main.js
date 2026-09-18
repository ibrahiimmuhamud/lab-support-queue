'use strict';
const $ = id => document.getElementById(id);
let tickets = [], token = '', filter = 'all', busy = false, noticeTimer;
const statusNames = {waiting: 'Waiting', active: 'In progress', resolved: 'Resolved'};
const priorities = {1: 'High', 2: 'Normal', 3: 'Low'};
const dialog = $('ticket-dialog');
document.addEventListener('keydown', () => document.body.classList.add('keyboard'));
document.addEventListener('pointerdown', () => document.body.classList.remove('keyboard'));

function notice(message) {
  clearTimeout(noticeTimer);
  $('notice').textContent = message;
  noticeTimer = setTimeout(() => { $('notice').textContent = ''; }, 6000);
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function render() {
  for (const status of Object.keys(statusNames)) $(''+status+'-count').textContent = tickets.filter(t => t.status === status).length;
  $('nav-count').textContent = tickets.length;
  const waiting = tickets.filter(t => t.status === 'waiting').sort((a,b) => a.priority-b.priority || a.id-b.id);
  $('next-title').textContent = waiting[0]?.title || 'No waiting tickets';
  $('start-next').disabled = busy || !waiting.length || !token;
  $('new-ticket').disabled = busy || !token;
  $('submit-ticket').disabled = busy;
  $('refresh').disabled = busy;
  const query = $('search').value.toLowerCase().trim();
  const shown = tickets.filter(t => (filter === 'all' || t.status === filter) && (t.title.toLowerCase().includes(query) || String(t.id).includes(query)));
  $('queue-heading').textContent = filter === 'all' ? 'All tickets' : statusNames[filter];
  $('result-count').textContent = `${shown.length} ticket${shown.length === 1 ? '' : 's'}`;
  $('tickets').replaceChildren();
  for (const ticket of shown) {
    const row = element('tr');
    const title = element('td');
    title.append(element('span', `LAB-${String(ticket.id).padStart(3, '0')}`, 'ticket-id'), element('span', ticket.title, 'ticket-title'));
    const priority = element('td');
    priority.append(element('span', priorities[ticket.priority], `badge priority-${ticket.priority}`));
    const status = element('td'), badge = element('span', undefined, 'status-badge');
    badge.append(element('i', undefined, `status-dot ${ticket.status}`), document.createTextNode(statusNames[ticket.status]));
    status.append(badge);
    const date = element('td', new Date(ticket.created_at).toLocaleDateString(undefined,{month:'short',day:'numeric'}));
    date.title = new Date(ticket.created_at).toLocaleString();
    const action = element('td');
    if (ticket.status === 'active') {
      const button = element('button', '✓ Resolve', 'resolve');
      button.setAttribute('aria-label', `Resolve ticket ${ticket.id}: ${ticket.title}`);
      button.disabled = busy;
      button.addEventListener('click', () => mutate('/api/resolve', {id:ticket.id}, `Ticket #${ticket.id} resolved.`));
      action.append(button);
    } else if (ticket.status === 'resolved') action.append(element('span', '✓ Done'));
    row.append(title,priority,status,date,action);
    $('tickets').append(row);
  }
  $('empty').hidden = shown.length !== 0;
  $('empty').querySelector('h3').textContent = query ? 'No matching tickets' : 'No tickets here yet';
  $('empty').querySelector('p').textContent = query ? 'Try another title or ticket number.' : filter === 'all' ? 'Add your first issue to get things moving.' : 'Choose another status to see the rest of your queue.';
  document.querySelectorAll('[data-filter]').forEach(button => {
    button.classList.toggle('selected', button.dataset.filter === filter);
    button.setAttribute('aria-pressed', String(button.dataset.filter === filter));
  });
}
async function load() {
  const response = await fetch('/api/tickets');
  if (!response.ok) throw new Error('Could not load your queue. Check that the server is running, then refresh.');
  const data = await response.json();
  tickets = data.tickets;
  token = data.token;
  render();
}
async function mutate(path, payload, message) {
  if (busy) return;
  busy = true; render(); $('form-error').textContent = '';
  try {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Queue-Token':token}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Something went wrong. Please try again.');
    if (path === '/api/tickets') { dialog.close(); $('ticket-form').reset(); }
    if (path === '/api/start-next') filter = 'active';
    try { await load(); notice(message); }
    catch { token = ''; notice('Change saved, but the list could not refresh. Use Refresh before making another change.'); }
  } catch (error) {
    const message = error instanceof TypeError ? 'Connection lost. Refresh to check whether your change was saved before retrying.' : error.message;
    if (dialog.open) $('form-error').textContent = message;
    else notice(message);
  } finally {busy = false; render();}
}
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {filter=button.dataset.filter;render();}));
$('search').addEventListener('input',render);
$('new-ticket').addEventListener('click', () => {$('form-error').textContent='';dialog.showModal();$('title').focus();});
document.querySelectorAll('.close').forEach(button => button.addEventListener('click', () => dialog.close()));
$('ticket-form').addEventListener('submit', event => {event.preventDefault();mutate('/api/tickets',{title:$('title').value,priority:Number($('priority').value)},'Ticket created.');});
$('start-next').addEventListener('click', () => mutate('/api/start-next',{},'Next ticket started. Find it under In progress.'));
$('refresh').addEventListener('click', async () => {try {await load();notice('Queue refreshed.');} catch(error){notice(error.message);}});
$('new-ticket').disabled = true;
load().catch(error => {$('next-title').textContent='Unable to connect to your queue';$('result-count').textContent='Offline';notice(error.message);});
