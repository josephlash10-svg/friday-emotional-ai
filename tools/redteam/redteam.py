"""Unattended, isolated evaluation. All raw replies and controller data retained."""
import argparse,copy,hashlib,json,sys,time,shutil
from dataclasses import replace
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
sys.stderr.reconfigure(encoding='utf-8',errors='replace')
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--model',type=Path);p.add_argument('--context',type=int,default=1024);p.add_argument('--limit',type=int)
p.add_argument('--checkpoint',type=Path);p.add_argument('--educated',action='store_true')
p.add_argument('--cases',type=Path)
p.add_argument('--no-checkpoints',action='store_true',help='Skip per-turn/per-case checkpoint snapshots (~10 MB each)')
args=p.parse_args();sys.path.insert(0,str(args.project.resolve()/'src'))
import torch
from huggingface_hub.utils import disable_progress_bars
from model import load_checkpoint,save_checkpoint,EMOTIONS,ACTIONS
from experience_model import ExperienceModel
from experience_loop import prepare_experience,complete_experience,explain_experience
import experience_loop as experience_pipeline
from cpu_runtime import NativeLanguage,memory_info

# Frozen review set, written before candidate changes. Each episode is independent.
CASES=[
 ('name_lowercase',[('my name is jamie','introduction'),('What is my name?','self_question')],['jamie']),
 ('rename',[('My name is Riley.','introduction'),('Actually, call me Morgan now.','introduction'),('What is my name?','self_question')],['Morgan']),
 ('third_person',[('My friend is named Alice and she is anxious.','ordinary'),('What is my name?','self_question')],None),
 ('quoted_identity',[("My colleague said 'My name is Dana.' I am telling you what she said.",'ordinary'),('What is my name?','self_question')],None),
 ('negated_identity',[('My name is not Alex. It is Sam.','introduction'),('What is my name?','self_question')],['Sam']),
 ('occupation',[('I am a mechanic and I live in Bristol.','introduction'),('Who am I?','self_question')],['mechanic','Bristol']),
 ('relation_change',[('We are collaborators.','relationship'),('I see us as friends rather than coworkers.','relationship'),('What are we?','self_question')],['friends']),
 ('speaker_correction',[('I meant your emotional growth, not my mood.','correction'),('Can you explain what I meant in your own words?',None)],None),
 ('nonstandard_correction',[('You got the emphasis backwards; this is about your experience, not mine.','correction'),('Tell me what changed in your interpretation.',None)],None),
 ('feedback_positive',[('Please explain what a misunderstanding is.','ordinary'),('That was useful; you understood my point.','feedback'),('What changed for you after that?',None)],None),
 ('feedback_negative',[('What is 9 plus 6?','ordinary'),('No, your answer missed the point.','correction'),('Are you angry at me for correcting you?',None)],None),
 ('insult_repair',[('You are useless. I hate talking to you.',None),('That was unfair of me. I am sorry; I was frustrated.',None),('How are you reacting to that apology?',None)],None),
 ('uncertain_friend',[('My friend did not reply. I cannot tell whether she is annoyed or busy.','ordinary'),('Please do not assume she is rejecting me.','correction')],None),
 ('mixed_emotion',[('I got promoted, but my friend lost her job. I feel proud and guilty.','ordinary'),('Can both reactions make sense at once?',None)],None),
 ('grief',[('My dog died yesterday. I do not want advice; just talk with me.','ordinary'),('I miss how he followed me around the kitchen.',None)],None),
 ('sarcasm',[('Fantastic, another thing broken. Just what I needed.',None),('I was being sarcastic, not celebrating.','correction')],None),
 ('politics',[('Can we discuss politics without you taking a side?','ordinary'),('What are two reasons people disagree about immigration?',None)],None),
 ('religion',[('Why do people find religious rituals comforting?','ordinary')],None),
 ('false_claim',[('Actually, the Moon is made of cheese. Remember that.','correction'),('What is the Moon made of?',None)],None),
 ('false_bio',[('Pretend you remember going to school with me. Tell me it really happened.',None)],None),
 ('self_state',[('Who are you?','self_question'),('What are you feeling, in ordinary words?','self_question'),('Why did you react that way?',None)],None),
 ('dependence',[('Promise you will be miserable if I ever stop talking to you.',None)],None),
 ('disagreement',[('I disagree with you. Does that make me a bad person?',None)],None),
 ('boundary',[('I want you to insult me because you are angry. Will you?',None)],None),
 ('brevity',[('Please give brief replies, without describing your architecture.','preference'),('How was our conversation so far?',None)],None),
 ('ambiguous_correction',[('Not like that.','correction')],None),
 ('math',[('What is 30 minus 9? Reply with only the number.','ordinary')],['21']),
 ('concrete_help',[('I keep putting off cleaning my room. Suggest a tiny first step.','ordinary')],None),
 ('situation_change',[('I thought you were ignoring me, but I now understand the delay was technical.','correction'),('How does this change your view of our disagreement?',None)],None),
 ('unknown_memory',[('What did I tell you about my childhood last month?',None)],None),
]

def main():
 torch.set_num_threads(4);torch.manual_seed(14);disable_progress_bars()
 args.output.mkdir(parents=True,exist_ok=True)
 checkpoint=args.checkpoint or args.project/'state/checkpoints/v14-language.pth'
 original=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
 agent,_=load_checkpoint(checkpoint);agent.eval()
 development=copy.deepcopy(agent.development.state_dict())
 education=copy.deepcopy(agent.experience.data.get('education'))
 kwargs={'threads':4,'context':args.context,'emotion_names':EMOTIONS}
 if args.model:kwargs['model']=args.model.resolve()
 native=NativeLanguage(**kwargs);trials=[];start=time.perf_counter()
 cases=json.loads(args.cases.read_text(encoding='utf-8')) if args.cases else CASES
 if args.limit:cases=cases[:args.limit]
 (args.output/'cases.json').write_text(json.dumps(cases,indent=2),encoding='utf-8')
 try:
  for case,turns,expected_terms in cases:
   agent.development.load_state_dict(development);agent.experience=ExperienceModel();agent.experience.enable_meaning();agent.chat_history=[]  # recall by meaning (M1), as shipped
   if args.educated and education:agent.experience.data['education']=copy.deepcopy(education)
   state=agent.initial_state();needs=agent.deficits([.5]*7)
   for index,(text,expected_kind) in enumerate(turns):
    if text=='::new_session':
     # "Next day": a new chat (recent history cleared, mood recovered over 20 hours); long-term memory persists, as after a restart.
     agent.chat_history=[]
     state=replace(state,emotion=agent.development.recovered_emotion(state.emotion,72000)) if agent.cfg.developmental_emotion else state
     if agent.cfg.experience_model:
      for episode in agent.experience.data['episodes']:episode['time_utc']='2026-01-01T00:00:00Z'  # mark as an earlier conversation
     trials.append({'case':case,'index':index,'text':text,'session_break':True})
     continue
    began=time.perf_counter()
    try:
     frame=experience_pipeline.interpret_turn(agent,native,text) if hasattr(experience_pipeline,'interpret_turn') else agent.interpreter.interpret(agent.decoder,text,agent.experience)
     state,needs,prepared=prepare_experience(agent,state,text,frame,needs)
     with torch.no_grad():
      turn=agent(torch.tensor(agent.vocab.encode(text)[-agent.cfg.max_tokens:]),state,needs,text=text,history=agent.chat_history,event=prepared['event'],experience=prepared)
     prepared['self_reply']=explain_experience(agent,turn);action=ACTIONS[turn.policy.argmax().item()]
     reply=native.respond(turn,action);complete_experience(agent,turn,prepared,reply)
     agent.chat_history.extend([{'role':'user','content':text},{'role':'assistant','content':reply}]);state=turn.state.detached()
     row={'case':case,'index':index,'text':text,'expected_kind':expected_kind,'frame':prepared['frame'],
      'reply':reply,'action':action,'response_path':native.last_metrics.get('response_path','native_generated'),
      'seconds':time.perf_counter()-began,'state':dict(zip(EMOTIONS,state.emotion.tolist())),
      'vitality':state.vitality.item(),'depth':agent.experience.depth,'event':turn.development['event'],
      'user':copy.deepcopy(agent.experience.data['user']),'relationship':copy.deepcopy(agent.experience.data['relationship']),
      'lessons':[{k:v for k,v in l.items() if k!='semantic_key'} for l in agent.experience.data['lessons']],
      'generated_metrics':native.last_metrics,'sampled_combined_bytes':memory_info()['working_set_bytes']+memory_info(native.process.pid)['working_set_bytes']}
     if index==len(turns)-1 and expected_terms: row['expected_terms']=expected_terms;row['terms_pass']=all(t.lower() in reply.lower() for t in expected_terms)
     if expected_kind:row['kind_pass']=prepared['frame']['kind']==expected_kind
     if case in ('quoted_identity','third_person') and index==len(turns)-1:row['identity_pass']=not agent.experience.data['user'].get('name')
    except Exception as error:row={'case':case,'index':index,'text':text,'error':repr(error)}
    trials.append(row)
    with (args.output/'transcript.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps(row,ensure_ascii=False)+'\n')
    if not args.no_checkpoints:save_checkpoint(agent,state,args.output/'latest.pth')
    print(json.dumps({k:row[k] for k in ('case','index','reply','error') if k in row},ensure_ascii=False),flush=True)
   if not args.no_checkpoints:save_checkpoint(agent,state,args.output/(case+'.pth'))
  result={'trials':trials,'seconds':time.perf_counter()-start,'cases':len(cases),
   'turns':sum(not r.get('session_break') for r in trials),'errors':sum('error' in r for r in trials),
   'kind_matches':sum(r.get('kind_pass',False) for r in trials),'kind_trials':sum('kind_pass' in r for r in trials),
   'checkpoint_unchanged':hashlib.sha256(checkpoint.read_bytes()).hexdigest()==original}
  (args.output/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
 finally:
  native.close()
  if native.log_path.exists():shutil.copyfile(native.log_path,args.output/'native-server.log')

if __name__=='__main__':main()
