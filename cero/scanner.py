"""Motor en segundo plano con cancelación, progreso y resultados incrementales."""
import json
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from cero.db import connect,upsert,now,setting,set_setting,unpack
from cero.analyzer import score_deals
from cero.hunter import SEEDS,check_url,discovery_jobs,listing_job,search_job,catalog_job,candidate
from cero.policy import canonical
from cero.telegram import enqueue
from cero.market import COUNTRY

_lock=threading.Lock();_stop=threading.Event();_shutdown=threading.Event();_found_ids=set()
STATE={'running':False,'message':'El radar está listo.','done':0,'total':0,'found':0,'checked':0,'phase':'idle','profile':'','run_id':None,'log':deque(maxlen=120)}


def status():
    with _lock:return {**STATE,'log':list(STATE['log'])}


def _log(text):
    with _lock:STATE['message']=text;STATE['log'].append(text)


def _progress(phase,done,total):
    with _lock:STATE.update(phase=phase,done=done,total=total)


def start(profile='normal',url=None):
    with _lock:
        if STATE['running']:return False
        STATE.update(running=True,message='Preparando el radar…',done=0,total=0,found=0,checked=0,phase='starting',profile=profile)
        STATE['log'].clear();_stop.clear()
        _found_ids.clear()
    threading.Thread(target=_run,args=(profile,url),daemon=True,name='cero-hunter').start();return True


def stop():
    _stop.set();c=connect()
    try:
        cfg=schedule_config(c);cfg['enabled']=False;set_setting(c,'schedule',cfg);c.commit()
    finally:c.close()
    _log('Deteniendo: se conservan los resultados y se pausa el rastreo automático. Puedes reactivarlo en Configuración.');return True


def _save(conn,d):
    from cero.images import ensure_image
    ensure_image(d)
    key=upsert(conn,d);enqueue(conn,key,d);conn.commit()
    with _lock:
        STATE['checked']+=1
        if key not in _found_ids and d.get('status')=='verified' and d.get('image_status')=='verified' and candidate(d):
            _found_ids.add(key);STATE['found']+=1


def _verify(conn,items,label):
    # Evita duplicar fichas por precio, título, origen o parámetros de seguimiento.
    rest={r['url'] for r in conn.execute('SELECT url FROM restocks WHERE active=1 AND next_check>?',(now(),))}
    unique={canonical(d['url']):d for d in items if STATE['profile']=='single' or canonical(d['url']) not in rest}
    total=len(unique);_progress(label,0,total);pending=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(check_url,d['url'],d):d for d in unique.values()}
        for i,future in enumerate(as_completed(futures),1):
            if _stop.is_set():
                for f in futures:f.cancel()
                break
            try:d=future.result()
            except Exception as exc:_log('No se pudo comprobar una ficha: '+type(exc).__name__);continue
            _progress(label,i,total)
            if d:
                pending.append(d)
                if len(pending)>=4:
                    score_deals(conn,pending,_log)
                    for row in pending:_save(conn,row)
                    pending=[]
    if pending and not _stop.is_set():
        score_deals(conn,pending,_log)
        for row in pending:_save(conn,row)


def priority_items(conn):
    # Las ofertas activas no esperan detrás de cientos de indicios sin confirmar.
    hot=conn.execute("SELECT * FROM deals WHERE status='verified' AND (price=0 OR discount_pct>=80) ORDER BY favorite DESC,checked_at LIMIT 120").fetchall()
    tracked=conn.execute("SELECT * FROM deals WHERE (favorite=1 OR last_verified_at IS NOT NULL) AND status!='rejected' AND page_status!='not_found' ORDER BY favorite DESC,checked_at LIMIT 60").fetchall()
    pending=conn.execute("SELECT * FROM deals WHERE last_verified_at IS NULL AND status IN ('candidate','unverified','conditional','blocked') AND page_status!='not_found' ORDER BY checked_at LIMIT 60").fetchall()
    return list({r['id']:unpack(r) for r in [*hot,*tracked,*pending]}.values())


def _run(profile,url):
    c=connect();run_id=None;outcome='completed'
    try:
        cur=c.execute('INSERT INTO runs(profile,started_at,status) VALUES(?,?,?)',(profile,now(),'running'))
        run_id=cur.lastrowid;c.commit()
        with _lock:STATE['run_id']=run_id
        existing=priority_items(c)
        watches=[dict(r) for r in c.execute('SELECT * FROM watches')]
        due_restocks=[unpack(r) for r in c.execute('SELECT d.* FROM deals d JOIN restocks r ON r.deal_id=d.id WHERE r.active=1 AND r.next_check<=?',(now(),))]
        items=due_restocks+existing+watches+[{'url':u} for u in SEEDS]
        if url:items=[{'url':url}]+[d for d in existing if canonical(d['url'])==canonical(url)]
        _log(f'Comprobando {len({canonical(d["url"]) for d in items})} fichas y productos vigilados.')
        _verify(c,items,'checking')
        if not _stop.is_set() and profile!='single':set_setting(c,'last_watch',now());c.commit()
        if not _stop.is_set() and profile not in ('watch','single'):
            from cero.amazon import collect as amazon_collect
            amazon_candidates,amazon_read=amazon_collect(profile,_log)
            if amazon_candidates:_verify(c,amazon_candidates[:50],'amazon')
            from cero.adapters import deporvillage
            from cero.hunter import health
            import time
            began=time.monotonic()
            api_candidates,read=deporvillage(_log) if COUNTRY=='ES' else ([],0)
            if COUNTRY=='ES':health('Deporvillage · catálogo completo','catálogo','https://www.deporvillage.com/outlet','ok' if read else 'empty',time.monotonic()-began,read)
            if api_candidates:_verify(c,api_candidates,'catalogue')
            from cero.registry import import_catalog,analyze_catalog
            import_catalog()
            from cero.policy import host_of
            catalog_seen=set();catalog_counts={};catalog_limit=150 if profile=='deep' else 80
            def live_catalog(found):
                if _stop.is_set():return
                selected=[]
                for d in sorted(found,key=lambda d:(d.get('price')==0,d.get('discount_pct') or 0),reverse=True):
                    key=canonical(d['url']);host=host_of(key)
                    if key in catalog_seen or len(catalog_seen)>=catalog_limit or catalog_counts.get(host,0)>=5:continue
                    catalog_seen.add(key);catalog_counts[host]=catalog_counts.get(host,0)+1;selected.append(d)
                if selected:_verify(c,selected,'verifying')
            analyze_catalog(600 if profile=='deep' else 35,_log,_stop.is_set,
                            lambda done,total:_progress('coverage',done,total),live_catalog)
            jobs=discovery_jobs(c,profile);_log(f'Explorando {len(jobs)} fuentes: tiendas, catálogos y buscadores.');_progress('discovery',0,len(jobs))
            candidates=[];urls=[]
            with ThreadPoolExecutor(max_workers=8) as pool:
                tasks={}
                for kind,name,arg,q in jobs:
                    if _stop.is_set():break
                    fn,args=(listing_job,(name,arg,q)) if kind=='listing' else (search_job,(name,arg)) if kind=='search' else (catalog_job,(name,arg))
                    tasks[pool.submit(fn,*args)]=kind
                for i,f in enumerate(as_completed(tasks),1):
                    if _stop.is_set():
                        for other in tasks:other.cancel()
                        break
                    _progress('discovery',i,len(tasks))
                    try:result=f.result()
                    except Exception as exc:_log('Fuente fallida: '+type(exc).__name__);continue
                    if tasks[f]=='search':urls.extend(result)
                    else:candidates.extend(result)
            if not _stop.is_set():
                candidates=sorted(candidates,key=lambda d:(d.get('price')==0,d.get('discount_pct') or 0),reverse=True)
                # Repartir el presupuesto de fichas entre tiendas evita que un solo catálogo monopolice el radar.
                from cero.policy import host_of
                counts={};selected=[];limit=150 if profile=='deep' else 65
                for d in candidates:
                    host=host_of(d['url']);counts[host]=counts.get(host,0)+1
                    if counts[host]<=12:selected.append(d)
                selected=selected[:limit]+[{'url':u,'source':'buscador'} for u in dict.fromkeys(urls)][:80 if profile=='deep' else 30]
                _log(f'{len(candidates)} candidatos de catálogos; {len(set(urls))} enlaces de buscadores. Verificando fichas.');_verify(c,selected,'verifying')
        if _stop.is_set():outcome='cancelled';_log('Rastreo detenido. Los hallazgos ya comprobados están guardados.')
        else:_log(f'Pasada terminada: {STATE["checked"]} fichas revisadas, {STATE["found"]} ofertas verificadas en esta pasada.')
    except Exception as exc:
        outcome='failed';_log('El rastreo se interrumpió: '+type(exc).__name__+': '+str(exc)[:150])
    finally:
        if run_id:
            c.execute('UPDATE runs SET finished_at=?,status=?,checked=?,found=?,log=? WHERE id=?',
              (now(),outcome,STATE['checked'],STATE['found'],json.dumps(list(STATE['log']),ensure_ascii=False),run_id))
            set_setting(c,'last_'+profile,now());c.commit()
        c.close()
        with _lock:STATE.update(running=False,phase='idle')


DEFAULTS={'enabled':True,'continuous':True,'cycle_pause_seconds':60,'watch_minutes':15,'discovery_minutes':60,'deep_hours':24}


def schedule_config(conn):return {**DEFAULTS,**setting(conn,'schedule',{})}


def scheduler_loop():
    while not _shutdown.wait(15):
        if STATE['running']:continue
        c=connect()
        try:
            cfg=schedule_config(c)
            if not cfg['enabled']:continue
            def due(key,seconds):
                last=setting(c,'last_'+key)
                if not last:return True
                return (datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()>=seconds
            if due('watch',cfg['watch_minutes']*60):start('watch')
            elif due('deep',cfg['deep_hours']*3600):start('deep')
            elif cfg['continuous'] and due('normal',cfg['cycle_pause_seconds']):start('normal')
            elif due('normal',cfg['discovery_minutes']*60):start('normal')
        finally:c.close()


def boot():
    _shutdown.clear()
    c=connect();c.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE status='running'",(now(),));c.commit();c.close()
    threading.Thread(target=scheduler_loop,daemon=True,name='cero-scheduler').start()


def shutdown():_shutdown.set();_stop.set()
