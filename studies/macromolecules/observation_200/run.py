"""Owner-authorized 200-task observation of the current loop; no prompt/code adoption.

Ran in `.oopc/loop/harness/2026-10-03-200/` and still reads and writes there; moved to the repository on 2026-10-13
unchanged except imports and paths."""
import collections, datetime as dt, hashlib, html, importlib.util, json, os, queue, signal, statistics, sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import run_dir  # noqa: E402  (common puts CODE first on sys.path)
BASE=run_dir('2026-10-03-200'); WORK=BASE/'workspace'
from oopc import ask, calls, engines, knowledge, loop, parity, reviewer, server
from oopc.task_progress import effort, read_progress
from oopc.util import atomic_bytes, atomic_json, locked, now, read_json, resolve_release
spec=importlib.util.spec_from_file_location('buffered_guard',Path(__file__).resolve().with_name('guard.py'))
g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
guard=g.Guard(); entries=read_json(BASE/'questions.json'); by_id={e['taskId']:e for e in entries}
mutex=threading.RLock(); STATE={}; audits={}; ready={e['number']:threading.Event() for e in entries}; jobs=queue.Queue()

def save(name,value): atomic_json(BASE/name,value,private=True)
def state(**values):
 with mutex:
  STATE.update(values,updatedAt=now(),calls=len(guard.call_snapshot()),quota=guard.quota_snapshot())
  save('state.json',STATE)

def run(engine,prompt,schema,**options):
 phase='research' if schema is ask.ANSWER_SCHEMA else 'answer-check' if schema is reviewer.CHECK_SCHEMA else 'review'
 guard.phase=phase
 tracker=options.get('progress')
 if phase=='research' and hasattr(tracker,'path'):
  entry=by_id.get(tracker.path.parent.name)
  guard.number=entry['number'] if entry else None
 state()
 return guard(engine,prompt,schema,**options)

def median(values):
 values=[v for v in values if isinstance(v,(int,float))]
 return statistics.median(values) if values else None

def elapsed(start,end):
 return (dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(start)).total_seconds() if start and end else None

def rows():
 result=[]
 for entry in entries:
  target=ask.folder(WORK)/entry['taskId']; path=target/'question.json'; row=dict(entry,status='unattempted')
  if path.exists():
   item=read_json(path); row.update(status=item['status'],engine=item.get('engine'),error=item.get('error'),attempts=item.get('attempts'),responseSeconds=elapsed(item.get('startedAt'),item.get('finishedAt')))
   row['deposit']=knowledge.deposit_summary(WORK,entry['taskId'])
   if (target/'result.json').exists():
    value=read_json(target/'result.json'); ev=effort(value,read_progress(target/'progress.json')); answer=value.get('answer') or {}
    row.update(newTokens=calls.new_tokens(value.get('usage')),effort=ev,webCalls=sum(ev.get(k) or 0 for k in ('webSearches','pagesRead','unclassifiedWebCalls')),citationCoverage=parity.cited_fraction(answer),reuse=ask.reused_findings(WORK,answer.get('citations')),answerPath=str(target/'result.json'))
  cp=BASE/('check-%03d.json'%entry['number'])
  row['check']=read_json(cp) if cp.exists() else None
  row['audit']=audits.get(entry['number'],{})
  result.append(row)
 return result

def assessment():
 rr=rows(); complete=[r for r in rr if r['status']=='completed']; checked=[r for r in rr if (r.get('check') or {}).get('verdict')]
 statements=[s for r in checked for s in r['check'].get('statements',[])]
 categories=collections.Counter(s.get('category','unspecified') for s in statements if s.get('verdict')!='supported')
 scientific=[s for s in statements if s.get('kind') in ('source-fact','inference')]
 pairs=[]
 for r in rr:
  if r['group']!='repeat' or r['status']!='completed': continue
  first=rr[r['parent']-1]
  if first['status']!='completed': continue
  pairs.append(dict(material=r['material'],first=first['number'],repeat=r['number'],sameEngine=first.get('engine')==r.get('engine'),firstEngine=first.get('engine'),repeatEngine=r.get('engine'),webCalls=[first.get('webCalls'),r.get('webCalls')],newTokens=[first.get('newTokens'),r.get('newTokens')],seconds=[first.get('responseSeconds'),r.get('responseSeconds')],tokenRatio=r['newTokens']/first['newTokens'] if first.get('newTokens') and r.get('newTokens') is not None else None,timeRatio=r['responseSeconds']/first['responseSeconds'] if first.get('responseSeconds') and r.get('responseSeconds') is not None else None,verdicts=[(first.get('check') or {}).get('verdict'),(r.get('check') or {}).get('verdict')],reuse=r.get('reuse')))
 ids=list(by_id); marks=','.join('?' for _ in ids)
 with knowledge.connect(WORK) as db:
  fs=[dict(r) for r in db.execute('SELECT id,status,review_reason,detail FROM findings WHERE question_id IN ('+marks+')',ids)]
  reviews=[dict(r) for r in db.execute('SELECT r.*,d.engine AS producer FROM reviews r JOIN deposits d ON r.question_id=d.question_id WHERE r.question_id IN ('+marks+')',ids)]
  notes=db.execute('SELECT COUNT(*) FROM notes WHERE question_id IN ('+marks+')',ids).fetchone()[0]
 spot=collections.Counter(json.loads(f.get('detail') or '{}').get('spotCheck') for f in fs); spot.pop(None,None)
 completed_reviews=[r for r in reviews if r['status']=='completed']; same=sum(r['engine']==r['producer'] for r in completed_reviews)
 timing=elapsed(STATE.get('startedAt'),STATE.get('finishedAt') or now()); costs=calls.summary(WORK,STATE.get('startedAt',''))
 checks_cost=costs['byPhase'].get('answer-check',{}).get('newTokens',0)
 routine_cost=costs['byPhase'].get('review',{}).get('newTokens',0)
 matched=[p for p in pairs if p['sameEngine']]
 return dict(state=dict(STATE),tasks=dict(total=200,counts=dict(collections.Counter(r['status'] for r in rr)),completed=len(complete),engines=dict(collections.Counter(r.get('engine') for r in complete))),quality=dict(planned=40,checked=len(checked),verdicts=dict(collections.Counter(r['check']['verdict'] for r in checked)),statements=len(statements),supported=sum(s.get('verdict')=='supported' for s in statements),scientificStatements=len(scientific),scientificSupported=sum(s.get('verdict')=='supported' for s in scientific),categories=dict(categories),completeness=dict(collections.Counter(s.get('verdict') for s in statements if s.get('kind')=='completeness')),sourceAccessUncertainty=categories.get('source-access',0)),performance=dict(medianResponseSeconds=median(r.get('responseSeconds') for r in complete),p90ResponseSeconds=sorted(r['responseSeconds'] for r in complete if r.get('responseSeconds') is not None)[int(.9*(len(complete)-1))] if complete else None,medianResearchNewTokens=median(r.get('newTokens') for r in complete),medianWebCalls=median(r.get('webCalls') for r in complete),elapsedRunSeconds=timing,byEngine={e:dict(answers=sum(r.get('engine')==e for r in complete),medianResponseSeconds=median(r.get('responseSeconds') for r in complete if r.get('engine')==e),medianResearchNewTokens=median(r.get('newTokens') for r in complete if r.get('engine')==e)) for e in engines.ENGINES}),costs=dict(costs,routineReviewTokens=routine_cost,boundedAssessmentTokens=checks_cost),knowledge=dict(newFindings=len(fs),statuses=dict(collections.Counter(f['status'] for f in fs)),newSourceNotes=notes,duplicates=sum((r.get('deposit') or {}).get('duplicates',0) for r in rr),spotChecks=dict(spot),reviewsCompleted=len(completed_reviews),sameEngineReviews=same,sameEngineReviewFraction=same/len(completed_reviews) if completed_reviews else None,outstanding=[r['number'] for r in rr if (r.get('deposit') or {}).get('waitingReview')],inconclusiveReasons=[f['review_reason'] for f in fs if f['status']=='uncertain']),reuse=dict(completedPairs=len(pairs),sameEnginePairs=len(matched),medianTokenRatio=median(p['tokenRatio'] for p in matched),medianTimeRatio=median(p['timeRatio'] for p in matched),repeatZeroWeb=sum(p['webCalls'][1]==0 for p in pairs),pairs=pairs),rows=rr)

def report():
 value=assessment(); save('metrics.json',value); save('rows.json',value['rows'])
 q,p,k,c,re=value['quality'],value['performance'],value['knowledge'],value['costs'],value['reuse']
 lines=[f"OOPC 200-task harness — {STATE.get('status')} / {STATE.get('phase')}",f"Completed {value['tasks']['completed']}/200; states: {value['tasks']['counts']}.",f"Revision {read_json(BASE/'baseline.json')['revision']}; prompt {ask.prompt_version()}; standard depth; internet enabled.","160 distinct questions across 40 polymers, then 40 exact repeats. Private knowledge snapshot; deposits accumulate within this run.","SUPPORT AND COMPLETENESS (PRESELECTED 20 FIRST/REPEAT PAIRS)",f"{q['checked']}/40 answer checks: {q['verdicts']}; {q['supported']}/{q['statements']} statements supported; scientific facts/inferences {q['scientificSupported']}/{q['scientificStatements']}.",f"Completeness: {q['completeness']}; non-supported categories: {q['categories']}.","SPEED AND COST",f"Median response {p['medianResponseSeconds']} s; p90 {p['p90ResponseSeconds']} s; elapsed run {p['elapsedRunSeconds']} s.",f"Median research new tokens {p['medianResearchNewTokens']}; median observed research web calls {p['medianWebCalls']}.",f"Total measured uncached input plus output: {c['measuredNewTokens']}; missing usage {c['missingUsage']}; accumulated call duration {c['accumulatedCallSeconds']} s.",f"Routine combined finding-review tokens {c['routineReviewTokens']}; bounded whole-answer assessment tokens {c['boundedAssessmentTokens']}. Failed attempts: {c['failed']}.","KNOWLEDGE INTEGRATION",f"New findings {k['newFindings']}: {k['statuses']}; source notes {k['newSourceNotes']}; duplicate deposits {k['duplicates']}.",f"Sampled Added findings: {k['spotChecks']}; completed review sessions {k['reviewsCompleted']}; same-engine review share {k['sameEngineReviewFraction']}.",f"Outstanding finding reviews: {k['outstanding']}.","EXACT REPEATS",f"{re['completedPairs']} pairs complete ({re['sameEnginePairs']} same-engine pairs); median repeat/first tokens {re['medianTokenRatio']}; time {re['medianTimeRatio']}; {re['repeatZeroWeb']} repeats needed no research web.","Repeat ratios above use same-engine pairs. Prior knowledge already existed before this run; repetition is observational, not a controlled cold-start comparison.","INTERPRETATION AND LIMITS","A support check measures agreement with accessible cited evidence, not ground-truth scientific accuracy. The 40 checks are a preselected descriptive sample; findings from unassessed answers are not independently established.","Unreadable sources and image tables stay uncertain. Whole-answer checks never promote findings. Internal status is supplied at check time; an intervening review may make an earlier Added assertion stale.","Web calls are observed tool activity, not inferred from citations. Missing usage remains unknown. Call durations can overlap and are distinct from response latency and elapsed run time.","No automatic self-improvement system remains: diagnostics inform maintainer-reviewed changes to the one prompt/code, with parity on demand. No prompt changes or adoption occur during this run.","The October 1 report used different prompts/checker behavior and question mix; its pass rate is not a causal before/after comparison.","TOP FOLLOW-UP CHECKS"]
 if q['sourceAccessUncertainty']: lines.append('Inspect source-access failures and image-only tables; separate access failures from contradictions before changing scientific claims.')
 if q['categories'].get('completeness'): lines.append('Read omitted-detail examples and improve completion coverage only where evidence is actually available.')
 if q['categories'].get('bibliography') or q['categories'].get('attribution'): lines.append('Review exact titles, citation assignment and source-specific attribution errors in the sampled answers.')
 if k['spotChecks'].get('unsupported'): lines.append('Inspect unsupported Added findings, their scope/conditions and producer rationale before changing admission guidance.')
 if any(p['webCalls'][1] for p in re['pairs']): lines.append('Inspect repeat web reads: distinguish missing deposited methods/conditions from discretionary reopening of already covered sources.')
 if k['outstanding']: lines.append('Unfinished reviews remain visible; do not describe their findings as Reviewed.')
 lines.append('Human-read representative passed and uncertain answers; broader claim coverage and causal performance comparisons remain unmeasured.')
 lines+=['COST BY PHASE']+[f"{phase}: {bucket}" for phase,bucket in c['byPhase'].items()]
 lines+=['PAIR RESULTS']+[f"{pair['material']}: web {pair['webCalls']}, tokens {pair['newTokens']}, seconds {pair['seconds']}, checks {pair['verdicts']}" for pair in re['pairs']]
 text='\n\n'.join(lines)+'\n'; atomic_bytes(BASE/'report.txt',text.encode(),private=True)
 refresher='<meta http-equiv="refresh" content="30">' if STATE.get('status')=='running' else ''
 links='<p><a href="http://127.0.0.1:8766/#/history">Live harness History</a> · <a href="metrics.json">Full metrics</a> · <a href="rows.json">Task records</a></p>'
 detail=''.join('<details><summary>Task %d — %s — %s</summary><pre>%s</pre></details>'%(r['number'],html.escape(r['material']),html.escape((r.get('check') or {}).get('verdict','unchecked')),html.escape(json.dumps(r['check'],ensure_ascii=False,indent=2))) for r in value['rows'] if r.get('check'))
 page='<!doctype html><meta charset="utf-8">'+refresher+'<title>OOPC 200-task assessment</title><style>body{font:16px system-ui;max-width:1050px;margin:35px auto;padding:20px;background:#fafafa;color:#202a35}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5}details{margin:12px 0}a{color:#175b88}</style><h1>OOPC 200-task assessment</h1>'+links+'<pre>'+html.escape(text)+'</pre><h2>Independent check evidence</h2>'+detail
 atomic_bytes(BASE/'report.html',page.encode(),private=True)

def audit_worker():
 while True:
  entry=jobs.get()
  if entry is None: jobs.task_done(); return
  n,qid=entry['number'],entry['taskId']; guard.number=n
  try:
   audits[n]={'status':'reviewing'}; state(auditQuestion=n,auditPhase='finding-review')
   while qid in knowledge.review_queue(WORK) and not guard.boundary():
    producer=read_json(ask.folder(WORK)/qid/'question.json').get('engine')
    selected=guard.choose(engines.CLAUDE if producer==engines.CODEX else engines.CODEX)
    if not selected: audits[n]={'status':'deferred','reason':'no-eligible-engine'}; break
    try: reviewer.review(WORK,qid,runner=run,engine=selected)
    except engines.EngineError as error:
     audits[n]={'status':'failed','reason':error.reason}
     if qid not in knowledge.review_queue(WORK): break
   ready[n].set() # Research repeats depend only on finding review, never the answer assessment.
   if entry['checkSample'] and not guard.boundary():
    target=ask.folder(WORK)/qid; answer=read_json(target/'result.json')['answer']; sources=parity.resolve_sources(WORK,answer.get('citations'))
    save('check-input-%03d.json'%n,dict(at=now(),question=entry['question'],answer=answer['answer'],sources=sources))
    state(auditPhase='answer-check')
    for attempt in range(2):
     producer=read_json(target/'question.json').get('engine'); selected=guard.choose(engines.CLAUDE if producer==engines.CODEX else engines.CODEX)
     if not selected: save('check-%03d.json'%n,{'error':{'reason':'quota','message':'No eligible engine'},'at':now()}); break
     try:
      checked=reviewer.check_answer(entry['question'],answer['answer'],sources,engine=selected,runner=run,root=WORK,owner=qid)
      save('check-%03d.json'%n,dict(checked,at=now(),attempt=attempt+1)); break
     except engines.EngineError as error:
      save('check-%03d.json'%n,dict(error=error.summary(),at=now(),attempt=attempt+1))
      if not (error.retryable or error.reason in ('quota','not-signed-in')): break
   if audits[n].get('status')=='reviewing': audits[n]={'status':'finished'}
  except Exception as error:
   audits[n]={'status':'failed','reason':'crashed','message':str(error)[:500]}; save('audit-error-%03d.json'%n,audits[n])
  finally:
   ready[n].set(); jobs.task_done(); save('audits.json',audits); state(auditQuestion=None,auditPhase=None,auditsOutstanding=jobs.unfinished_tasks)

def main():
 with locked(BASE/'runner.lock',blocking=False):
  if (BASE/'state.json').exists() and read_json(BASE/'state.json').get('startedAt'): raise RuntimeError('Existing run preserved; no implicit resume or duplicate scheduling.')
  STATE.update(startedAt=now(),pid=os.getpid(),status='running',phase='preflight',planned=200,completed=0,failed=0,unattempted=200)
  state(); guard.quota(engines.CODEX); guard.quota(engines.CLAUDE)
  questions=ask.Questions(WORK,runner=run,reviews=False)
  web=server.make_server(WORK,resolve_release(WORK),8766,task_service=questions,loop_runner=run)
  threading.Thread(target=web.serve_forever,daemon=True,name='harness-view').start()
  worker=threading.Thread(target=audit_worker,name='harness-assessment',daemon=True); worker.start()
  report(); stop_reason=None
  try:
   for entry in entries:
    if guard.boundary(): stop_reason=guard.boundary(); break
    if ask.prompt_version()!=read_json(BASE/'baseline.json')['promptVersion']: stop_reason='prompt-changed'; break
    selected=guard.choose(engines.CODEX)
    if not selected: stop_reason='no-eligible-engine'; break
    if entry['parent']:
     while not ready[entry['parent']].wait(1):
      if guard.boundary(): break
    state(phase='research',question=entry['number'],material=entry['material'])
    questions.submit(dict(question=entry['question'],depth='standard',runtime=selected,origin='research',taskId=entry['taskId'],authorizeSubscription=True))
    while questions._read(entry['taskId'])['status'] in ('queued','running'):
     questions.wait(timeout=1)
     state()
     if guard.boundary(): engines._stop_live_workers()
    item=questions._read(entry['taskId']); state(completed=STATE['completed']+(item['status']=='completed'),failed=STATE['failed']+(item['status']=='failed'),unattempted=200-entry['number'])
    if item['status']=='completed':
     audits[entry['number']]={'status':'waiting'}; jobs.put(entry)
    else: ready[entry['number']].set()
    state(auditsOutstanding=jobs.unfinished_tasks); report()
   state(phase='finishing',stopReason=stop_reason,question=None)
   jobs.put(None)
   while worker.is_alive():
    worker.join(1); state(auditsOutstanding=max(0,jobs.unfinished_tasks-1))
    if guard.boundary(): engines._stop_live_workers()
   for e in engines.ENGINES: guard.quota(e)
   final_status='stopped' if stop_reason else 'completed'
   state(status=final_status,phase='report',auditsOutstanding=0)
   report()
   state(status=final_status,phase='finished',finishedAt=now())
   report()
  except BaseException as error:
   state(status='failed',phase='report',error=type(error).__name__+': '+str(error)[:500]); engines._stop_live_workers()
   worker.join(5)
   state(status='failed',phase='finished',finishedAt=now()); report(); raise
  finally: web.shutdown(); web.server_close()

if __name__=='__main__':
 signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('runner terminated')))
 main()
