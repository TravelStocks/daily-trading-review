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
ASSET_VERSION = '20261120-2'
RISK_RULE = '按周初权益计算整周收益，包含已实现和浮动盈亏，不按周内高点回撤。无出入金时，周收益率 =（当前权益 / 周初权益 - 1）× 100%；有出入金先单独核对，数据未确认标待核。本周任一时点周收益率 ≤ -5%（恰好亏5%也算）即触线：本周剩余时间停止开新仓，新增开仓预算统一为0。空仓、换票、亏损收窄、看好龙头或小仓试错均不能解除。进入新周重新核对周初权益与三问，不自动放行；已有持仓继续按原退出计划管理。'
QUESTIONS = [
    ('weekly', '本周累计亏损有没有达到5%？', [('','待核'),('clear','已确认本周未触线'),('hit','已触线：停止本周新开仓')]),
    ('mindset', '我是不是急着回本，才想买得更早、买得更重？', [('','待核'),('steady','本人确认：不以回本驱动'),('urgent','有急于回本的心态')]),
    ('context', '天时和题材，是否支持这个买点及仓位？', [('','待核'),('supported','已核对：当前支持'),('unsupported','当前不支持')]),
]

def validate(values):
    if not isinstance(values, dict) or any(not isinstance(v,str) for v in values.values()):
        raise ValueError('Daily preflight must be a flat string dictionary')
    for prefix, _, choices in QUESTIONS:
        if values.get(prefix + 'Status','') not in dict(choices):
            raise ValueError('Invalid preflight status: ' + prefix)
    for key in ['targetDate', 'weeklyTriggeredOn']:
        if values.get(key):
            date.fromisoformat(values[key])
    return values

def panel(day, values):
    blocks = []
    for i,(prefix,title,choices) in enumerate(QUESTIONS,1):
        options = ''.join(f'<option value="{key}">{label}</option>' for key,label in choices)
        weekly = '<label>本周收益率（%，亏损填负数；可留空）<input type="number" step="0.01" data-preflight-field="weeklyReturn"></label>' if prefix == 'weekly' else ''
        blocks.append(
            f'<article class="preflight-question"><header><h4>{i}. {title}</h4><button type="button" data-preflight-edit aria-expanded="false">编辑</button></header>'
            f'<p class="preflight-conclusion">结论：<span data-preflight-answer="{prefix}">待核</span></p>'
            f'<p class="preflight-basis">依据：<span data-preflight-basis="{prefix}">待核</span></p>'
            f'<div class="preflight-editor" hidden><label>结论<select data-preflight-field="{prefix}Status">{options}</select></label>{weekly}'
            f'<label>依据 / 核对日期<textarea data-preflight-field="{prefix}Basis" rows="3"></textarea></label></div></article>')
    seed = json.dumps(values,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return (START + f'<section class="daily-preflight" id="daily-preflight" data-daily-preflight data-review-date="{day}">'
            '<h3>盘前必问 · 三项前置检查</h3><label class="preflight-date">预案执行日<input type="date" data-preflight-field="targetDate"></label>'
            + f'<p data-weekly-risk-rule>{RISK_RULE}</p>'
            + ''.join(blocks) + '<p class="preflight-result" data-preflight-result role="status">待核：三项确认后再看新增预算；周亏达到5%停止本周开新仓。</p>'
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
    for name in ['daily-preflight.js','daily-preflight.css']:
        source = ROOT / 'assets' / name
        destination = asset_dir / name
        if source.resolve() != destination.resolve():
            shutil.copyfile(source,destination)
    link = f'<link rel="stylesheet" data-daily-preflight-asset href="../assets/daily-preflight.css?v={ASSET_VERSION}">'
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
