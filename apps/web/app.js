const state = { batches: { left: null, right: null }, run: null, exceptions: [], report: null };
const $ = (id) => document.getElementById(id);
const base = () => $('baseUrl').value.replace(/\/$/, '');
const token = () => $('token').value.trim();
const show = (text, kind = 'success') => { const el = $('message'); el.textContent = text; el.className = `message show ${kind}`; };
const clearMessage = () => { $('message').className = 'message'; $('message').textContent = ''; };
const setStatus = (id, text, kind = '') => { const el = $(id); el.textContent = text; el.className = `status ${kind}`; };
function key() { return `${Date.now()}-${crypto.randomUUID()}`.slice(0, 64); }
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
function text(tag, value, className = '') { const el = document.createElement(tag); el.textContent = String(value); if (className) el.className = className; return el; }
function formatInteger(value) {
  if (typeof value === 'number' && !Number.isSafeInteger(value)) throw new Error('UNSAFE_INTEGER');
  const raw = BigInt(String(value));
  const sign = raw < 0n ? '-' : '';
  const digits = (raw < 0n ? -raw : raw).toString();
  return `${sign}${digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`;
}
function appendMetric(container, label, value) {
  const metric = text('div', '', 'metric');
  metric.append(text('small', label), text('strong', formatInteger(value)));
  container.append(metric);
}
function parseApiJson(source) {
  return JSON.parse(source, (key, value, context) => {
    if (typeof value !== 'number') return value;
    if (!Number.isFinite(value)) throw new Error('NON_FINITE_JSON_NUMBER');
    if (Number.isSafeInteger(value) || !Number.isInteger(value)) return value;
    // The original token must be used before any rounded Number conversion.
    if (!context || !/^-?(0|[1-9]\d*)$/.test(context.source)) throw new Error('UNSAFE_JSON_NUMBER');
    return context.source;
  });
}
async function api(path, options = {}) {
  const headers = { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(token() ? { Authorization: `Bearer ${token()}` } : {}), ...(options.headers || {}) };
  const response = await fetch(`${base()}${path}`, { ...options, headers });
  let body;
  try { body = parseApiJson(await response.text()); }
  catch (error) { if (response.ok) throw error; body = {}; }
  if (!response.ok) { const error = new Error(body.detail || body.title || `HTTP ${response.status}`); error.code = body.code || ''; error.status = response.status; throw error; }
  return body;
}
function errorMessage(error) { const stale = error.code === 'STALE_VERSION' || error.status === 409 && /stale/i.test(error.message); show(`${error.code || 'REQUEST_FAILED'}: ${error.message}. Refresh the current resource before retrying.`, stale ? 'warn' : 'error'); }
function renderBatches() {
  const list = $('batchList'); clear(list);
  const batches = Object.entries(state.batches).filter(([, batch]) => batch);
  if (!batches.length) { list.append(text('p', 'No batches registered in this session.', 'empty')); return; }
  for (const [side, batch] of batches) {
    const entity = text('div', '', 'entity');
    const details = text('span', ''); details.append(text('strong', side.toUpperCase()), text('span', ` · ${batch.source_label} · ${formatInteger(batch.row_count)} rows · ${batch.currency}`));
    entity.append(details, text('code', batch.id)); list.append(entity);
  }
}
function renderMetrics(totals) {
  if (!totals) return;
  const summary = $('rowSummary'); clear(summary);
  [['Left total (minor)', totals.left_total_minor], ['Right total (minor)', totals.right_total_minor], ['Allocated (minor)', totals.allocated_total_minor], ['Source imbalance (minor)', totals.source_unbalanced_minor], ['Conservation discrepancy (minor)', totals.conservation_discrepancy_minor], ['Open exceptions', totals.open_exception_count]].forEach(([label, value]) => appendMetric(summary, label, value));
}
function renderRowTotals(totals) {
  const summary = $('rowSummary'); clear(summary);
  Object.entries(totals).forEach(([label, value]) => appendMetric(summary, label.replaceAll('_', ' '), value));
}
async function loadRows() {
  try {
    const rows = await Promise.all(['left', 'right'].map(async (side) => state.batches[side] ? [side, await api(`/v1/import-batches/${state.batches[side].id}/rows`)] : [side, null]));
    const totals = rows.reduce((acc, [side, page]) => { if (page) { acc[`${side}_total_minor`] = page.items.reduce((sum, row) => sum + BigInt(String(row.amount_minor)), 0n); acc[`${side}_row_count`] = page.items.length; } return acc; }, {});
    renderRowTotals(totals); show('Rows loaded. Amounts remain integer minor units; no decimal conversion is performed.');
  } catch (error) { errorMessage(error); }
}
async function loadExceptions() {
  if (!state.run) return;
  try {
    const page = await api(`/v1/reconciliation-runs/${state.run.id}/exceptions`); state.exceptions = page.items;
    const list = $('exceptionList'); clear(list);
    if (!state.exceptions.length) { list.append(text('p', 'No exceptions. This run can be finalized if conservation passes.', 'empty')); }
    for (const item of state.exceptions) {
      const exception = text('div', '', 'exception'); const heading = text('strong', `${item.reason_code} · ${item.status} · version ${item.version}`); const id = text('code', item.id); const button = text('button', 'Use this exception', 'secondary select-exception');
      button.type = 'button'; button.dataset.id = item.id; button.dataset.version = String(item.version); button.onclick = () => { $('exceptionId').value = button.dataset.id; $('exceptionVersion').value = button.dataset.version; };
      exception.append(heading, text('br', ''), id, button); list.append(exception);
    }
    show(`${state.exceptions.length} exception(s) loaded.`);
  } catch (error) { errorMessage(error); }
}
$('healthButton').onclick = async () => { try { const health = await api('/healthz'); setStatus('health', health.status, 'ok'); show('API is reachable.'); } catch (error) { setStatus('health', 'Unavailable', 'error'); errorMessage(error); } };
$('importForm').onsubmit = async (event) => { event.preventDefault(); clearMessage(); const csv = $('csvContent').value.trim(); const body = { source_label: $('sourceLabel').value, artifact_id: $('artifactId').value, file_sha256: $('fileSha').value, currency: $('currency').value.toUpperCase(), profile_version: $('profileVersion').value, ...(csv ? { csv_content: csv } : {}) }; try { const batch = await api('/v1/import-batches', { method: 'POST', headers: { 'Idempotency-Key': key() }, body: JSON.stringify(body) }); const side = $('importSide').value; state.batches[side] = batch; $(`${side}BatchId`).value = batch.id; $('rowsButton').disabled = false; $('exceptionsButton').disabled = !state.run; renderBatches(); show(`${side} import accepted with ${formatInteger(batch.row_count)} rows.`); } catch (error) { errorMessage(error); } };
$('rowsButton').onclick = loadRows;
$('reconcileForm').onsubmit = async (event) => { event.preventDefault(); try { state.run = await api('/v1/reconciliation-runs', { method: 'POST', headers: { 'Idempotency-Key': key() }, body: JSON.stringify({ left_batch_id: $('leftBatchId').value, right_batch_id: $('rightBatchId').value, rule_version: $('ruleVersion').value }) }); setStatus('runStatus', `${state.run.status} · ${formatInteger(state.run.unmatched_count)} unmatched`, 'ok'); $('runVersion').value = state.run.version; $('exceptionsButton').disabled = false; show(`Reconciliation accepted. ${formatInteger(state.run.unmatched_count)} exception(s) require review.`); } catch (error) { errorMessage(error); } };
$('exceptionsButton').onclick = loadExceptions;
$('resolveForm').onsubmit = async (event) => { event.preventDefault(); try { await api(`/v1/exceptions/${$('exceptionId').value}/resolutions`, { method: 'POST', body: JSON.stringify({ decision: $('decision').value, evidence_sha256: $('evidenceSha').value, expected_version: Number($('exceptionVersion').value) }) }); show('Resolution recorded. Reload exceptions before finalizing.'); await loadExceptions(); } catch (error) { errorMessage(error); } };
$('finalizeForm').onsubmit = async (event) => { event.preventDefault(); if (!state.run) { show('Start a reconciliation run first.', 'warn'); return; } try { state.report = await api(`/v1/reconciliation-runs/${state.run.id}/finalize`, { method: 'POST', body: JSON.stringify({ expected_version: Number($('runVersion').value), approved_summary_sha256: $('summarySha').value }) }); renderMetrics(state.report.totals); const reportBox = $('reportBox'); clear(reportBox); reportBox.append(text('strong', 'Report finalized'), text('br', ''), text('code', state.report.id), text('br', ''), text('span', `Ledger ${state.report.ledger_sha256}`)); show('Immutable report finalized. Fetching report download metadata...'); const download = await api(`/v1/reports/${state.report.id}/download`); renderMetrics(download.totals); reportBox.append(text('br', ''), text('span', `Download capability expires ${download.expires_at}; no file or transfer is created by this console.`)); } catch (error) { errorMessage(error); } };
renderBatches();

const reportDownloadButton=text('button','Unduh laporan terverifikasi','secondary');reportDownloadButton.type='button';$('reportBox').after(reportDownloadButton);
reportDownloadButton.onclick=async()=>{try{if(!state.report)throw new Error('Finalisasi laporan terlebih dahulu.');const metadata=await api(`/v1/reports/${state.report.id}/download`);const url=new URL(metadata.download_url,base()||location.origin);if(url.origin!==new URL(base()||location.origin).origin||!url.pathname.startsWith('/v1/report-transfers/'))throw new Error('Alamat unduh tidak valid.');const response=await fetch(url,{cache:'no-store',referrerPolicy:'no-referrer'});if(!response.ok)throw new Error('Unduhan ditolak ('+response.status+').');const bytes=await response.arrayBuffer();const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');if(digest!==state.report.artifact_sha256)throw new Error('Integritas laporan gagal.');const blob=URL.createObjectURL(new Blob([bytes],{type:'application/json'}));const link=document.createElement('a');link.href=blob;link.download='reconciliation-'+state.report.id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(blob),1000);show('Laporan diunduh dan digest terverifikasi.');}catch(error){errorMessage(error);}};
window.addEventListener('forge-session-cleared',()=>{state.batches={left:null,right:null};state.run=null;state.exceptions=[];state.report=null;renderBatches();clear($('reportBox'));clear($('exceptionList'));clear($('rowSummary'));});
