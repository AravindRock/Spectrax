#!/usr/bin/env python3
"""SpectraX backend (stdlib only). Keeps API keys server-side. Run: python server.py -> http://127.0.0.1:8000"""
import json, os, re, time, urllib.request, urllib.error, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
ROOT = os.path.dirname(os.path.abspath(__file__))
def load_env():
    p = os.path.join(ROOT, '.env')
    if os.path.exists(p):
        for l in open(p):
            l = l.strip()
            if l and not l.startswith('#') and '=' in l:
                k, v = l.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"\''))
load_env()
def http(url, body=None, headers=None, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json', 'User-Agent': 'SpectraX/0.1', **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read())
WC = {0:'clear',1:'mainly clear',2:'partly cloudy',3:'overcast',45:'fog',48:'fog',51:'drizzle',53:'drizzle',55:'drizzle',61:'rain',63:'rain',65:'heavy rain',80:'showers',81:'showers',82:'violent showers',95:'thunderstorm',96:'thunderstorm',99:'thunderstorm'}
_wc = {}
def wx_summary(o):
    if not o: return 'No weather data'
    rp = max((p.get('rain_prob_6h_max') or 0) for p in o); wk = max((p.get('wind_kmh') or 0) for p in o)
    vs = [p['visibility_km_min'] for p in o if p.get('visibility_km_min') is not None]; t = [p['temp_c'] for p in o if p.get('temp_c') is not None]
    s = 'Rain risk up to %d%% (next 6 h) · wind up to %.0f km/h' % (rp, wk)
    if vs: s += ' · min visibility %.0f km' % min(vs)
    if t: s += ' · %.0f–%.0f °C' % (min(t), max(t))
    return s
def route_weather(points):
    pts = [(round(a, 3), round(b, 3)) for a, b in points[:8]]; hit = _wc.get(tuple(pts))
    if hit and time.time() - hit[0] < 300: return hit[1]          # 5-minute cache
    base = {'latitude': ','.join(str(p[0]) for p in pts), 'longitude': ','.join(str(p[1]) for p in pts),
        'current': 'temperature_2m,apparent_temperature,relative_humidity_2m,is_day,precipitation,rain,weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m',
        'hourly': 'precipitation_probability,precipitation,visibility,uv_index', 'forecast_hours': 6,
        'daily': 'sunrise,sunset,uv_index_max,precipitation_probability_max', 'forecast_days': 1, 'timezone': 'auto'}
    try: j = http('https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode({**base, 'minutely_15': 'visibility,rain', 'forecast_minutely_15': 2}))
    except urllib.error.HTTPError as e:
        if e.code != 400: raise
        j = http('https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(base))
    j = j if isinstance(j, list) else [j]; out = []
    for (la, lo), d in zip(pts, j):
        c = d.get('current', {}); h = d.get('hourly', {}); dl = d.get('daily', {}); mn = d.get('minutely_15', {})
        pp = [x for x in h.get('precipitation_probability', []) if x is not None]
        vis = [x for x in (mn.get('visibility', []) + h.get('visibility', [])) if x is not None]
        uv = [x for x in h.get('uv_index', []) if x is not None]
        g = lambda k: (dl.get(k) or [None])[0]
        out.append({'lat': la, 'lon': lo, 'elev_m': d.get('elevation'), 'temp_c': c.get('temperature_2m'), 'feels_c': c.get('apparent_temperature'),
            'humidity': c.get('relative_humidity_2m'), 'is_day': c.get('is_day'), 'precip_mm': c.get('precipitation'), 'rain_mm': c.get('rain'),
            'code': c.get('weather_code'), 'condition': WC.get(c.get('weather_code'), 'code %s' % c.get('weather_code')), 'cloud': c.get('cloud_cover'),
            'pressure_hpa': c.get('pressure_msl'), 'wind_kmh': c.get('wind_speed_10m'), 'wind_dir': c.get('wind_direction_10m'), 'gust_kmh': c.get('wind_gusts_10m'),
            'rain_prob_6h_max': max(pp) if pp else None, 'visibility_km_min': round(min(vis) / 1000, 1) if vis else None,
            'uv_max': max(uv) if uv else g('uv_index_max'), 'sunrise': g('sunrise'), 'sunset': g('sunset')})
    res = {'ok': True, 'source': 'Open-Meteo (live forecast)', 'points': out, 'summary': wx_summary(out), 'fetched': time.strftime('%H:%M:%S')}
    _wc[tuple(pts)] = (time.time(), res); return res
def tavily(q, topic='general'):
    k = os.environ.get('TAVILY_API_KEY')
    if not k: return {'ok': False, 'error': 'TAVILY_API_KEY not configured', 'results': []}
    body = {'query': q[:300], 'max_results': 3, 'search_depth': 'basic', 'topic': topic}
    if topic == 'news': body['days'] = 3
    j = http('https://api.tavily.com/search', body, {'Authorization': 'Bearer ' + k})
    return {'ok': True, 'source': 'Tavily', 'results': [{'title': r.get('title'), 'url': r.get('url'), 'snippet': (r.get('content') or '')[:240], 'published': r.get('published_date')} for r in j.get('results', [])]}
def soc_drop_pct(distance_km, consumption_kwh_per_100km, capacity_kwh):
    """Battery percentage points used over a distance. Consumption is kWh per 100 km."""
    energy_kwh = distance_km * consumption_kwh_per_100km / 100      # kWh per 100 km -> kWh
    return energy_kwh / capacity_kwh * 100                          # kWh -> % of capacity (the /100 and *100 cancel)
def estimate_energy(s, distance_km, cons=None):
    v = s['vehicle']; cons = cons or v['consumption']; kwh = distance_km * cons / 100
    return {'distance_km': distance_km, 'energy_kwh': round(kwh, 1), 'soc_after_pct': round(v['soc'] - soc_drop_pct(distance_km, cons, v['capacity_kwh']), 1),
            'model': 'baseline: distance × consumption / 100 (not calibrated to a real vehicle)'}
def rank_chargers(s, max_off=30):
    v = s['vehicle']; out = []
    for c in s['chargers']:
        if c['ahead_km'] <= 0 or c['off_route_km'] > max_off: continue
        a = v['soc'] - soc_drop_pct(c['ahead_km'], v['consumption'], v['capacity_kwh'])
        out.append({**c, 'arrival_soc_at_charger': round(a, 1), 'feasible': bool(c['available']) and a >= v['reserve_pct'], 'charge_min_20_80': round(70 / (min(c['kw'], 200) * .9) * 60)})
    out.sort(key=lambda c: (not c['feasible'], c['off_route_km'], -c['kw'])); return out
def validate_stop(s, cid):
    c = next((x for x in rank_chargers(s, 1e9) if x['id'] == cid), None)
    if not c: return {'accepted': False, 'reason': 'unknown charger or behind the vehicle'}
    if not c['available']: return {'accepted': False, 'reason': 'charger unavailable'}
    if c['arrival_soc_at_charger'] < s['vehicle']['reserve_pct']: return {'accepted': False, 'reason': 'not reachable above reserve'}
    return {'accepted': True, 'charger_id': cid, 'arrival_soc_at_charger': c['arrival_soc_at_charger']}
def _fn(n, d, p): return {'type': 'function', 'function': {'name': n, 'description': d, 'parameters': p}}
TOOLS = [_fn('get_route_weather', 'Live Open-Meteo forecast at 5 sampled points along the current route.', {'type': 'object', 'properties': {}}),
 _fn('tavily_search', 'Web search for road disruptions or charging-provider info. Sourced snippets only, never live charger availability.', {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}),
 _fn('estimate_energy', 'Deterministic energy estimate for a distance.', {'type': 'object', 'properties': {'distance_km': {'type': 'number'}}, 'required': ['distance_km']}),
 _fn('find_chargers', 'Rank chargers ahead on the route (availability is SIMULATED).', {'type': 'object', 'properties': {}}),
 _fn('update_journey_plan', 'Propose the charging stop; the server validates feasibility.', {'type': 'object', 'properties': {'charger_id': {'type': 'string'}, 'reason': {'type': 'string'}}, 'required': ['charger_id', 'reason']})]
SYSTEM = ('You are the SpectraX EV journey agent. The JSON user message is the journey state; vehicle telemetry, traffic and charger availability are SIMULATED. '
 'Use tools: 1) get_route_weather, 2) tavily_search once for road disruptions or charging info on the corridor to the destination, 3) estimate_energy and find_chargers, '
 '4) if arrival SoC is below 15% or the current stop is unavailable, call update_journey_plan with the best feasible charger. Never invent data. '
 'Finish with ONLY a JSON object: {"status":"ok|risk|critical","situation_summary":str,"detected_risks":[str],"evidence":[str],"selected_action":"keep_plan|set_charging_stop","charger_id":str|null,"reason":str,"confidence":"low|medium|high","limitations":[str]}. Be concise.')
def run_tool(n, a, s, st):
    if n == 'get_route_weather': r = route_weather(([s['position']] if s.get('position') else []) + s['route_samples']); return r, r['summary']
    if n == 'tavily_search':
        r = tavily(str(a.get('query', ''))); st['sources'] += r.get('results', []); return r, ('%d results' % len(r['results']) if r['ok'] else r['error'])
    if n == 'estimate_energy':
        r = estimate_energy(s, float(a.get('distance_km', s['vehicle']['total_km'] - s['vehicle']['pos_km']))); return r, '%.1f kWh → SoC %.1f%%' % (r['energy_kwh'], r['soc_after_pct'])
    if n == 'find_chargers': r = {'chargers': rank_chargers(s)[:4], 'availability': 'simulated'}; return r, '%d candidates' % len(r['chargers'])
    if n == 'update_journey_plan':
        r = validate_stop(s, str(a.get('charger_id')))
        if r['accepted']: st['action'] = {'type': 'set_charging_stop', 'charger_id': a['charger_id'], 'reason': a.get('reason', '')}
        return r, 'accepted' if r['accepted'] else 'rejected: ' + r['reason']
    return {'error': 'unknown tool'}, 'unknown tool'
BRIEF = ('You are the SpectraX pre-trip route analyst. Input: the journey state, live Open-Meteo weather (including at the traveller\'s current location), and Tavily search evidence about chargers, roads, weather alerts and the current location. '
 'Use only the provided evidence and tool results; cite URLs for news claims; if evidence is empty or irrelevant say so. Vehicle telemetry, traffic and charger availability are SIMULATED. If arrival SoC is below 15% you may call find_chargers and update_journey_plan. '
 'Output ONLY JSON: {"verdict":"go|caution|avoid","summary":str,"weather_notes":str,"charger_notes":str,"road_notes":str,"location_notes":str,"risks":[str],"recommended_actions":[str],"sources":[url],"limitations":[str]}. Be concise.')
CHAT = ('You are the SpectraX route companion. Answer the traveller\'s questions about this route in under 120 words using the journey context and the tools (weather, web search, energy estimate, charger ranking). '
 'Never invent data; say which facts are live (weather, routes, places, search) and which are simulated (battery, traffic, charger availability).')
def llm_cfg():
    return (os.environ.get('LLM_API_KEY') or os.environ.get('NVIDIA_API_KEY') or os.environ.get('NEBIUS_API_KEY'),
            os.environ.get('LLM_BASE_URL', 'https://integrate.api.nvidia.com/v1').rstrip('/'), os.environ.get('LLM_MODEL', 'nvidia/nemotron-3.5-lightning-30b-a3b'))
def loop(msgs, s, tools=None, turns=5):
    key, base, model = llm_cfg()
    if not key: return {'ok': False, 'degraded': True, 'error': 'LLM API key not configured', 'steps': []}
    st = {'sources': [], 'action': None}; steps = []; m = {}
    try:
        for i in range(turns):                                       # bounded: max `turns` model calls, 3 tools per call
            body = {'model': model, 'messages': msgs, 'temperature': .2, 'max_tokens': 1500}
            if tools: body['tools'] = tools; body['tool_choice'] = 'auto' if i < turns - 1 else 'none'
            m = http(base + '/chat/completions', body, {'Authorization': 'Bearer ' + key}, timeout=60)['choices'][0]['message']
            msgs.append({k: v for k, v in m.items() if k in ('role', 'content', 'tool_calls')})
            tcs = m.get('tool_calls') or []
            if not tcs or not tools: break
            for tc in tcs[:3]:
                n = tc['function']['name']
                try: a = json.loads(tc['function'].get('arguments') or '{}')
                except Exception: a = {}
                try: res, sm = run_tool(n, a, s, st)
                except Exception as e: res, sm = {'error': str(e)}, 'error: ' + str(e)[:80]
                steps.append({'tool': n, 'args': a, 'summary': sm}); msgs.append({'role': 'tool', 'tool_call_id': tc['id'], 'content': json.dumps(res)[:6000]})
        return {'ok': True, 'model': model, 'text': m.get('content') or '', 'steps': steps, 'action': st['action'], 'sources': st['sources'][:8]}
    except urllib.error.HTTPError as e: return {'ok': False, 'degraded': True, 'error': 'LLM HTTP %s: %s' % (e.code, e.read()[:200].decode('utf8', 'ignore')), 'steps': steps}
    except Exception as e: return {'ok': False, 'degraded': True, 'error': 'LLM call failed: %s' % e, 'steps': steps}
def parse_json(txt):
    mm = re.search(r'\{[\s\S]*\}', txt or '')
    try: return json.loads(mm.group(0)) if mm else {}
    except Exception: return {}
def agent(s):
    r = loop([{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps(s)[:20000]}], s, TOOLS, 5)
    if r['ok']: r['final'] = parse_json(r.pop('text')) or {'situation_summary': 'Model did not return JSON', 'selected_action': 'keep_plan'}
    return r
def brief(d):
    s = d.get('ctx') or {}
    r = loop([{'role': 'system', 'content': BRIEF}, {'role': 'user', 'content': json.dumps({'journey': s, 'evidence': d.get('evidence', [])})[:24000]}], s, TOOLS, 3)
    if r['ok']: r['final'] = parse_json(r.pop('text')) or {'verdict': 'caution', 'summary': 'Model did not return structured JSON.'}
    return r
def chat(d):
    s = d.get('ctx') or {}; hist = [{'role': h['role'], 'content': str(h.get('content', ''))[:1500]} for h in (d.get('history') or [])[-6:] if h.get('role') in ('user', 'assistant')]
    msgs = [{'role': 'system', 'content': CHAT}, {'role': 'user', 'content': 'Journey context (JSON): ' + json.dumps(s)[:16000]}, {'role': 'assistant', 'content': 'Understood. Ask me about this route.'}] + hist + [{'role': 'user', 'content': str(d.get('message', ''))[:1000]}]
    r = loop(msgs, s, [t for t in TOOLS if t['function']['name'] != 'update_journey_plan'], 4)
    if r['ok']: r['reply'] = r.pop('text')
    return r
def update_env(k, v):
    p = os.path.join(ROOT, '.env'); lines = open(p).read().splitlines() if os.path.exists(p) else []; out = []; done = False
    for l in lines:
        if l.startswith(k + '='): out.append('%s=%s' % (k, v)); done = True
        else: out.append(l)
    if not done: out.append('%s=%s' % (k, v))
    open(p, 'w').write('\n'.join(out) + '\n')
def set_config(d):
    for k, e in (('llm_key', 'LLM_API_KEY'), ('tavily_key', 'TAVILY_API_KEY')):
        v = (d.get(k) or '').strip()
        if not v: continue
        if not re.fullmatch(r'[A-Za-z0-9._\-]{8,200}', v): raise ValueError('invalid key format')
        os.environ[e] = v; update_env(e, v)                         # kept in memory and the local, git-ignored .env; never returned to the browser
    return {'ok': True}
def selftest(svc):
    t = time.time()
    try:
        if svc == 'llm':
            key, base, model = llm_cfg()
            if not key: return {'ok': False, 'error': 'API key needed'}
            http(base + '/chat/completions', {'model': model, 'messages': [{'role': 'user', 'content': 'Reply with the single word OK'}], 'max_tokens': 16, 'temperature': 0}, {'Authorization': 'Bearer ' + key}, timeout=12); detail = model.split('/')[-1]
        elif svc == 'tavily':
            r = tavily('Chennai weather today')
            if not r['ok']: return {'ok': False, 'error': r['error']}
            detail = 'search ok'
        elif svc == 'wx': detail = '%s °C in Chennai' % route_weather([(13.08, 80.27)])['points'][0]['temp_c']
        else: return {'ok': False, 'error': 'unknown service'}
        return {'ok': True, 'ms': int((time.time() - t) * 1000), 'detail': detail}
    except urllib.error.HTTPError as e: return {'ok': False, 'error': 'HTTP %s' % e.code}
    except Exception as e: return {'ok': False, 'error': str(e)[:80]}
class H(BaseHTTPRequestHandler):
    def send(self, code, body, ct='application/json'):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header('Content-Type', ct); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == '/api/selftest': return self.send(200, selftest((urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('svc') or [''])[0]))
        if p == '/api/health': return self.send(200, {'ok': True, 'llm_key': bool(os.environ.get('LLM_API_KEY') or os.environ.get('NVIDIA_API_KEY') or os.environ.get('NEBIUS_API_KEY')), 'tavily_key': bool(os.environ.get('TAVILY_API_KEY')), 'model': os.environ.get('LLM_MODEL', 'nvidia/nemotron-3.5-lightning-30b-a3b')})
        f = 'titan-hmi.html' if p == '/' else p.lstrip('/'); fp = os.path.normpath(os.path.join(ROOT, f))
        if not fp.startswith(ROOT) or f.startswith('.') or f.endswith('.py') or not os.path.isfile(fp): return self.send(404, {'error': 'not found'})
        self.send(200, open(fp, 'rb').read(), {'.html': 'text/html', '.png': 'image/png'}.get(os.path.splitext(fp)[1], 'text/plain'))
    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path; n = int(self.headers.get('Content-Length') or 0)
        if n > 60000: return self.send(413, {'error': 'request too large'})
        try: d = json.loads(self.rfile.read(n) or b'{}')
        except Exception: return self.send(400, {'error': 'invalid JSON'})
        try:
            if p == '/api/weather': return self.send(200, route_weather([(float(a), float(b)) for a, b in d['points']]))
            if p == '/api/search':
                r = tavily(str(d.get('query', '')), 'news' if d.get('topic') == 'news' else 'general')
                return self.send(200 if r['ok'] else 503, r if r['ok'] else {'error': r['error']})
            if p == '/api/agent': return self.send(200, agent(d))
            if p == '/api/brief': return self.send(200, brief(d))
            if p == '/api/chat': return self.send(200, chat(d))
            if p == '/api/config':
                if self.client_address[0] not in ('127.0.0.1', '::1'): return self.send(403, {'error': 'local only'})
                return self.send(200, set_config(d))
        except ValueError as e: return self.send(400, {'error': str(e)})
        except Exception as e: return self.send(502, {'ok': False, 'error': 'upstream error: %s' % e})
        self.send(404, {'error': 'not found'})
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000)); print('SpectraX on http://127.0.0.1:%d' % port); ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
