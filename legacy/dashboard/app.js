const $ = (s) => document.querySelector(s);
const fmt = (n, digits = 2) => Number(n ?? 0).toLocaleString('zh-TW', {maximumFractionDigits: digits});
const time = (s) => s ? new Date(s).toLocaleString('zh-TW', {timeZone:'Asia/Taipei', hour12:false}) : '—';

function accountCard(a) {
  const s = a.snapshot || {}, active = s.active_position;
  return `<article class="card">
    <div class="card-head"><div><span class="eyebrow">${a.account_id || 'PAPER ACCOUNT'}</span><h2>${(a.strategy || 'unknown').toUpperCase()}</h2></div><span class="badge">${a.status || 'ok'}</span></div>
    <div class="decision">${a.decision || '—'}</div><p>${active ? `${active.type} @ ${fmt(active.entry_price)}` : '目前無持倉或等待委託'}</p>
    <div class="metrics"><div class="metric"><span>帳戶餘額</span><b>${fmt(s.balance)} USDT</b></div><div class="metric"><span>風險 / 槓桿</span><b>${fmt((a.risk_pct || 0)*100)}% / ${fmt(a.max_leverage,1)}×</b></div><div class="metric"><span>最後評估</span><b>${time(a.evaluated_at)}</b></div><div class="metric"><span>交易筆數</span><b>${(s.trades || []).length}</b></div><div class="metric"><span>訊號 / 結構週期</span><b>${a.market?.signal_timeframe || '—'} / ${a.market?.structure_timeframe || '—'}</b></div><div class="metric"><span>最新 K 棒</span><b>${s.as_of || '—'}</b></div></div>
  </article>`;
}

async function load() {
  $('#refresh').disabled = true; $('#summary').textContent = '正在更新…';
  try {
    const response = await fetch('/api/status'), data = await response.json();
    if (!data.ok) throw new Error(data.error || '讀取失敗');
    const accounts = data.accounts || [], timers = Object.entries(data.timers || {});
    $('#health').className = 'dot'; $('#summary').textContent = `${accounts.length} 個策略帳戶在線`;
    $('#updated').textContent = `瀏覽器更新：${new Date().toLocaleString('zh-TW', {hour12:false})}`;
    $('#accounts').innerHTML = accounts.length ? accounts.map(accountCard).join('') : $('#empty').innerHTML;
    $('#timers').innerHTML = timers.map(([name, t]) => { const ok=t.ActiveState==='active'; return `<div class="timer"><b>${name}</b><span class="${ok?'ok':'bad-text'}">${ok?'● 正常運行':'● '+(t.ActiveState||'未知')} · 下次 ${t.NextElapseUSecRealtime||'—'}</span></div>` }).join('');
  } catch (e) {
    $('#health').className = 'dot bad'; $('#summary').textContent = '無法連接 VPS'; $('#updated').textContent = e.message;
    $('#accounts').innerHTML = $('#empty').innerHTML; $('#timers').innerHTML = '';
  } finally { $('#refresh').disabled = false; }
}

$('#refresh').addEventListener('click', load);
setInterval(() => $('#clock').textContent = new Date().toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei',hour12:false}), 1000);
load();
