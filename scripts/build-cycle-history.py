"""Extract only explicitly dated sector strengths; preserve labels and provenance."""
import json, re, sys
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import quote

def plain(fragment):
    from html import unescape
    return ' '.join(unescape(re.sub(r'<[^>]*>', ' ', fragment)).split())

def sections(html):
    heads=list(re.finditer(r'<h2\b[^>]*class=[\"\'][^\"\']*chapter-title[^\"\']*[\"\'][^>]*>([\s\S]*?)</h2>',html,re.I))
    result=[]
    for i,h in enumerate(heads):
        end=heads[i+1].start() if i+1<len(heads) else html.find('</main>',h.end())
        fragment=html[h.end():end if end>0 else len(html)]
        fragment=re.sub(r'<(?:script|style)\b[^>]*>[\s\S]*?</(?:script|style)>','',fragment,flags=re.I)
        fragment=re.sub(r'</(?:p|div|tr|h[1-6]|li|section|table)>|<br\s*/?>','\n',fragment,flags=re.I)
        result.append(dict(title=plain(h[1]),text='\n'.join(filter(None,map(plain,fragment.split('\n'))))))
    return result

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables=[]; self.table=None; self.row=None; self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='table': self.table=[]
        elif tag=='tr' and self.table is not None: self.row=[]
        elif tag in ('td','th') and self.row is not None: self.cell=[]
        elif tag=='br' and self.cell is not None: self.cell.append(' ')
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell=None
        elif tag=='tr' and self.row is not None:
            self.table.append(self.row); self.row=None
        elif tag=='table' and self.table is not None:
            self.tables.append(self.table); self.table=None

def build(root):
    records=json.loads((root/'site-data.json').read_text(encoding='utf-8-sig'))
    points={}; days=[]; conflicts=[]
    for r in sorted(records,key=lambda r:r['date_iso']):
        path=r['page_path'].replace('\\','/'); url='https://travelstocks.github.io/daily-trading-review/'+quote(path,safe='/')
        html=(root/path).read_text(encoding='utf-8-sig')
        days.append(dict(date=r['date_iso'],label=r.get('emotion_label',''),summary=r.get('emotion_summary',''),url=url,title=r['title'],updatedAt=r.get('updated_at',''),sections=sections(html)))
        parser=Tables(); parser.feed(html)
        for rows in parser.tables:
            if not rows or not rows[0] or not re.search('板块|题材',rows[0][0]): continue
            dates={}
            next_col=next((i for i,h in enumerate(rows[0]) if '次日' in h),-1)
            judgment_col=next((i for i,h in enumerate(rows[0]) if '核心判断' in h),-1)
            for i,head in enumerate(rows[0][1:],1):
                m=re.search(r'(20\d{2})[./年-](\d{1,2})[./月-](\d{1,2})',head)
                if m: dates[i]='%04d-%02d-%02d'%tuple(map(int,m.groups()))
            for row in rows[1:]:
                if not row: continue
                for i,day in dates.items():
                    if i>=len(row): continue
                    raw=row[i]; m=re.fullmatch(r'\s*([+-]?[\d,]+(?:\.\d+)?)\s*(?:[（(]([^）)]+)[）)])?\s*',raw)
                    strength=float(m[1].replace(',','')) if m else None
                    state=m[2] if m and m[2] else ''
                    name=row[0].strip(); key=(day,name)
                    point=dict(date=day,name=name,strength=strength,state=state,raw=raw,sourceDate=r['date_iso'],url=url)
                    if day==r['date_iso']:
                        point.update(next=row[next_col] if next_col>=0 and next_col<len(row) else '',judgment=row[judgment_col] if judgment_col>=0 and judgment_col<len(row) else '')
                    old=points.get(key)
                    if old and old['raw']!=raw: conflicts.append(dict(date=day,name=name,previous=old['raw'],current=raw,sourceDate=r['date_iso']))
                    # The same-day recap wins; otherwise use the newest recap that quotes this date.
                    if not old or old['sourceDate']!=day: points[key]=point
    data=dict(version=1,latest=max((r['date_iso'] for r in records),default=''),days=days,points=sorted(points.values(),key=lambda p:(p['date'],p['name'])),conflicts=conflicts)
    target=root/'assets'/'cycle-history.json'; target.parent.mkdir(exist_ok=True); target.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return data

if __name__=='__main__':
    data=build(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1])
    print(json.dumps(dict(days=len(data['days']),points=len(data['points']),conflicts=len(data['conflicts']),latest=data['latest'])))
