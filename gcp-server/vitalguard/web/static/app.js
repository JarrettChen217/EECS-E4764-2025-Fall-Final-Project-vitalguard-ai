const translations = {
  en: {
    static: {
      appName: 'VitalGuard AI',
      languageLabel: 'Language',
      dataVisualizationTitle: 'Data Visualization',
      currentStatusTitle: 'Current Status',
      aiReportTitle: 'AI Report',
      sensorHeartRate: 'Heart Rate',
      sensorSpO2: 'SpO₂',
      sensorTemperature: 'Temperature',
      sensorRed: 'PPG · RED',
      sensorIr: 'PPG · IR',
      tempUnitLabel: 'Temperature Unit',
      reportSummaryTitle: 'Report Summary',
      immediateAdviceTitle: 'Immediate Advice',
      trendAnalysisTitle: 'Trend Analysis',
      notesTitle: 'Notes',
      hrLabel: 'Heart Rate Level',
      activityLabel: 'Activity State',
      sleepLabel: 'Sleep State',
      spo2Label: 'SpO₂ Status',
      tempLabel: 'Temperature Status',
      reportButton: 'Generate Latest Report'
    },
    dynamic: {
      healthChecking: () => 'Checking backend status...',
      healthOk: ({ timestamp }) => `Backend: healthy · ${timestamp}`,
      healthDegraded: ({ timestamp }) => `Backend issue · ${timestamp}`,
      healthError: ({ message }) => `Health check failed: ${message}`,
      realtimeLoading: () => 'Loading...',
      realtimeSamples: ({ count, time }) => `Samples ${count} · ${time}`,
      realtimeError: ({ message }) => `Load failed: ${message}`,
      statusInfo: ({ windowSize, timestamp }) => `Window ${windowSize} · ${timestamp}`,
      statusPlaceholder: () => 'Awaiting latest analysis...',
      statusError: ({ message }) => `Status failed: ${message}`,
      reportHint: () => 'Tap the button to generate a report.',
      reportLoading: () => 'Generating report...',
      reportSuccess: ({ historySize }) => `Report ready · history ${historySize}`,
      reportFailure: ({ message }) => `Failed: ${message}`,
      reportNoJson: () => 'LLM JSON parsing failed.',
      toastHealthFail: ({ message }) => `Health check failed: ${message}`,
      toastRecentFail: ({ message }) => `Realtime data failed: ${message}`,
      toastStatusFail: ({ message }) => `Status fetch failed: ${message}`,
      toastReportFail: ({ message }) => `Report failed: ${message}`,
      riskLabel: ({ level, needMedical }) => {
        const map = { low: 'Low risk', moderate: 'Moderate risk', high: 'High risk' };
        const base = map[level] || level;
        return needMedical ? `${base} · Attention recommended` : base;
      }
    }
  },
  zh: {
    static: {
      appName: 'VitalGuard AI',
      languageLabel: '语言',
      dataVisualizationTitle: '数据可视化',
      currentStatusTitle: '当前状态',
      aiReportTitle: 'AI 报告',
      sensorHeartRate: '心率',
      sensorSpO2: '血氧',
      sensorTemperature: '体温',
      sensorRed: 'PPG · RED',
      sensorIr: 'PPG · IR',
      tempUnitLabel: '体温单位',
      reportSummaryTitle: '报告概要',
      immediateAdviceTitle: '即时建议',
      trendAnalysisTitle: '趋势分析',
      notesTitle: '备注',
      hrLabel: '心率等级',
      activityLabel: '活动状态',
      sleepLabel: '睡眠状态',
      spo2Label: 'SpO₂ 状态',
      tempLabel: '体温状态',
      reportButton: '生成最新报告'
    },
    dynamic: {
      healthChecking: () => '正在检查后端状态...',
      healthOk: ({ timestamp }) => `后端正常 · ${timestamp}`,
      healthDegraded: ({ timestamp }) => `后端异常 · ${timestamp}`,
      healthError: ({ message }) => `健康检查失败：${message}`,
      realtimeLoading: () => '加载中...',
      realtimeSamples: ({ count, time }) => `样本 ${count} 点 · ${time}`,
      realtimeError: ({ message }) => `加载失败：${message}`,
      statusInfo: ({ windowSize, timestamp }) => `窗口 ${windowSize} · ${timestamp}`,
      statusPlaceholder: () => '等待最新分析...',
      statusError: ({ message }) => `状态获取失败：${message}`,
      reportHint: () => '点击按钮生成报告。',
      reportLoading: () => '报告生成中...',
      reportSuccess: ({ historySize }) => `报告完成 · history ${historySize}`,
      reportFailure: ({ message }) => `生成失败：${message}`,
      reportNoJson: () => 'LLM JSON 解析失败。',
      toastHealthFail: ({ message }) => `健康检查失败：${message}`,
      toastRecentFail: ({ message }) => `实时数据获取失败：${message}`,
      toastStatusFail: ({ message }) => `状态获取失败：${message}`,
      toastReportFail: ({ message }) => `报告生成失败：${message}`,
      riskLabel: ({ level, needMedical }) => {
        const map = { low: '低风险', moderate: '中等风险', high: '高风险' };
        let text = map[level] || level;
        if (needMedical) text += ' · 建议关注';
        return text;
      }
    }
  }
};

class EventBus {
  constructor() { this.listeners = new Map(); }
  subscribe(event, handler) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event).add(handler);
    return () => this.listeners.get(event).delete(handler);
  }
  publish(event, payload) {
    if (!this.listeners.has(event)) return;
    this.listeners.get(event).forEach((handler) => handler(payload));
  }
}
const bus = new EventBus();

class I18nService {
  constructor(table) {
    this.table = table;
    this.lang = 'en';
  }
  init() {
    const saved = localStorage.getItem('vg_language');
    const initial = saved && this.table[saved] ? saved : this.lang;
    this.setLanguage(initial, { silent: true });
    const select = document.getElementById('language-select');
    if (select) {
      select.value = initial;
      select.addEventListener('change', (event) => this.setLanguage(event.target.value));
    }
    const healthEl = document.getElementById('health-status');
    if (healthEl) healthEl.textContent = this.dynamic('healthChecking');
    const realtimeEl = document.getElementById('realtime-status');
    if (realtimeEl) realtimeEl.textContent = this.dynamic('realtimeLoading');
  }
  setLanguage(lang, { silent = false } = {}) {
    if (!this.table[lang]) return;
    this.lang = lang;
    localStorage.setItem('vg_language', lang);
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    this.applyStaticTexts();
    if (!silent) bus.publish('languageChanged', lang);
  }
  applyStaticTexts() {
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      const key = el.dataset.i18n;
      const text = this.t(key);
      if (typeof text === 'string') el.textContent = text;
    });
  }
  t(key) {
    return this.table[this.lang].static[key] || this.table.en.static[key] || key;
  }
  dynamic(key, params = {}) {
    const entry = this.table[this.lang].dynamic[key] || this.table.en.dynamic[key];
    return typeof entry === 'function' ? entry(params) : entry || key;
  }
  get locale() {
    return this.lang === 'zh' ? 'zh-CN' : 'en-US';
  }
}
const i18n = new I18nService(translations);

const DataService = (() => {
  const controllers = new Map();
  async function request(key, path, options = {}) {
    const previous = controllers.get(key);
    if (previous) previous.abort();
    const controller = new AbortController();
    controllers.set(key, controller);
    const config = { ...options, signal: controller.signal };
    try {
      const response = await fetch(path, config);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      if (controllers.get(key) === controller) controllers.delete(key);
    }
  }
  return {
    getHealth: () => request('health', '/health'),
    getRecent: () => request('recent', '/api/recent?limit=200'),
    getStatus: () => request('status', '/api/status/current'),
    postReport: () => request('report', '/api/report/manual', { method: 'POST' })
  };
})();
const isAbortError = (error) => error && error.name === 'AbortError';

const Toast = (() => {
  const container = document.getElementById('toast-container');
  function show(message) {
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }
  return { show };
})();

class TemperatureUnitToggle {
  constructor() {
    this.container = document.getElementById('temp-unit-toggle');
    this.buttons = document.querySelectorAll('.unit-btn');
    this.unit = localStorage.getItem('vg_temp_unit') || 'fahrenheit';
  }
  init() {
    this.syncUI();
    this.buttons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const unit = btn.dataset.unit;
        if (unit && unit !== this.unit) {
          this.unit = unit;
          localStorage.setItem('vg_temp_unit', unit);
          this.syncUI();
          bus.publish('temperatureUnitChanged', this.unit);
        }
      });
    });
    bus.publish('temperatureUnitChanged', this.unit);
  }
  syncUI() {
    this.buttons.forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.unit === this.unit);
    });
  }
  setActiveState(isActive) {
    if (!this.container) return;
    this.container.classList.toggle('active', isActive);
  }
  get currentUnit() {
    return this.unit;
  }
}

class ChartCarousel {
  constructor(canvasId, buttonSelector, tempUnitToggle) {
    this.canvas = document.getElementById(canvasId);
    this.buttons = document.querySelectorAll(buttonSelector);
    this.tempUnitToggle = tempUnitToggle;
    this.currentIndex = 0;
    this.lastPayload = null;
    this.realtimeStatusEl = document.getElementById('realtime-status');
    this.chart = null;
    this.temperatureUnit = tempUnitToggle?.currentUnit || 'fahrenheit';
    this.sensors = [
      {
        key: 'heartrate',
        labelKey: 'sensorHeartRate',
        accessor: (d) => d.data.ppg?.heartrate || [],
        color: '#fb7185',
        background: 'rgba(251,113,133,0.2)'
      },
      {
        key: 'spo2',
        labelKey: 'sensorSpO2',
        accessor: (d) => d.data.ppg?.spo2 || [],
        color: '#22d3ee',
        background: 'rgba(34,211,238,0.18)'
      },
      {
        key: 'temperature',
        labelKey: 'sensorTemperature',
        accessor: (d) => d.data.temperature || [],
        color: '#facc15',
        background: 'rgba(250,204,21,0.25)'
      },
      {
        key: 'ppg_red',
        labelKey: 'sensorRed',
        accessor: (d) => d.data.ppg?.red || [],
        color: '#f87171',
        background: 'rgba(248,113,113,0.18)'
      },
      {
        key: 'ppg_ir',
        labelKey: 'sensorIr',
        accessor: (d) => d.data.ppg?.ir || [],
        color: '#c084fc',
        background: 'rgba(192,132,252,0.18)'
      }
    ];
  }
  init() {
    if (!this.canvas) return;
    const ctx = this.canvas.getContext('2d');
    this.chart = new Chart(ctx, {
      type: 'line',
      data: { labels: [], datasets: [{ data: [], borderWidth: 2, pointRadius: 0, tension: 0.35 }] },
      options: {
        responsive: true,
        animation: false,
        interaction: { mode: 'index', intersect: false, axis: 'x' },
        plugins: {
          legend: { display: false },
          tooltip: {
            intersect: false,
            mode: 'index',
            callbacks: {
              label: (context) => this.formatTooltipValue(this.currentSensorKey(), context.parsed.y)
            }
          }
        },
        scales: {
          x: { display: false },
          y: { ticks: { color: '#cbd5f5' } }
        }
      }
    });
    if (this.realtimeStatusEl) {
      this.realtimeStatusEl.textContent = i18n.dynamic('realtimeLoading');
    }
    this.bindButtons();
    bus.subscribe('recentData', (payload) => this.consume(payload));
    bus.subscribe('languageChanged', () => this.handleLanguageChange());
    bus.subscribe('temperatureUnitChanged', (unit) => this.handleTemperatureUnitChange(unit));
  }
  currentSensorKey() {
    return this.sensors[this.currentIndex]?.key;
  }
  bindButtons() {
    this.buttons.forEach((btn, idx) => {
      btn.addEventListener('click', () => {
        this.currentIndex = idx;
        this.buttons.forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        if (this.lastPayload) this.consume(this.lastPayload);
      });
    });
  }
  handleLanguageChange() {
    if (this.lastPayload) {
      this.consume(this.lastPayload);
    } else if (this.realtimeStatusEl) {
      this.realtimeStatusEl.textContent = i18n.dynamic('realtimeLoading');
    }
  }
  handleTemperatureUnitChange(unit) {
    this.temperatureUnit = unit;
    if (this.currentSensorKey() === 'temperature' && this.lastPayload) {
      this.consume(this.lastPayload);
    }
  }
  consume(payload) {
    if (!payload || !this.chart) return;
    this.lastPayload = payload;
    const sensor = this.sensors[this.currentIndex];
    if (!sensor) return;
    const seriesResult = this.prepareSeries(sensor, payload);
    const data = seriesResult.data || [];
    this.chart.data.labels = data.map((_, i) => i);
    this.chart.data.datasets[0].data = data;
    this.chart.data.datasets[0].label = i18n.t(sensor.labelKey);
    this.chart.data.datasets[0].borderColor = sensor.color;
    this.chart.data.datasets[0].backgroundColor = sensor.background;
    if (seriesResult.bounds) {
      this.chart.options.scales.y.min = seriesResult.bounds.min;
      this.chart.options.scales.y.max = seriesResult.bounds.max;
    } else {
      this.chart.options.scales.y.min = undefined;
      this.chart.options.scales.y.max = undefined;
    }
    this.chart.options.plugins.tooltip.callbacks = {
      label: (context) => this.formatTooltipValue(sensor.key, context.parsed.y)
    };
    this.chart.update();
    if (this.realtimeStatusEl) {
      this.realtimeStatusEl.textContent = i18n.dynamic('realtimeSamples', {
        count: data.length,
        time: new Date().toLocaleTimeString(i18n.locale)
      });
    }
    this.tempUnitToggle?.setActiveState(sensor.key === 'temperature');
  }
  prepareSeries(sensor, payload) {
    const raw = sensor.accessor(payload) || [];
    if (sensor.key !== 'temperature') {
      return { data: raw };
    }
    const converted = raw
      .map((value) => {
        if (typeof value !== 'number') return null;
        return this.temperatureUnit === 'fahrenheit' ? ((value * 9) / 5) + 32 : value;
      })
      .filter((value) => typeof value === 'number' && Number.isFinite(value));
    if (!converted.length) {
      return { data: [] };
    }
    let min = Math.min(...converted);
    let max = Math.max(...converted);
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      return { data: converted };
    }
    if (max - min < 10) {
      const pad = (10 - (max - min)) / 2;
      min -= pad;
      max += pad;
    }
    return { data: converted, bounds: { min, max } };
  }
  formatTooltipValue(sensorKey, value) {
    const label = this.chart?.data?.datasets[0]?.label || '';
    if (value === null || value === undefined || Number.isNaN(value)) {
      return label;
    }
    switch (sensorKey) {
      case 'heartrate':
        return `${label}: ${Math.round(value)} bpm`;
      case 'spo2':
        return `${label}: ${value.toFixed(1)}%`;
      case 'temperature': {
        const unitSymbol = this.temperatureUnit === 'fahrenheit' ? '°F' : '°C';
        return `${label}: ${value.toFixed(1)} ${unitSymbol}`;
      }
      default:
        return `${label}: ${value.toFixed(0)}`;
    }
  }
}

class StatusPanel {
  constructor() {
    this.infoEl = document.getElementById('status-info');
    this.lastStatus = null;
    if (this.infoEl) this.infoEl.textContent = i18n.dynamic('statusPlaceholder');
    bus.subscribe('currentStatus', (status) => {
      this.lastStatus = status;
      this.render(status);
    });
    bus.subscribe('statusError', ({ message }) => {
      if (this.infoEl) this.infoEl.textContent = i18n.dynamic('statusError', { message });
    });
    bus.subscribe('languageChanged', () => this.render(this.lastStatus));
  }
  render(status) {
    if (!this.infoEl) return;
    if (!status) {
      this.infoEl.textContent = i18n.dynamic('statusPlaceholder');
      return;
    }
    const windowSize = status.features?.window_size ?? '-';
    const timestamp = status.timestamp ?? '--';
    this.infoEl.textContent = i18n.dynamic('statusInfo', { windowSize, timestamp });
    this.setStatusValue('hr-level', status.heart_rate_level);
    this.setStatusValue('activity-state', status.activity_state);
    this.setStatusValue('sleep-state', status.sleep_state);
    this.setStatusValue('spo2-status', status.spo2_status);
    this.setStatusValue('temp-status', status.temperature_status);
  }
  setStatusValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value || '-';
  }
}

class ReportPanel {
  constructor() {
    this.button = document.getElementById('generate-report-btn');
    this.statusEl = document.getElementById('report-status');
    this.card = document.getElementById('report-card');
    this.state = { type: 'idle' };
    if (this.button) {
      this.button.addEventListener('click', () => this.generate());
    }
    bus.subscribe('languageChanged', () => this.updateStatusText());
    this.updateStatusText();
  }
  setState(state) {
    this.state = state;
    this.updateStatusText();
  }
  updateStatusText() {
    if (!this.statusEl) return;
    const { type, historySize, message } = this.state;
    if (type === 'loading') {
      this.statusEl.textContent = i18n.dynamic('reportLoading');
    } else if (type === 'success') {
      this.statusEl.textContent = i18n.dynamic('reportSuccess', { historySize });
    } else if (type === 'error') {
      this.statusEl.textContent = i18n.dynamic('reportFailure', { message });
    } else {
      this.statusEl.textContent = i18n.dynamic('reportHint');
    }
  }
  setLoading(isLoading) {
    if (this.button) this.button.disabled = isLoading;
  }
  renderRisk(level, needMedical) {
    const badge = document.getElementById('risk-badge');
    if (!badge) return;
    badge.className = '';
    badge.textContent = '';
    if (!level) return;
    let cls = 'badge ';
    if (level === 'low') cls += 'badge-low';
    else if (level === 'moderate') cls += 'badge-moderate';
    else cls += 'badge-high';
    badge.className = cls;
    badge.textContent = i18n.dynamic('riskLabel', { level, needMedical });
  }
  populate(parsed) {
    document.getElementById('report-summary').textContent = parsed.summary || '';
    const list = document.getElementById('report-immediate-advice');
    list.innerHTML = '';
    (parsed.immediate_advice || []).forEach((item) => {
      const li = document.createElement('li');
      li.textContent = item;
      list.appendChild(li);
    });
    document.getElementById('report-trend').textContent = parsed.trend_analysis || '';
    document.getElementById('report-notes').textContent = parsed.notes || '';
  }
  async generate() {
    this.setLoading(true);
    this.setState({ type: 'loading' });
    try {
      const payload = await DataService.postReport();
      if (!payload.success) throw new Error(payload.error || 'API failure');
      const parsed = payload.report?.llm_parsed;
      if (!parsed) throw new Error(i18n.dynamic('reportNoJson'));
      this.populate(parsed);
      this.renderRisk(parsed.risk_level, parsed.need_medical_attention);
      if (this.card) this.card.style.display = 'block';
      this.setState({ type: 'success', historySize: payload.report.history_size });
    } catch (error) {
      if (isAbortError(error)) return;
      Toast.show(i18n.dynamic('toastReportFail', { message: error.message }));
      if (this.card) this.card.style.display = 'none';
      this.setState({ type: 'error', message: error.message });
    } finally {
      this.setLoading(false);
    }
  }
}

class DataPoller {
  constructor() {
    this.timers = [];
    this.running = false;
    this.healthEl = document.getElementById('health-status');
    this.lastHealth = null;
    bus.subscribe('languageChanged', () => this.renderHealth());
  }
  start() {
    if (this.running) return;
    this.running = true;
    this.pollHealth();
    this.pollRecent();
    this.pollStatus();
    this.timers.push(setInterval(() => this.pollHealth(), 10000));
    this.timers.push(setInterval(() => this.pollRecent(), 4000));
    this.timers.push(setInterval(() => this.pollStatus(), 6000));
  }
  stop() {
    if (!this.running) return;
    this.timers.forEach((id) => clearInterval(id));
    this.timers = [];
    this.running = false;
  }
  renderHealth() {
    if (!this.healthEl) return;
    if (!this.lastHealth) {
      this.healthEl.textContent = i18n.dynamic('healthChecking');
      this.healthEl.style.color = '#e2e8f0';
      return;
    }
    const { status, timestamp } = this.lastHealth;
    if (status === 'healthy') {
      this.healthEl.textContent = i18n.dynamic('healthOk', { timestamp });
      this.healthEl.style.color = '#34d399';
    } else {
      this.healthEl.textContent = i18n.dynamic('healthDegraded', { timestamp });
      this.healthEl.style.color = '#f87171';
    }
  }
  async pollHealth() {
    try {
      const data = await DataService.getHealth();
      this.lastHealth = { status: data.status, timestamp: data.timestamp };
      this.renderHealth();
    } catch (error) {
      if (isAbortError(error)) return;
      if (this.healthEl) {
        this.healthEl.textContent = i18n.dynamic('healthError', { message: error.message });
        this.healthEl.style.color = '#f87171';
      }
      Toast.show(i18n.dynamic('toastHealthFail', { message: error.message }));
    }
  }
  async pollRecent() {
    try {
      const payload = await DataService.getRecent();
      if (!payload.success) throw new Error(payload.error || 'API failure');
      bus.publish('recentData', payload);
    } catch (error) {
      if (isAbortError(error)) return;
      Toast.show(i18n.dynamic('toastRecentFail', { message: error.message }));
      const statusEl = document.getElementById('realtime-status');
      if (statusEl) statusEl.textContent = i18n.dynamic('realtimeError', { message: error.message });
    }
  }
  async pollStatus() {
    try {
      const payload = await DataService.getStatus();
      if (!payload.success) throw new Error(payload.error || 'API failure');
      bus.publish('currentStatus', payload.status);
    } catch (error) {
      if (isAbortError(error)) return;
      Toast.show(i18n.dynamic('toastStatusFail', { message: error.message }));
      bus.publish('statusError', { message: error.message });
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  i18n.init();

  const temperatureUnitToggle = new TemperatureUnitToggle();
  temperatureUnitToggle.init();

  const carousel = new ChartCarousel('sensorChart', '.sensor-btn', temperatureUnitToggle);
  carousel.init();

  new StatusPanel();
  new ReportPanel();

  const poller = new DataPoller();
  poller.start();

  window.addEventListener('beforeunload', () => poller.stop());
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) poller.stop();
    else poller.start();
  });
});
