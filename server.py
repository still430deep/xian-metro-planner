"""Python standard-library web server for Xi'an metro route planning."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs
from html import escape
import json, heapq, os

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / "data" / "network.json").read_text(encoding="utf-8"))
LINES = DATA["lines"]
EDGES = []
for line, info in LINES.items():
    names = info["stations"]
    n = len(names) if info.get("loop") else len(names) - 1
    pairs = list(zip(names, names[1:]))
    if info.get("loop"): pairs.append((names[-1], names[0]))
    for a, b in pairs:
        EDGES.append({"from": a, "to": b, "line": line, "distance_km": info["km"] / n,
                      "minutes": info["minutes"] / n, "estimated": True})
STATIONS = sorted({s for x in LINES.values() for s in x["stations"]})
GRAPH = {}
for e in EDGES:
    GRAPH.setdefault(e["from"], []).append((e["to"], e))
    GRAPH.setdefault(e["to"], []).append((e["from"], e))

def fare(km, only_eight):
    if only_eight: return 6
    for bound, price in ((6,2),(10,3),(14,4),(20,5),(26,6)):
        if km <= bound: return price
    return 6 + int((km - 26 + 7.999) // 8)

def find_plan(start, end, mode, label):
    serial = 0
    todo = [(0, serial, start, None, [])]
    best = {(start, None): 0}
    while todo:
        score, _, node, prev_line, path = heapq.heappop(todo)
        if node == end:
            kms = sum(e["distance_km"] for e in path)
            lines = [e["line"] for e in path]
            transfers = sum(a != b for a,b in zip(lines,lines[1:]))
            mins = sum(e["minutes"] for e in path) + 4 * transfers
            seq = [start]
            for e in path: seq.append(e["to"] if e["from"] == seq[-1] else e["from"])
            return {"label":label,"stations":seq,"lines":lines,"km":round(kms,1),"minutes":round(mins),"transfers":transfers,"fare":fare(kms, bool(lines) and all(x=="8号线" for x in lines))}
        for other,e in GRAPH.get(node,[]):
            cost = (int(prev_line is not None and prev_line != e["line"]) if mode=="transfers" else e[mode])
            new = score + cost
            state=(other,e["line"])
            if new < best.get(state,float("inf")):
                best[state]=new; serial+=1
                heapq.heappush(todo,(new,serial,other,e["line"],path+[e]))
    return None

def render_results(start,end,selected):
    if not start or not end: return ""
    labels={"fewest_transfers":("transfers","少换乘"),"fastest_time":("minutes","时间较快"),"shortest_distance":("distance_km","距离较短")}
    plans=[]
    for key,(mode,label) in labels.items():
        if selected and key not in selected: continue
        p=find_plan(start,end,mode,label)
        if p and all(tuple(p["stations"])!=tuple(x["stations"]) for x in plans): plans.append(p)
    cards=[]
    for i,p in enumerate(plans):
        lines="".join(f'<span class="line-tag">{escape(x)}</span>' for x in dict.fromkeys(p["lines"]))
        cards.append(f'<article class="plan {"plan-featured" if i==0 else ""}"><div class="plan-head"><div><span class="plan-kicker">{"推荐方案" if i==0 else "备选方案"}</span><strong>{p["label"]}</strong></div><span class="duration">{p["minutes"]}<small>分钟</small></span></div><div class="plan-stats"><span><b>{p["km"]}</b> 公里</span><span><b>{p["transfers"]}</b> 次换乘</span><span class="fare"><b>约 {p["fare"]}</b> 元</span></div><div class="line-tags">{lines}</div><div class="itinerary"><div class="itinerary-start"><i></i><strong>{escape(p["stations"][0])}</strong></div><div class="itinerary-middle"><span>{max(0,len(p["stations"])-2)} 站 · {" / ".join(dict.fromkeys(p["lines"]))}</span></div><div class="itinerary-end"><i></i><strong>{escape(p["stations"][-1])}</strong></div><details><summary>查看完整站序</summary><div class="station-list">{"<i>›</i>".join(escape(x) for x in p["stations"])}</div></details></div></article>')
    body="".join(cards) if cards else '<div class="empty-state"><span>⌕</span><strong>未找到可用路线</strong><p>请检查站名后重试。</p></div>'
    return f'<section class="results-section"><div class="results-heading"><div><p class="eyebrow">ROUTE OPTIONS</p><h2>为你找到的方案</h2></div><span>{len(plans)} 个方案</span></div><p class="query-summary">{escape(start)} → {escape(end)}</p><div class="plans">{body}</div><p class="estimate-note">用时、区间里程为估算值；票价按当前票制计算，乘车信息请以现场为准。</p></section>'

def render_lines():
    out=[]
    for i,(line,info) in enumerate(LINES.items(),1):
        sym="户" if line=="西户线" else line.replace("号线","")
        stops="".join(f'<span>{escape(s)}</span>' for s in info["stations"])
        out.append(f'<details class="line-item"><summary><span class="line-symbol line-{i}">{sym}</span><b>{line}</b><small>{len(info["stations"])} 站</small><i>＋</i></summary><div class="line-stops">{stops}</div></details>')
    return "".join(out)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT),**kwargs)
    def do_GET(self):
        if self.path.startswith('/static/'):
            return super().do_GET()
        self.page("", "", [])
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0')); form=parse_qs(self.rfile.read(n).decode('utf-8'))
        self.page(form.get('start',[''])[0].strip(),form.get('end',[''])[0].strip(),form.get('preferences',[]))
    def page(self,start,end,selected):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        html=html.replace('{{START}}',escape(start,quote=True)).replace('{{END}}',escape(end,quote=True))
        html=html.replace('{{STATIONS}}',''.join(f'<option value="{escape(s,quote=True)}"></option>' for s in STATIONS))
        html=html.replace('{{CHECK_TRANSFERS}}','checked' if not selected or 'fewest_transfers' in selected else '')
        html=html.replace('{{CHECK_TIME}}','checked' if not selected or 'fastest_time' in selected else '')
        html=html.replace('{{CHECK_DISTANCE}}','checked' if not selected or 'shortest_distance' in selected else '')
        html=html.replace('{{RESULTS}}',render_results(start,end,selected)).replace('{{LINES}}',render_lines())
        body=html.encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,format,*args): pass

if __name__=='__main__':
    port = int(os.environ.get('PORT', '8000'))
    print(f'Listening on port {port}', flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
