// app.js

let ppgChart = null;

// ---------- Generic HTTP helper ----------

async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return await resp.json();
}

// ---------- Backend health ----------

async function refreshHealthStatus() {
  const el = document.getElementById('health-status');
  try {
    const data = await fetchJson('/health');
    if (data.status === 'healthy') {
      el.textContent = `后端正常 (${data.timestamp})`;
      el.style.color = '#28a745';
    } else {
      el.textContent = '后端状态异常';
      el.style.color = '#dc3545';
    }
  } catch (err) {
    el.textContent = `健康检查失败: ${err.message}`;
    el.style.color = '#dc3545';
  }
}

// ---------- Realtime PPG chart ----------

async function initPpgChart() {
  const statusEl = document.getElementById('realtime-status');
  try {
    const data = await fetchJson('/api/recent?limit=200');
    if (!data.success) {
      throw new Error(data.message || data.error || 'API returned failure');
    }

    const irValues = data.data.ppg.ir || [];
    const labels = irValues.map((_, idx) => idx);

    const ctx = document.getElementById('ppgChart').getContext('2d');
    ppgChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'PPG IR',
          data: irValues,
          borderColor: 'rgba(220,53,69,1)',
          backgroundColor: 'rgba(220,53,69,0.15)',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.3
        }]
      },
      options: {
        responsive: true,
        animation: false,
        scales: {
          x: { display: false },
          y: { title: { display: true, text: 'IR Value' } }
        }
      }
    });

    statusEl.textContent = `已加载 ${irValues.length} 点`;
  } catch (err) {
    console.error(err);
    statusEl.textContent = `加载失败: ${err.message}`;
  }
}

async function refreshPpgChart() {
  if (!ppgChart) return;
  const statusEl = document.getElementById('realtime-status');

  try {
    const data = await fetchJson('/api/recent?limit=200');
    if (!data.success) {
      throw new Error(data.message || data.error || 'API returned failure');
    }
    const irValues = data.data.ppg.ir || [];
    const labels = irValues.map((_, idx) => idx);

    ppgChart.data.labels = labels;
    ppgChart.data.datasets[0].data = irValues;
    ppgChart.update();

    statusEl.textContent = `最近 ${irValues.length} 点 @ ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    console.error(err);
    statusEl.textContent = `更新失败: ${err.message}`;
  }
}

// ---------- Current status (ML output) ----------

function setStatusValue(id, text) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = text || '-';
  }
}

async function refreshCurrentStatus() {
  const infoEl = document.getElementById('status-info');
  try {
    const data = await fetchJson('/api/status/current');
    if (!data.success) {
      throw new Error(data.error || 'API returned failure');
    }
    const status = data.status;

    infoEl.textContent = `最近分析时间: ${status.timestamp}, 窗口大小: ${status.features?.window_size || '-'}`;

    setStatusValue('hr-level', status.heart_rate_level);
    setStatusValue('activity-state', status.activity_state);
    setStatusValue('sleep-state', status.sleep_state);
    setStatusValue('temp-status', status.temperature_status);
    setStatusValue('spo2-status', status.spo2_status);

  } catch (err) {
    console.error(err);
    infoEl.textContent = `获取状态失败: ${err.message}`;
  }
}

// ---------- LLM Report ----------

function renderRiskBadge(riskLevel, needMedical) {
  const badgeEl = document.getElementById('risk-badge');
  badgeEl.textContent = '';
  badgeEl.className = '';

  if (!riskLevel) return;

  let cls = 'badge ';
  if (riskLevel === 'low') {
    cls += 'badge-low';
  } else if (riskLevel === 'moderate') {
    cls += 'badge-moderate';
  } else {
    cls += 'badge-high';
  }

  badgeEl.className = cls;
  badgeEl.textContent = `风险: ${riskLevel}${needMedical ? ' (建议关注)' : ''}`;
}

async function generateReport() {
  const btn = document.getElementById('generate-report-btn');
  const statusEl = document.getElementById('report-status');
  const cardEl = document.getElementById('report-card');

  btn.disabled = true;
  statusEl.textContent = '正在生成报告，请稍候...';

  try {
    const data = await fetchJson('/api/report/manual', { method: 'POST' });

    if (!data.success) {
      throw new Error(data.error || 'API returned failure');
    }

    const report = data.report || {};
    const parsed = report.llm_parsed || null;

    if (!parsed) {
      statusEl.textContent = 'LLM 返回格式不合法，无法解析为 JSON。';
      cardEl.style.display = 'none';
      return;
    }

    document.getElementById('report-summary').textContent = parsed.summary || '';

    const listEl = document.getElementById('report-immediate-advice');
    listEl.innerHTML = '';
    (parsed.immediate_advice || []).forEach((item) => {
      const li = document.createElement('li');
      li.textContent = item;
      listEl.appendChild(li);
    });

    document.getElementById('report-trend').textContent = parsed.trend_analysis || '';
    document.getElementById('report-notes').textContent = parsed.notes || '';

    renderRiskBadge(parsed.risk_level, parsed.need_medical_attention);

    cardEl.style.display = 'block';
    statusEl.textContent = `报告生成完成 (history_size=${report.history_size})`;

  } catch (err) {
    console.error(err);
    statusEl.textContent = `生成失败: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

// ---------- Tabs ----------

function initTabs() {
  const buttons = document.querySelectorAll('.tab-button');
  const contents = {
    realtime: document.getElementById('tab-realtime'),
    status: document.getElementById('tab-status'),
    report: document.getElementById('tab-report'),
  };

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const tab = btn.getAttribute('data-tab');

      buttons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');

      Object.keys(contents).forEach((key) => {
        contents[key].classList.toggle('active', key === tab);
      });
    });
  });
}

// ---------- Main ----------

document.addEventListener('DOMContentLoaded', async () => {
  initTabs();
  await refreshHealthStatus();
  await initPpgChart();
  await refreshCurrentStatus();

  // Periodic refresh
  setInterval(refreshHealthStatus, 10000);
  setInterval(refreshPpgChart, 3000);
  setInterval(refreshCurrentStatus, 5000);

  // Report button
  const btn = document.getElementById('generate-report-btn');
  btn.addEventListener('click', generateReport);
});
