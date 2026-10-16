"""Scripted lifecycle/accounting checks. Never invokes host engines or binds ports.

The 200-task observation's test_harness.py (`.oopc/loop/harness/2026-10-03-200/`), moved to the repository on
2026-10-13 unchanged except imports and paths, a skip when the run's private records are absent, and its scratch
workspace in the system temporary folder instead of inside the private run folder."""
import importlib.util, pathlib, shutil, sqlite3, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import STUDY, run_dir  # noqa: E402  (common puts CODE first on sys.path)
from oopc import ask, engines, knowledge, loop
from oopc.util import atomic_json, read_json
BASE=run_dir('2026-10-03-200')
class Web:
 def serve_forever(self): pass
 def shutdown(self): pass
 def server_close(self): pass
@unittest.skipUnless((BASE/'questions.json').exists() and (BASE/'workspace/releases/current.json').exists(),
                     "needs the 200-task run's private records (.oopc/loop/harness/2026-10-03-200)")
class HarnessTests(unittest.TestCase):
 def test_inputs_are_balanced_and_repeats_are_exact(self):
  entries=read_json(BASE/'questions.json')
  self.assertEqual(len(entries),200); self.assertEqual(len({e['question'] for e in entries}),160)
  self.assertEqual(sum(e['checkSample'] for e in entries),40)
  self.assertEqual(len({e['material'] for e in entries}),40)
  for e in entries:
   if e['parent']: self.assertEqual(e['question'],entries[e['parent']-1]['question'])
  self.assertEqual({e['angle'] for e in entries if e['checkSample']},{0,1,2,3})
 def test_research_review_check_and_repeat_accounting(self):
  spec=importlib.util.spec_from_file_location('scripted200',STUDY/'observation_200'/'run.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as tmp:
   temp=pathlib.Path(tmp); work=temp/'workspace'; work.mkdir(); (work/'releases').mkdir()
   release=(BASE/'workspace/releases/current.json').read_text()
   shutil.copy2(BASE/'workspace/releases/current.json',work/'releases/current.json')
   for p in (BASE/'workspace/releases').iterdir():
    if p.is_symlink(): (work/'releases'/p.name).symlink_to(p.resolve(),target_is_directory=True)
   loop.update_settings(work,dict(reviewMode='researcher',spotCheckRate=.2,researchPerWeek=0))
   m.BASE=temp; m.WORK=work; m.g.BASE=temp; m.STATE={}; m.audits={}
   first=dict(number=1,material='PET',angle=0,group='distinct',question='Report a scripted PET film result with a method.',depth='standard',parent=None,checkSample=True,taskId='a'*32)
   repeat=dict(first,number=2,group='repeat',parent=1,taskId='b'*32)
   m.entries=[first,repeat]; m.by_id={e['taskId']:e for e in m.entries}; m.ready={n:m.threading.Event() for n in (1,2)}
   atomic_json(temp/'baseline.json',dict(promptVersion=ask.prompt_version(),revision='scripted'),private=True)
   counters={'review':0,'research':0,'check':0}
   def session(engine,prompt,schema,**opts):
    if schema is ask.ANSWER_SCHEMA:
     counters['research']+=1
     answer=dict(answer='Reported value `https://example.org/pet`.',citations=['https://example.org/pet'],findings=[dict(statement='PET film result is 2 units under the stated conditions.',material='PET',property='permeability',value='2',unit='units',conditions='specified film',sourceTitle='PET study',sourceUrl='https://example.org/pet',sourceDoi='',locator='Table 1',excerpt='value 2',needsReview=True,reviewFlag='needs a source check')],sources=[],limitations=[],openQuestions=[])
    elif schema is m.reviewer.REVIEW_SCHEMA:
     counters['review']+=1
     if counters['review']==1: raise engines.EngineError('quota','scripted exhausted Claude',usage={'input_tokens':10,'cached_input_tokens':0,'output_tokens':2})
     data=m.json.loads(prompt[prompt.index('{'):]); answer={'verdicts':[dict(id=f['id'],verdict='supported',reason='scripted source confirms') for f in data['findings']], 'notes':''}
    else:
     counters['check']+=1; answer=dict(verdict='pass',statements=[dict(statement='result',verdict='supported',reason='scripted source',kind='source-fact',category='none')],notes='')
    return dict(engine=engine,answer=answer,agentSeconds=.1,sessionId='scripted',usage={'input_tokens':100,'cached_input_tokens':60,'output_tokens':10},observedTools=[])
   m.guard=m.g.Guard(read_quota=lambda e:{'remainingPercent':90},run_session=session)
   with patch.object(engines,'signed_in',return_value=True),patch.object(m.server,'make_server',return_value=Web()): m.main()
   self.assertEqual(m.STATE['status'],'completed'); self.assertEqual(counters,dict(review=2,research=2,check=2))
   metrics=read_json(temp/'metrics.json'); self.assertEqual(metrics['tasks']['completed'],2)
   self.assertEqual(metrics['reuse']['completedPairs'],1); self.assertEqual(metrics['quality']['checked'],2)
   self.assertEqual(metrics['costs']['failed'],{'quota':1}); self.assertEqual(metrics['costs']['measuredNewTokens'],262)
   self.assertEqual(metrics['costs']['missingUsage'],0)
if __name__=='__main__': unittest.main()
