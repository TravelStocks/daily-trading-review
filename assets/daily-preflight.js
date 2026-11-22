(() => {
  const root = document.querySelector('[data-daily-preflight]');
  if (!root) return;
  const seed = JSON.parse(root.querySelector('[data-daily-preflight-defaults]').textContent);
  const pageDate = root.dataset.reviewDate;
  const dayKey = 'a-share-daily-preflight-' + pageDate + '-v1';
  const fields = [...root.querySelectorAll('[data-preflight-field]')];
  const allowed = fields.map(field => field.dataset.preflightField);
  let storageFailed = false;
  const read = key => {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); }
    catch { storageFailed = true; return null; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); }
    catch { storageFailed = true; }
  };
  const state = {...seed};
  const contextLabels = {
    marketStage: {falling:'下跌',stabilizing:'企稳',strengthening:'转强'},
    themeContinuity: {sustained:'有持续性',broken:'持续性不足 / 已中断'},
    themeReflow: {confirmed:'回流已确认',expected:'仅预期回流',none:'未见回流',ongoing:'持续走强，非回流节点'}
  };
  const saved = read(dayKey);
  if (saved && !Array.isArray(saved)) {
    for (const key of allowed) if (typeof saved[key] === 'string') state[key] = saved[key];
  }
  const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') &&
    !Number.isNaN(Date.parse(value)) && new Date(value + 'T00:00:00Z').toISOString().slice(0,10) === value;
  const weekOf = value => {
    if (!validDate(value)) return '';
    const date = new Date(value + 'T00:00:00Z');
    date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
    return date.toISOString().slice(0,10);
  };
  const lossHit = value => String(value ?? '').trim() !== '' && Number.isFinite(Number(value)) && Number(value) <= -5;
  const memory = new Map();
  let snapshot = {locked:false, ready:false, reason:'待核'};
  const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
  const evaluate = () => {
    const date = state.targetDate;
    const week = weekOf(date);
    const key = 'a-share-weekly-loss-stop-' + week + '-v1';
    const prior = week ? read(key) : null;
    const records = Array.from(new Map([...(Array.isArray(prior) ? prior : []), ...(memory.get(week) || [])]
      .filter(record => validDate(record.date) && weekOf(record.date) === week)
      .map(record => [JSON.stringify([record.date,record.basis]),record])).values());
    const seedTriggerDate = seed.weeklyTriggeredOn || seed.targetDate;
    const seedHit = week && weekOf(seedTriggerDate) === week && seedTriggerDate <= date &&
      (seed.weeklyStatus === 'hit' || lossHit(seed.weeklyReturn));
    if (week && (state.weeklyStatus === 'hit' || lossHit(state.weeklyReturn) || seedHit)) {
      const record = {date:seedHit ? seedTriggerDate : date, basis:seedHit ? seed.weeklyBasis : state.weeklyBasis};
      if (!records.some(item => item.date === record.date && item.basis === record.basis)) records.push(record);
      memory.set(week, records);
      write(key, records);
    }
    const trigger = records.filter(record => record.date <= date).sort((a,b) => a.date.localeCompare(b.date))[0];
    const locked = Boolean(trigger);
    const complete = prefix => Boolean(String(state[prefix + 'Basis'] || '').trim());
    const weeklyClear = !storageFailed && week && state.weeklyStatus === 'clear' && complete('weekly');
    const contextSequenceComplete = Boolean(contextLabels.marketStage[state.marketStage] && complete('market') &&
      contextLabels.themeContinuity[state.themeContinuity] && contextLabels.themeReflow[state.themeReflow] && complete('theme'));
    const checklistReady = !allowed.includes('checklistStatus') || state.checklistStatus === 'reviewed' && complete('checklist');
    const ready = !locked && weeklyClear && state.mindsetStatus === 'steady' && complete('mindset') &&
      contextSequenceComplete && state.contextStatus === 'supported' && complete('context') && checklistReady;
    return {locked, ready, trigger, week, weeklyClear, contextSequenceComplete};
  };
  const set = (selector, value) => { root.querySelector(selector).textContent = value; };
  const notify = () => window.dispatchEvent(new CustomEvent('daily-preflight-change'));
  const refresh = () => {
    snapshot = evaluate();
    const {locked,ready,trigger,weeklyClear,contextSequenceComplete} = snapshot;
    set('[data-preflight-answer="weekly"]', locked ? '已触线 · 本周停止开新仓' : weeklyClear ? '已确认未触线 · 继续核对后两问' : '待核');
    set('[data-preflight-basis="weekly"]', locked ? (trigger.basis || '本人确认本周已触线；具体依据待补。') + '\n触线记录适用日：' + trigger.date : state.weeklyBasis || '待核：尚未确认本周期初权益、当前收益及本周触线记录。');
    set('[data-preflight-answer="mindset"]', state.mindsetStatus === 'urgent' ? '急于回本 · 不得放宽纪律' : state.mindsetStatus === 'steady' && state.mindsetBasis?.trim() ? '本人已确认 · 不以回本驱动这笔交易' : '待核');
    set('[data-preflight-basis="mindset"]', state.mindsetBasis || '待核：需要本人当前确认，不根据亏损推测心态。');
    set('[data-preflight-answer="market"]', contextLabels.marketStage[state.marketStage] && state.marketBasis?.trim() ? contextLabels.marketStage[state.marketStage] : '待核');
    set('[data-preflight-basis="market"]', state.marketBasis || '待核：记录大盘状态及对应日期、走势、量能与反证；单根阳线或十字星不直接等于底部确认。');
    for (const key of ['themeContinuity','themeReflow']) set('[data-preflight-answer="' + key + '"]', contextLabels[key][state[key]] && state.themeBasis?.trim() ? contextLabels[key][state[key]] : '待核');
    set('[data-preflight-basis="theme"]', state.themeBasis || '待核：写明题材、逐日强弱和回流证据；区分实际回流与仅有回流预期。');
    set('[data-preflight-answer="context"]', state.contextStatus === 'unsupported' ? '当前不支持 · 不执行新开仓' : !contextSequenceComplete ? '待核 · 先完成大盘与题材判断' : state.contextStatus === 'supported' && state.contextBasis?.trim() ? '已确认支持 · 仍服从周风控与更严限仓' : '待核');
    set('[data-preflight-basis="context"]', state.contextBasis || '待核：基于前两步，核对龙头地位、主动性、承接、左右侧买点、仓位上限与失效条件；不能只因看好龙头而放行。');
    if (allowed.includes('checklistStatus')) {
      const checked = state.checklistStatus === 'reviewed' && state.checklistBasis?.trim();
      set('[data-preflight-answer="checklist"]', checked ? '已逐票核对 · 仍服从三问和更严风控' : '待核 · 尚未完成逐票清单核对');
      set('[data-preflight-basis="checklist"]', state.checklistBasis || '待核：逐票记录归类、依据与时点、买点及失效条件、预算。禁忌票剔除或仅零预算观察；无计划时写明继续空仓。');
    }
    const message = locked ? '本周已触及亏损5%：所有新增开仓预算为0。看好龙头、回本冲动、换票或后续回升均不解除；已有持仓按原退出计划处理。' :
      ready ? '三问及页面要求的逐票清单核对已记录；按原预案与更严风控执行，不代表买点已触发。' : '前置检查未全部确认：新增开仓预算待核，不作为开仓许可。';
    set('[data-preflight-result]', message);
    document.querySelectorAll('[data-preflight-plan-notice]').forEach(node => {node.textContent = message;});
    set('[data-preflight-storage]', storageFailed ? '本地存储不可用或记录损坏，请核对；未自动放行。' : '检查结果保存在当前浏览器；公共页面不会上传本地修改。');
    notify();
  };
  window.dailyPreflight = {
    budget: value => snapshot.locked ? '0' : snapshot.ready ? String(value ?? '') : '待核',
    field(row,index,label,field) {
      if (field !== 'budget') return null;
      const locked = !snapshot.ready;
      return '<span class="plan-field-label">新增开仓预算</span><div class="plan-field-value" contenteditable="' + !locked +
        '" role="textbox" aria-label="新增开仓预算" data-index="' + index + '" data-field="budget"' +
        (locked ? ' data-preflight-locked aria-readonly="true"' : '') + '>' +
        esc(this.budget(row.budget)) + '</div><small class="preflight-budget-original">原预案草稿：' + esc(row.budget || '待填') + '（不代表执行许可）</small>';
    }
  };
  fields.forEach(field => { field.value = state[field.dataset.preflightField] || ''; });
  root.addEventListener('click', event => {
    const button = event.target.closest('[data-preflight-edit]');
    if (!button) return;
    const editor = button.closest('.preflight-question,.preflight-checklist-review').querySelector('.preflight-editor');
    editor.hidden = !editor.hidden;
    button.textContent = editor.hidden ? '编辑' : '完成';
    button.setAttribute('aria-expanded', String(!editor.hidden));
  });
  root.addEventListener('change', event => {
    const field = event.target.closest('[data-preflight-field]');
    if (!field) return;
    const oldTarget = state.targetDate;
    state[field.dataset.preflightField] = field.value;
    if (allowed.includes('checklistStatus') && ['checklistBasis','marketStage','marketBasis','themeContinuity','themeReflow','themeBasis','contextStatus','contextBasis'].includes(field.dataset.preflightField)) {
      state.checklistStatus = '';
      root.querySelector('[data-preflight-field="checklistStatus"]').value = '';
    }
    if (['marketStage','marketBasis','themeContinuity','themeReflow','themeBasis'].includes(field.dataset.preflightField)) {
      state.contextStatus = '';
      root.querySelector('[data-preflight-field="contextStatus"]').value = '';
    }
    if (field.dataset.preflightField === 'targetDate' && oldTarget !== field.value) {
      for (const key of allowed.filter(key => key !== 'targetDate')) state[key] = '';
      fields.forEach(item => {item.value = state[item.dataset.preflightField] || '';});
    }
    write(dayKey,state);
    refresh();
  });
  window.addEventListener('storage', event => {
    if (event.key?.startsWith('a-share-weekly-loss-stop-')) refresh();
  });
  refresh();
})();
