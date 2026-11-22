"""Install daily risk questions and effective-budget hooks without changing drafts."""
import argparse
import json
import re
import shutil
from datetime import date
from html import escape
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- DAILY_PREFLIGHT_START -->'
END = '<!-- DAILY_PREFLIGHT_END -->'
ASSET_VERSION = '20261122-four-stops'
RISK_RULE = '按周初权益计算整周收益，包含已实现和浮动盈亏，不按周内高点回撤。无出入金时，周收益率 =（当前权益 / 周初权益 - 1）× 100%；有出入金先单独核对，数据未确认标待核。本周任一时点周收益率 ≤ -5%（恰好亏5%也算）即触线：本周剩余时间停止开新仓，新增开仓预算统一为0。空仓、换票、亏损收窄、看好龙头或小仓试错均不能解除。进入新周重新核对周初权益与三问，不自动放行；已有持仓继续按原退出计划管理。'
QUESTIONS = [
    ('weekly', '本周累计亏损有没有达到5%？', [('','待核'),('clear','已确认本周未触线'),('hit','已触线：停止本周新开仓')]),
    ('mindset', '我是不是急着回本，才想买得更早、买得更重？', [('','待核'),('steady','本人确认：不以回本驱动'),('urgent','有急于回本的心态')]),
    ('context', '天时和题材，是否支持这个买点及仓位？', [('','待核'),('supported','已核对：当前支持'),('unsupported','当前不支持')]),
]
DISCIPLINE_LISTS = """<section class="trading-discipline" id="trading-discipline" data-trading-discipline>
<h2>三份交易清单</h2>
<p class="discipline-date">个人执行纪律 · 2026-11-22更新 · 先过风控三问，再逐票归类</p>
<div class="discipline-grid">
<section class="discipline-column discipline-forbidden" data-trading-category="forbidden"><h3>禁忌清单</h3><p class="discipline-action">不新增开仓</p><ul>
<li><strong>抢反弹、抄底、切换</strong></li><li><strong>同身位PK</strong></li><li><strong>低身位卡高身位PK</strong></li>
</ul><ol class="discipline-four-stops"><li>不抢未定龙</li><li>不做被动跟风</li><li>不在弱天时左侧重仓</li><li>不为回本放宽纪律</li></ol><p>切换不再保留旧版“半成仓试错”例外。</p></section>
<section class="discipline-column discipline-limited" data-trading-category="limited"><h3>少做清单</h3><p class="discipline-action">严格筛选，条件写清</p><ul>
<li><strong>普通补涨</strong><span>仅确认地位的“补涨三板龙”列入主做，其余仍少做。</span></li>
<li><strong>监管反核</strong><span>若做，仅限首日，最多两成仓；更严限仓和周风控优先。</span></li>
<li><strong>绕异动</strong></li>
</ul></section>
<section class="discipline-column discipline-primary" data-trading-category="primary"><h3>主做清单</h3><p class="discipline-action">模式内确认，不自动放行</p><ol class="primary-mode-priority">
<li><span class="mode-priority-label">第一优先级 · 核心主攻 <b>80%</b></span><strong>题材第一波主升二阶段连板龙</strong><span>竞价超预期缺口；回封大单半路；板上连续大单进攻。</span></li>
<li><span class="mode-priority-label">第二优先级 · 重点关注 <b>12%</b></span><strong>龙头二波</strong><span>突破平台或反包板。</span></li>
<li><span class="mode-priority-label">第三优先级 · 次要关注 <b>6%</b></span><strong>抱团龙</strong><span>反包或突破平台，只做主动核心。</span></li>
<li><span class="mode-priority-label">第四优先级 · 严格择机 <b>2%</b></span><strong>补涨三板龙</strong><span>确认地位的三板买点，不延伸为四板盲接。</span></li>
</ol><p>主模式与次模式为8:2；次模式内部二波、抱团、补涨为6:3:1。80%、12%、6%、2%是模式侧重与重要程度，不是单笔仓位比例或开仓指令；风控与确认条件始终优先。</p></section>
</div>
<p class="discipline-threshold"><strong>1/4口径：</strong>连续进攻大单金额 ≥ 上方压单金额 × 1/4，仅作为准备排单信号；仍须同时核对题材、龙头地位、量能与失效条件，不是自动买入。</p>
<p class="discipline-check"><strong>逐票核对：</strong>标的 → 清单归类 → 依据与时点 → 买点及失效条件 → 新增预算。禁忌票新增预算0；少做须写清参与条件；未确认标待核。主做不等于无条件做。</p>
<p class="discipline-stop"><strong>周亏按周初权益计算，达到5%，本周全部新增开仓预算为0。三份清单均不能豁免。</strong></p>
</section>
"""

CONTEXT_CHOICES = {
    'marketStage': [('', '待核'), ('falling', '下跌'), ('stabilizing', '企稳'), ('strengthening', '转强')],
    'themeContinuity': [('', '待核'), ('sustained', '有持续性'), ('broken', '持续性不足 / 已中断')],
    'themeReflow': [('', '待核'), ('confirmed', '回流已确认'), ('expected', '仅预期回流'), ('none', '未见回流'), ('ongoing', '持续走强，非回流节点')],
}

def select_field(key, label, choices):
    options = ''.join(f'<option value="{value}">{text}</option>' for value, text in choices)
    return f'<label>{label}<select data-preflight-field="{key}">{options}</select></label>'

def context_steps():
    return (
        '<p class="preflight-order">先分别判断大盘与短线情绪是在下跌、企稳还是转强，再核题材持续性与实际回流，最后决定龙头买点和仓位。指数与情绪共振下行时，不新开中高位连板接力仓；等待共同企稳或转强，不能因为看好龙头就忽略天时。医药、电力仅为防御观察方向，行业名称不能自动放行；周亏按周初权益达到5%后，本周新增开仓预算始终为0。</p>'
        '<div class="preflight-context-step"><h5>3.1 大盘：下跌、企稳还是转强？</h5>'
        '<p class="preflight-conclusion">结论：<span data-preflight-answer="market">待核</span></p>'
        '<p class="preflight-basis">依据：<span data-preflight-basis="market">待核</span></p></div>'
        '<div class="preflight-context-step"><h5>3.2 题材：有没有持续性和实际回流？</h5>'
        '<p class="preflight-conclusion">持续性：<span data-preflight-answer="themeContinuity">待核</span><br>回流：<span data-preflight-answer="themeReflow">待核</span></p>'
        '<p class="preflight-basis">依据：<span data-preflight-basis="theme">待核</span></p></div>'
        '<h5 class="preflight-decision-title">3.3 个股：以上证据是否支持龙头买点及仓位？</h5>'
    )

def context_editor():
    return (
        select_field('marketStage', '大盘状态', CONTEXT_CHOICES['marketStage'])
        + '<label>大盘与情绪依据 / 日期（分别写指数走势、量能；高标反馈、晋级与炸板、赚钱与亏钱效应。未确认标待核）<textarea data-preflight-field="marketBasis" rows="3"></textarea></label>'
        + select_field('themeContinuity', '题材持续性', CONTEXT_CHOICES['themeContinuity'])
        + select_field('themeReflow', '题材回流状态', CONTEXT_CHOICES['themeReflow'])
        + '<label>题材依据 / 日期（题材名称、逐日强弱、实际回流或未确认信号）<textarea data-preflight-field="themeBasis" rows="3"></textarea></label>'
    )

def discipline_review():
    return (DISCIPLINE_LISTS
        + '<article class="preflight-checklist-review"><header><h4>今日逐票清单核对</h4><button type="button" data-preflight-edit aria-expanded="false">编辑</button></header>'
        '<p class="preflight-conclusion">结论：<span data-preflight-answer="checklist">待核</span></p>'
        '<p class="preflight-basis">依据：<span data-preflight-basis="checklist">待核：逐票记录清单归类、依据与时点、买点及失效条件、预算；禁忌票预算0。</span></p>'
        '<div class="preflight-editor" hidden>'
        + select_field('checklistStatus', '核对结论', [('', '待核'), ('reviewed', '已逐票核对，禁忌票已剔除 / 仅零预算观察')])
        + '<label>逐票依据 / 日期（少做写条件，主做写买点，禁忌预算0；无计划时写明继续空仓）<textarea data-preflight-field="checklistBasis" rows="5"></textarea></label></div></article>')

def validate(values):
    if not isinstance(values, dict) or any(not isinstance(v,str) for v in values.values()):
        raise ValueError('Daily preflight must be a flat string dictionary')
    for prefix, _, choices in QUESTIONS:
        if values.get(prefix + 'Status','') not in dict(choices):
            raise ValueError('Invalid preflight status: ' + prefix)
    for key, choices in CONTEXT_CHOICES.items():
        if values.get(key, '') not in dict(choices):
            raise ValueError('Invalid preflight context field: ' + key)
    for key in ['targetDate', 'weeklyTriggeredOn']:
        if values.get(key):
            date.fromisoformat(values[key])
    if values.get('checklistStatus', '') not in ['', 'reviewed']:
        raise ValueError('Invalid checklist status')
    return values

def panel(day, values):
    blocks = []
    for i,(prefix,title,choices) in enumerate(QUESTIONS,1):
        options = ''.join(f'<option value="{key}">{label}</option>' for key,label in choices)
        weekly = '<label>本周收益率（%，亏损填负数；可留空）<input type="number" step="0.01" data-preflight-field="weeklyReturn"></label>' if prefix == 'weekly' else ''
        blocks.append(
            f'<article class="preflight-question"><header><h4>{i}. {title}</h4><button type="button" data-preflight-edit aria-expanded="false">编辑</button></header>'
            + (context_steps() if prefix == 'context' else '')
            +
            f'<p class="preflight-conclusion">结论：<span data-preflight-answer="{prefix}">待核</span></p>'
            f'<p class="preflight-basis">依据：<span data-preflight-basis="{prefix}">待核</span></p>'
            '<div class="preflight-editor" hidden>'
            + (context_editor() if prefix == 'context' else '')
            + f'<label>{"买点及仓位综合结论" if prefix == "context" else "结论"}<select data-preflight-field="{prefix}Status">{options}</select></label>{weekly}'
            + f'<label>{"龙头地位、买点、仓位上限、失效条件 / 日期" if prefix == "context" else "依据 / 核对日期"}<textarea data-preflight-field="{prefix}Basis" rows="3"></textarea></label></div></article>')
    seed = json.dumps(values,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return (START + f'<section class="daily-preflight" id="daily-preflight" data-daily-preflight data-review-date="{day}">'
            '<p class="preflight-motto" data-preflight-motto><strong>风控才是股市存活的生命线。</strong></p><p data-no-rebound-rule><strong>不要抢反弹，不要抄底。收益空间有限、风险难以控制时，宁可空仓，也不在悬崖边上跳舞。君子不立危墙之下，先避免置身险境。</strong></p><p><strong>先问风控，再问心态，最后问买点与仓位。第一问触线，后两问不能推翻停止开仓。</strong></p>'
            '<h3>盘前必问 · 三项前置检查</h3><label class="preflight-date">预案执行日<input type="date" data-preflight-field="targetDate"></label>'
            + f'<p data-weekly-risk-rule>{RISK_RULE}</p>'
            + ''.join(blocks) + discipline_review() + '<p class="preflight-result" data-preflight-result role="status">待核：三问及逐票清单核对完成后再看新增预算；周亏达到5%停止本周开新仓。</p>'
            '<p class="preflight-storage" data-preflight-storage></p>'
            f'<script type="application/json" data-daily-preflight-defaults>{seed}</script></section>' + END)

def upgrade(script):
    if '// DAILY_PREFLIGHT_BUDGET' in script:
        return script
    marker = 'const planField = (row, index, label, field) => '
    if script.count(marker) != 1:
        raise ValueError('Expected one plan field renderer')
    line = next(line for line in script.splitlines() if marker in line)
    expression = line.split(marker,1)[1].rstrip().removesuffix(';')
    fallback = '<span class="plan-field-label">新增开仓预算</span><div class="plan-field-value" data-field="budget" aria-readonly="true">待核</div>'
    replacement = marker + "{ if (field === 'budget') return window.dailyPreflight?.field(row,index,label,field) ?? " + json.dumps(fallback,ensure_ascii=False) + "; return " + expression + "; };"
    script = script.replace(line, '  ' + replacement,1)
    script, count = re.subn(r'\b(r|row)\.budget(?=,)', r"window.dailyPreflight?.budget(\1.budget) ?? '待核'", script)
    if count != 1:
        raise ValueError(f'Expected one CSV budget value, got {count}')
    anchor = "  root.addEventListener('input', event => {"
    if script.count(anchor) != 1:
        raise ValueError('Expected one plan input listener')
    return script.replace(anchor, "// DAILY_PREFLIGHT_BUDGET\n  window.addEventListener('daily-preflight-change', () => render());\n" + anchor,1)

def apply(page, values=None, source=None):
    page = Path(page)
    raw = source if source is not None else page.read_bytes().decode('utf-8-sig')
    soup = BeautifulSoup(raw,'html.parser')
    root = soup.select_one('[data-plan-preconditions]')
    if root is None:
        raise ValueError('Missing daily preconditions: ' + str(page))
    day = re.search(r'\d{4}-\d{2}-\d{2}',root.get('data-storage-key',''))
    if not day:
        raise ValueError('Missing dated prerequisite storage key')
    day = day[0]
    previous = soup.select_one('[data-daily-preflight-defaults]')
    if values is None:
        values = json.loads(previous.string) if previous else {}
    values = dict(validate(values))
    if not values.get('targetDate'):
        title = soup.title.get_text() if soup.title else ''
        target = re.search(r'\+\s*(\d{1,2})[./月](\d{1,2})',title)
        if target:
            month,daynum = map(int,target.groups())
            year = int(day[:4]) + (month < int(day[5:7]))
            values['targetDate'] = date(year,month,daynum).isoformat()
    scripts = [node for node in soup.select('script') if 'const planField = ' in (node.string or '')]
    if len(scripts) != 1:
        raise ValueError('Expected one operation-plan script')
    old = scripts[0].string
    new = upgrade(old)
    raw = raw.replace(old,new,1)
    raw = re.sub(re.escape(START)+r'.*?'+re.escape(END),'',raw,flags=re.S)
    raw = re.sub(r'<(?:link|script)\b[^>]*data-daily-preflight-asset[^>]*>(?:</script>)?','',raw)
    root_tag = re.search(r'<section\b[^>]*\bdata-plan-preconditions=[^>]*>',raw)
    if not root_tag:
        raise ValueError('Missing root insertion point')
    raw = raw[:root_tag.end()] + panel(day,values) + raw[root_tag.end():]
    asset_dir = page.parent.parent / 'assets'
    asset_dir.mkdir(exist_ok=True)
    for name in ['daily-preflight.js','daily-preflight.css','trading-discipline.css']:
        source = ROOT / 'assets' / name
        destination = asset_dir / name
        if source.resolve() != destination.resolve():
            shutil.copyfile(source,destination)
    link = f'<link rel="stylesheet" data-daily-preflight-asset href="../assets/daily-preflight.css?v={ASSET_VERSION}"><link rel="stylesheet" data-daily-preflight-asset href="../assets/trading-discipline.css?v={ASSET_VERSION}">'
    raw = raw.replace('</head>',link+'</head>',1)
    if 'data-daily-preflight-nav' not in raw:
        nav = re.search(r'<a\b[^>]*href="#plan-preconditions"[^>]*>',raw)
        if nav:
            raw = raw[:nav.start()] + '<a href="#daily-preflight" data-daily-preflight-nav>盘前必问 · 三项检查</a>' + raw[nav.start():]
    script_tag = f'<script data-daily-preflight-asset src="../assets/daily-preflight.js?v={ASSET_VERSION}"></script>'
    # Load after the forms exist, before the operation editor renders budgets.
    start = raw.rfind('<script',0,raw.index(new))
    raw = raw[:start] + script_tag + raw[start:]
    if 'data-preflight-plan-notice' not in raw:
        editor_tag = re.search(r'<div\b[^>]*data-operation-plan=[^>]*>',raw)
        if not editor_tag:
            editor_tag = re.search(r'<section\b[^>]*data-operation-plan=[^>]*>',raw)
        if not editor_tag:
            raise ValueError('Missing plan notice location')
        raw = raw[:editor_tag.end()] + '<p class="preflight-plan-notice" data-preflight-plan-notice>前置检查待核</p>' + raw[editor_tag.end():]
    page.write_bytes(raw.encode('utf-8'))
    return day

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('pages',nargs='+',type=Path)
    parser.add_argument('--values',type=Path)
    args = parser.parse_args()
    values = json.loads(args.values.read_text(encoding='utf-8')) if args.values else None
    for page in args.pages:
        print(apply(page,values),page.name)
