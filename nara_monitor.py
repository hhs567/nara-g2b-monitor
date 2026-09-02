import os, json, time, hashlib
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import unquote
import requests

KEYWORDS = ['계획','설계','정비','구상','타당성','지정','재생','조성','시행','개발','검토','후보지','전략','조사','사업화']
SEOUL = ZoneInfo('Asia/Seoul')
STATE_FILE = os.getenv('STATE_FILE','seen_ids.json')
LOOKBACK_MINUTES = int(os.getenv('LOOKBACK_MINUTES','30'))
NUM_OF_ROWS = int(os.getenv('NUM_OF_ROWS','1000'))

APIS = [
 ('발주계획','https://apis.data.go.kr/1230000/ao/OrderPlanSttusService','getOrderPlanSttusListServc','G2B_ORDERPLAN_KEY'),
 ('사전규격','https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService','getPublicPrcureThngInfoServc','G2B_PRESPEC_KEY'),
 ('입찰공고','https://apis.data.go.kr/1230000/ad/BidPublicInfoService','getBidPblancListInfoServc','G2B_BID_KEY'),
]

def now(): return datetime.now(SEOUL)

def load_state():
    p=Path(STATE_FILE)
    if not p.exists(): return {}
    try: return json.loads(p.read_text(encoding='utf-8'))
    except: return {}

def save_state(s): Path(STATE_FILE).write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')

def extract_items(obj):
    out=[]
    def walk(x):
        if isinstance(x,dict):
            if 'item' in x:
                v=x['item']
                if isinstance(v,list): out.extend(i for i in v if isinstance(i,dict))
                elif isinstance(v,dict): out.append(v)
            for v in x.values():
                if isinstance(v,(dict,list)): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(obj)
    uniq=[]; seen=set()
    for r in out:
        sig=json.dumps(r,ensure_ascii=False,sort_keys=True,default=str)
        if sig not in seen: seen.add(sig); uniq.append(r)
    return uniq

def text_of(r):
    vals=[]
    def walk(x):
        if isinstance(x,dict):
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
        elif x is not None: vals.append(str(x))
    walk(r)
    return ' '.join(vals)

def first(r, keys):
    for k in keys:
        v=r.get(k) if isinstance(r,dict) else None
        if v not in (None,''): return str(v).strip()
    return ''

def uid(label,r):
    keys=['orderPlanUntyNo','bfSpecRgstNo','bidNtceNo','bidNtceOrd']
    vals=[str(r.get(k,'')) for k in keys if r.get(k) not in (None,'')]
    if vals: return label+'|'+'|'.join(vals)
    raw=json.dumps(r,ensure_ascii=False,sort_keys=True,default=str)
    return label+'|'+hashlib.sha256(raw.encode()).hexdigest()

def fetch(label,base,op,keyenv):
    key=os.getenv(keyenv,'').strip()
    if not key: raise RuntimeError(f'{keyenv} Secret이 없습니다.')
    end=now(); start=end-timedelta(minutes=LOOKBACK_MINUTES)
    params={'serviceKey':unquote(key),'pageNo':1,'numOfRows':NUM_OF_ROWS,'type':'json','inqryDiv':'1','inqryBgnDt':start.strftime('%Y%m%d%H%M'),'inqryEndDt':end.strftime('%Y%m%d%H%M')}
    if label=='발주계획':
        params['orderBgnYm']=start.strftime('%Y%m'); params['orderEndYm']=end.strftime('%Y%m')
    res=requests.get(base.rstrip('/')+'/'+op,params=params,timeout=40)
    res.raise_for_status()
    return extract_items(res.json())

def message(label,r,kws):
    title=first(r,['bidNtceNm','bfSpecNm','orderPlanNm','prdctNm','bsnsNm','cntrctNm']) or '(제목 확인 필요)'
    inst=first(r,['ntceInsttNm','orderInsttNm','dmndInsttNm','rlDminsttNm','insttNm']) or '-'
    dt=first(r,['bidNtceDt','rgstDt','orderPlanDt','bfSpecRgstDt','ntceDt'])
    url=first(r,['bidNtceDtlUrl','bfSpecDtlUrl','orderPlanUrl','ntceDtlUrl'])
    lines=[f'🔔 [나라장터 {label}]',title,'',f'🏢 발주기관: {inst}',f'🔎 검색어: {", ".join(kws)}']
    if dt: lines.append(f'🕒 등록/공고일: {dt}')
    if url: lines += ['',f'🔗 {url}']
    return '\n'.join(lines)

def send_telegram(txt):
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip(); chat=os.getenv('TELEGRAM_CHAT_ID','').strip()
    if not token or not chat: raise RuntimeError('Telegram Secret이 없습니다.')
    u=f'https://api.telegram.org/bot{token}/sendMessage'
    r=requests.post(u,json={'chat_id':chat,'text':txt,'disable_web_page_preview':True},timeout=30)
    r.raise_for_status()

def main():
    state=load_state(); new=0; errors=[]
    for spec in APIS:
        label=spec[0]
        try:
            records=fetch(*spec); print(f'[{label}] {len(records)}건 조회')
            for r in records:
                t=text_of(r); kws=[k for k in KEYWORDS if k in t]
                if not kws: continue
                k=uid(label,r)
                if k in state: continue
                send_telegram(message(label,r,kws))
                state[k]=now().isoformat(); save_state(state); new+=1; time.sleep(.4)
        except Exception as e:
            print(f'[오류] {label}: {e}'); errors.append(str(e))
    save_state(state); print(f'[완료] 신규 알림 {new}건')
    if errors: raise SystemExit(1)

if __name__=='__main__': main()
