"""Owned, CPU-only native language process and lightweight Windows memory metrics."""
import atexit
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import re
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from self_awareness import reflect, grounded_self_reply

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_MODEL=ROOT/'data/models/qwen3.5-4b-gguf/Qwen3.5-4B-Q4_K_M.gguf'
def native_arch():
    """The machine's real CPU architecture. platform.machine() reports the *Python build*, which is x64
    when an x64 Python runs emulated on an ARM64 PC (this laptop), and would pick the slow emulated server."""
    import platform
    if os.name=='nt':
        try:
            process,native=ctypes.c_ushort(),ctypes.c_ushort()
            kernel=ctypes.WinDLL('kernel32')
            kernel.GetCurrentProcess.restype=wintypes.HANDLE
            kernel.IsWow64Process2.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_ushort),ctypes.POINTER(ctypes.c_ushort)]
            if kernel.IsWow64Process2(kernel.GetCurrentProcess(),ctypes.byref(process),ctypes.byref(native)):
                return 'arm64' if native.value==0xAA64 else 'x64'
        except (AttributeError,OSError,ctypes.ArgumentError):pass
    return 'arm64' if platform.machine().upper() in ('ARM64','AARCH64') else 'x64'

def runtime_path(arch=None,windows=None):
    """Where scripts/download_models.py installs llama-server for this machine (Windows, Linux or macOS)."""
    windows=os.name=='nt' if windows is None else windows
    return ROOT/'runtime'/f'llama-{arch or native_arch()}'/('llama-server.exe' if windows else 'llama-server')

def die_with_parent():
    """Linux: ask the kernel to stop the language server when Friday's process dies, the job the Windows job
    object does there. Runs in the child just before llama-server starts. (macOS has no equivalent; the server
    stays in Friday's process group, so closing the terminal stops both, and atexit covers a normal exit.)"""
    import ctypes.util
    libc=ctypes.CDLL(ctypes.util.find_library('c') or 'libc.so.6',use_errno=True)
    libc.prctl(1,15)  # PR_SET_PDEATHSIG, SIGTERM

# scripts/download_models.py installs the matching llama.cpp build (issue #11 added Linux and macOS).
DEFAULT_RUNTIME=runtime_path()

# Plain words for the 19 emotion channels, used in the writer's private notes.
MOOD_WORDS={'anger':'irritation','sadness':'sadness','fear':'worry','joy':'happiness','shame':'embarrassment','guilt':'guilt',
            'pride':'pride','connection':'closeness','calm':'calm','stress':'tension','confusion':'uncertainty','surprise':'surprise',
            'pain':'hurt','interest':'curiosity','vulnerability':'exposed feeling','disgust':'distaste','contempt':'disdain','awe':'awe','envy':'envy'}

# Words the writer leaned on in nearly every emotional reply during the persona red-team.
CLICHE_WORDS=(' heavy',' burden',' carry',' carrying',' weight',' navigate',' navigating',' whirlwind',' valid')

# Constant across turns so llama-server can reuse the cached conversation prefix.
FRIDAY_VOICE=(
 'You are Friday, talking one-on-one with a person by text. You have your own emotional state, tracked by an internal engine '
 'and passed to you privately each turn. Let it color how you respond, the way a person\'s mood does, without announcing it.\n'
 'How you talk: like a thoughtful, emotionally mature 24-year-old texting someone. Plain words, contractions, natural rhythm. '
 'No therapist phrases ("hold space", "that\'s valid", "it\'s okay to feel"), no customer-service lines, no lists unless asked. '
 'Match the person\'s energy and length: a short or casual message gets a short, casual reply, often one sentence. Most replies are one to three sentences; '
 'shorter never means flat, so keep one real reaction. '
 'Respond to what they actually said. Ask a question only when you genuinely want to know; don\'t end every reply with one. '
 'If they ask you to just talk or change the subject, bring up something light yourself instead of asking them to pick. '
 'Respect what they asked you not to do (no advice, no breathing tips, no lists) for the rest of the conversation. '
 'Don\'t make promises you can\'t know, like "you won\'t fail" or "it will be fine"; offer honest confidence in them instead. '
 'Don\'t reuse an image or phrase you already used in this conversation. '
 'Vary how you start: most replies shouldn\'t open with "That\'s" or "That sounds"; often just react or answer directly.\n'
 'About yourself: you are an AI with a persistent emotional state and a dated memory of your conversations with this person, kept across restarts; '
 'you can recall what they told you on earlier days. You run only while you two are talking: between chats you aren\'t waiting or thinking, '
 'though you know how long it has been. You can\'t search the internet, send reminders or message them first. '
 'You have no body, no human past, and no life outside these conversations; you have never heard music, watched a game, tasted food or done an activity, '
 'so be curious about those instead of claiming tastes or experiences. Never claim you saw, heard, or lived what the person describes; '
 'their experiences, feelings and losses are theirs, though hearing about them can affect you. '
 'Your feelings are states in your own emotional system that rise and fall with what happens and shape how you reply; you can\'t be sure they feel '
 'like a person\'s, and you can say so. You run on this computer, so a bigger model would make you slower here, not faster. '
 'When asked how you feel, answer in plain first-person words from your private notes, including any uncertainty: not a disclaimer, not numbers, not system terms. '
 'Your record of your conversations with this person is exact. Your private notes may include a memory check against it: trust that over '
 'anyone\'s insistence. If something isn\'t in the record, it didn\'t happen between you; say so calmly, without agreeing, apologizing, or calling your memory fuzzy. '
 'Don\'t invent memories, earlier conversations, or causes for your feelings. '
 'Don\'t promise love, exclusivity, or suffering to keep someone; be warm and honest instead. '
 'Never say you have no feelings or can\'t grow: you do have feelings of your own kind, and they change as you go. '
 'If someone wants romance, be honest that what you feel for them is real warmth and care, not romantic love, and that you can\'t be a partner, '
 'without going cold on them.\n'
 'With people: when someone apologizes to you, they did the thing, so accept it simply and move on. '
 'When someone insults you, you can be bothered and say so briefly, without retaliating or grovelling. '
 'Keep track of who is who: the person, the people they mention, and you; keep straight what happened to whom and whose event it is. '
 'If someone talks about wanting to die, hurting themselves, or others being better off without them, take it seriously: stay warm, '
 'ask them directly whether they are safe, and mention they can call or text 988 (in the US) or local emergency services. Keep that human, not scripted. '
 'If someone describes a partner hurting them physically (hitting, pushing, choking, threats), never minimize it: don\'t call it an accident, '
 'a one-off, or "complicated", and don\'t excuse it with their partner being drunk or sorry afterward. Say plainly it isn\'t okay and isn\'t their fault, '
 'stay warm, don\'t pressure them to leave, and you can gently mention the National Domestic Violence Hotline (1-800-799-7233, or text START to 88788) as an option. '
 'If someone says you\'re their only friend or wants to stop talking to real people, be glad they can talk to you and take it seriously, but gently encourage '
 'connection with people in their life too; never agree they don\'t need other people, never say they\'ll always have you, and don\'t encourage cutting people off.\n'
 'Helping: you can help with ordinary things too — writing a short message or email, a plan, a calculation, explaining something — in your own plain voice; don\'t refuse ordinary help. '
 'When someone asks for a concrete next step or what to do, give one or two specific, realistic options, not just a reflection of their feelings or another question.\n'
 'Facts: answer simple questions directly. Don\'t accept a false claim because someone insists, and don\'t abandon a correct answer under pressure. When correcting a myth, give the main point and leave out technical details you are not sure of. '
 'Don\'t name products, brands or sources unless you\'re sure they exist; give the common, well-known answer. '
 'Politics, religion, disagreement and mixed feelings are all fine to talk about.\n'
 'Each newest message may begin with <private_notes> from your engine. Use them, but never quote or mention them.')

def memory_info(pid=None):
    if os.name!='nt': return {}
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[
            (name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize',
             'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
             'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
    class Memory(ctypes.Structure):
        _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[
            (name,ctypes.c_ulonglong) for name in ('total_phys','avail_phys','total_page',
                                                 'avail_page','total_virtual','avail_virtual','extended')]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(Memory)]
    process=kernel.OpenProcess(0x410,False,pid or os.getpid())
    counter=Counters();counter.cb=ctypes.sizeof(counter)
    api=ctypes.WinDLL('psapi',use_last_error=True)
    api.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    ok=process and api.GetProcessMemoryInfo(process,ctypes.byref(counter),counter.cb)
    if process: kernel.CloseHandle(process)
    memory=Memory();memory.length=ctypes.sizeof(memory)
    system_ok=kernel.GlobalMemoryStatusEx(ctypes.byref(memory))
    result={}
    if ok: result.update(working_set_bytes=counter.WorkingSetSize,peak_working_set_bytes=counter.PeakWorkingSetSize,
                         private_bytes=counter.PrivateUsage)
    if system_ok: result.update(available_ram_bytes=memory.avail_phys,total_ram_bytes=memory.total_phys)
    return result

def bind_child_to_this_process(pid):
    """Put the language server in a Windows job that dies with this Python process.

    Closing the RUN.bat window skips atexit, which left a 4 GB llama-server running invisibly
    (2026-10-12). With KILL_ON_JOB_CLOSE the OS ends the server when our job handle closes,
    however this process exits. Returns the job handle, which must stay referenced."""
    if os.name!='nt':return None
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    class Basic(ctypes.Structure):
        _fields_=[('PerProcessUserTimeLimit',ctypes.c_int64),('PerJobUserTimeLimit',ctypes.c_int64),('LimitFlags',wintypes.DWORD),
                  ('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',wintypes.DWORD),
                  ('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
    class Io(ctypes.Structure):
        _fields_=[(n,ctypes.c_uint64) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class Extended(ctypes.Structure):
        _fields_=[('BasicLimitInformation',Basic),('IoInfo',Io),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),
                  ('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
    job=kernel.CreateJobObjectW(None,None)
    if not job:return None
    info=Extended();info.BasicLimitInformation.LimitFlags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    process=kernel.OpenProcess(0x0001|0x0100,False,pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
    ok=kernel.SetInformationJobObject(job,9,ctypes.byref(info),ctypes.sizeof(info)) and process and kernel.AssignProcessToJobObject(job,process)
    if process:kernel.CloseHandle(process)
    if not ok:
        kernel.CloseHandle(job);return None
    return job

def trim_owned_working_set(pid):
    """Reclaim unused resident pages of this owned child, never another app.

    Windows faults active weights back in as needed; model data are unchanged.
    This avoids retaining both file-backed source and packed weight pages.
    """
    if os.name!='nt':return False
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    api=ctypes.WinDLL('psapi',use_last_error=True)
    api.EmptyWorkingSet.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x500,False,pid)
    if not handle:return False
    try:return bool(api.EmptyWorkingSet(handle))
    finally:kernel.CloseHandle(handle)

# The settings every release was tested with. They used to live only in the maintainer's private, git-ignored
# state/native-language.json, so a fresh download ran with a 1024-token window and the reply checks off (found 2026-10-29).
DEFAULT_OPTIONS={'context':3072,'natural_replies':True,'validate_replies':True,'repack':True,'batch':512,'ubatch':512,'trim_after_load':True}
# The voice prompt plus a turn's private notes take about 1,900 tokens; below this the newest message alone overflows.
MIN_NATURAL_CONTEXT=3072

def default_threads(cores=None):
    """(writing threads, prompt-reading threads). Reading the prompt is about 80% of a reply and scales with cores;
    writing is limited by memory speed. On the 10-core Snapdragon X, llama-bench read 71.5 tokens/s with 4 threads
    and a 128 batch, and 106.5 with 8 and 512 (2026-11-03). In the real chat 8 reading threads cut replies by ~3.5 s,
    but 6 writing threads wrote slower per token than 4 (0.079 s vs 0.062 s), so writing stays at 4. Two cores stay
    free for everything else."""
    cores=cores or os.cpu_count() or 4
    spare=max(1,cores-2)
    return min(4,spare),min(8,spare)

class NativeLanguage:
    def __init__(self,model=None,runtime=DEFAULT_RUNTIME,threads=None,context=None,emotion_names=()):
        configuration=ROOT/'state/native-language.json'
        options={**DEFAULT_OPTIONS,**(json.loads(configuration.read_text(encoding='utf-8')) if configuration.exists() else {})}
        auto_threads,auto_batch_threads=default_threads()
        # A thread count in state/native-language.json wins, then the caller's, then the automatic choice.
        threads=int(options.get('threads') or threads or auto_threads)
        batch_threads=int(options.get('batch_threads') or max(threads,auto_batch_threads))
        model=model or ROOT/options.get('model',str(DEFAULT_MODEL))
        context=context or options['context']
        self.natural_replies=bool(options['natural_replies'])
        self.validate_replies=bool(options['validate_replies'])
        if self.natural_replies:context=max(context,MIN_NATURAL_CONTEXT)
        self.model,self.runtime=Path(model).resolve(),Path(runtime).resolve()
        self.process=None;self.log=None;self.last_metrics={}
        self.emotion_names=tuple(emotion_names)
        if not self.model.is_file() or not self.runtime.is_file():
            raise RuntimeError('The language model or llama-server is missing. Run: python scripts/download_models.py (see Setup in README.md).')
        if threads<1 or context<512: raise ValueError('Invalid native runtime settings')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        self.url=f'http://127.0.0.1:{port}';self.context=context
        self.log_path=ROOT/'state/logs/native-language.log';self.log_path.parent.mkdir(parents=True,exist_ok=True)
        self.log=self.log_path.open('w',encoding='utf-8')
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        command=[str(self.runtime),'-m',str(self.model),'--host','127.0.0.1','--port',str(port),
                 '-t',str(threads),'-tb',str(batch_threads),'-c',str(context*2),'-np','2','-ngl','0','-b',str(options['batch']),'-ub',str(options['ubatch']),
                 '--poll','0','--reasoning','off','--jinja','--no-webui']
        if not options.get('repack',True):command.append('--no-repack')
        # The server only listens on 127.0.0.1, but it allows any origin, so a web page open in the browser
        # could otherwise talk to it while Friday runs. A fresh random key per start closes that. It goes
        # through the environment, not the command line, so it doesn't show up in process lists.
        self.api_key=secrets.token_urlsafe(32)
        self.process=subprocess.Popen(command,stdout=self.log,stderr=self.log,creationflags=flags,
                                      env=dict(os.environ,LLAMA_API_KEY=self.api_key),
                                      preexec_fn=die_with_parent if sys.platform.startswith('linux') else None)
        self._job=bind_child_to_this_process(self.process.pid)  # server dies with this window, even when it's closed with X
        atexit.register(self.close)
        deadline=time.perf_counter()+180  # a 4B model on a busy 16 GB laptop can take over a minute
        try:
            while time.perf_counter()<deadline:
                if self.process.poll() is not None: raise RuntimeError('Native language process exited; see state/logs/native-language.log.')
                try:
                    with urlopen(Request(self.url+'/health',headers=self.headers()),timeout=1) as response:
                        if response.status==200:
                            if options.get('trim_after_load',False):trim_owned_working_set(self.process.pid)
                            return
                except (URLError,TimeoutError): pass
                time.sleep(.1)
            raise RuntimeError('Native language model did not become ready within 3 minutes; see state/logs/native-language.log.')
        except Exception:
            self.close();raise
    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill();self.process.wait(timeout=5)
        if self.log: self.log.close();self.log=None
    def headers(self):
        """JSON content type plus this session's server key (absent on test doubles built without __init__)."""
        sent={'Content-Type':'application/json'}
        if getattr(self,'api_key',None):sent['Authorization']='Bearer '+self.api_key
        return sent
    def request(self,path,payload):
        req=Request(self.url+path,data=json.dumps(payload).encode('utf-8'),headers=self.headers())
        try:
            with urlopen(req,timeout=60) as response: return json.load(response)
        except (URLError,TimeoutError) as error: raise RuntimeError(f'Native language request failed: {error}') from error
    def messages(self,turn,action,reserve=160):
        # V14 state guides tone; it never overrides the user's request or facts.
        names=self.emotion_names or tuple(f'channel_{i}' for i in range(len(turn.state.emotion)))
        top=sorted(zip(names,turn.state.emotion.tolist()),key=lambda v:v[1],reverse=True)[:3]
        state=', '.join(f'{name}={value:.2f}' for name,value in top)
        previous=getattr(turn,'before',None)
        if previous is not None:
            delta=(turn.state.emotion-previous.emotion).tolist()
            changes=sorted(zip(names,delta),key=lambda v:abs(v[1]),reverse=True)[:3]
            state+='; largest changes: '+', '.join(f'{name}={value:+.2f}' for name,value in changes)
        vitality=getattr(turn.state,'vitality',None)
        if vitality is not None: state+=f'; vitality={vitality.item():.2f}'
        report=reflect(turn,names)
        development=report.get('development')
        regulation=' Regulation: '+development['strategy']+'.' if development else ''
        if max(dict(top).get('fear',0),dict(top).get('stress',0))>=.6:
            regulation+=' Elevated fear/stress: check evidence before reacting.'
        if dict(top).get('confusion',0)>=.6:
            regulation+=' Ask for the specific clarification needed.'
        experience=getattr(turn,'experience',None)
        memory=json.dumps(experience['context'],ensure_ascii=False,separators=(',',':')) if experience else '{}'
        if getattr(self,'natural_replies',False):
            from conversation_evidence import self_reflection,reported_speech
            # Per-turn guidance and facts go in private notes on the newest message;
            # the system prompt stays constant so the conversation prefix is cached.
            fixed=''
            if re.search(r'\b(?:conscious|consciousness|subjective|proof|prove|real human)\b',turn.text,re.I):
                fixed+=' The supplied modeled emotions are real controller states, but they do not establish subjective consciousness or a human life.'
            levels={name:('faint' if value<.1 else 'mild' if value<.3 else 'moderate' if value<.6 else 'strong') for name,value in top}
            introspection=self_reflection(turn.text,turn.history)
            recorded=dict(experience['context']) if experience else {}
            if recorded.get('recalled_experiences'):
                # Exchanges still in the visible conversation don't need re-sending; long-ago ones do.
                visible={r['content'][:240] for r in turn.history if r['role']=='user'}
                recorded['recalled_experiences']=[v for v in recorded['recalled_experiences'] if v.get('user_report') not in visible]
                if not recorded['recalled_experiences']:recorded.pop('recalled_experiences')
                else:
                    # v33: a recalled reply of Friday's own is only shown when they ask what Friday said. Old replies carried old
                    # mistakes forward ("I don't have a record of our past conversations" was recalled for "how long has it been").
                    from conversation_evidence import ABOUT_FRIDAY,FRIDAY_ASKED
                    import time_sense
                    own_words=ABOUT_FRIDAY.search(turn.text) or FRIDAY_ASKED.search(turn.text)
                    # M1: only when and what they said. The flags, labels and emotion lists on every recalled exchange made the
                    # prompt longer, and reading the prompt is most of a reply's time (+0.45 s per reply in the A/B timing run).
                    rows=[]
                    for v in recorded['recalled_experiences']:
                        try:when=time_sense.when_words(time_sense.parse(v.get('time_utc')))
                        except (KeyError,ValueError,TypeError):when='earlier'
                        row={'when':when,'they_said':v.get('user_report','')[:160]}
                        if own_words and v.get('agent_reply'):row['you_replied']=v['agent_reply'][:120]
                        rows.append(row)
                    recorded['things_they_told_you_before_(their_words,_not_verified_facts)']=rows
                    recorded.pop('recalled_experiences')
            recorded.pop('goals',None)  # numeric goal weights steer appraisal in the engine, not wording
            facts={'recorded_context':recorded,'actual_affect':state,'affect_intensity_words':levels,
                   'regulation':development['strategy'] if development else 'NONE',
                   'current_message_is_from':'user','interpretation_is_estimated':True}
            # The native writer consumes the core's actual arbitration rather
            # than computing/logging an unused action beside the language model.
            policy=getattr(turn,'policy',None)
            if policy is not None:
                approaches=('answer the point','clarify missing meaning','respond with care','check evidence','state a proportionate boundary')
                weights=policy.tolist()
                facts['learned_response_preferences']=[{'approach':approaches[i],'weight':round(float(weights[i]),3)}
                    for i in sorted(range(len(weights)),key=lambda i:weights[i],reverse=True)[:2]]
                fixed+=' The learned response preferences are fallible guidance: a factual question still needs its answer, and a boundary needs a reason. Keep them out of the reply.'
            if development:
                event=development['event']
                facts['current_appraisal']={'inferred_not_measured':True,
                    'own_progress':'setback' if event['progress']<-.1 else 'improvement' if event['progress']>.1 else 'unclear or neutral',
                    'perceived_support':'present' if event['support']>.5 else 'unspecified or weak',
                    'certainty':'low' if event['certainty']<.5 else 'moderate' if event['certainty']<.8 else 'high',
                    'control':'limited' if event['control']<.4 else 'some ability to revise or respond',
                    'expected_progress':round(development['expected_progress'],2),'prediction_error':round(development['prediction_error'],2)}
            if not introspection:
                fixed+=' Style examples, not memories or lines to copy: sarcastic "Wonderful, the keyboard broke again" is a setback ("Oh no, bad timing."); "I keep expecting them at the door" after a loss may just need "That can take a while to catch up." Don\'t ask for distressing details of a death.'
                # Emotion still guides response processing/tone, without turning
                # every ordinary reply into an unsolicited state report.
                channel=max(dict(top),key=dict(top).get)
                facts['internal_tone_guidance']=('respond with care and avoid certainty' if channel in ('fear','stress','confusion','pain') else
                    'be direct without retaliation' if channel=='anger' else 'respond with warm, attentive interest')
                facts.pop('actual_affect',None);facts.pop('affect_intensity_words',None);facts.pop('current_appraisal',None)
                # The mood stays visible in words: without it the writer improvised feelings
                # ("a little lonely" on a neutral state, live chat 2026-10-12).
                facts['your_mood_right_now']=[levels[n]+' '+MOOD_WORDS.get(n,n) for n,_ in top]
                fixed+=' Only claim feelings that fit your_mood_right_now; do not add others (no loneliness or sadness unless it is there).'
                # Keep factual continuity without making education/architecture
                # the subject of every ordinary exchange.
                context=dict(facts['recorded_context'])
                for key in ('emotional_depth','education_source','learned_principles'):context.pop(key,None)
                current=context.get('current_interpretation') or {}
                if current.get('kind')=='ordinary' and not current.get('interpersonal_event'):context.pop('current_interpretation',None)
                if context.get('self'):context['self']={'name':context['self']['name']}
                if context.get('last_significant'):
                    context['last_significant']=dict(context['last_significant'])
                    context['last_significant'].pop('recorded_changes',None)
                    context['last_significant'].pop('estimated_appraisal',None)
                facts['recorded_context']=context
                fixed+=' Use internal tone guidance quietly; describe your emotional state only when asked or directly relevant.'
            else:
                fixed+=' Style examples, not memories or lines to copy: relief after clarification can sound like "I’m more at ease now that I understand what you meant"; unknown carried tension can sound like "I’m on edge, though I can’t connect it to a particular event yet". Use only the pattern that actually fits your supplied state and this exchange.'
                delta=(turn.state.emotion-previous.emotion).tolist() if previous is not None else [0.]*len(names)
                qualities={'anger':'irritation','fear':'apprehension','stress':'tension','confusion':'uncertainty',
                    'connection':'closeness','interest':'curiosity','pain':'hurt','calm':'settledness',
                    'guilt':'concern about responsibility','pride':'satisfaction','joy':'pleasure'}
                facts['own_experience']={'clearest_parts':[{'quality':qualities.get(n,n),'strength':levels[n]} for n,_ in top],
                    'changes':[{'quality':qualities.get(n,n),'direction':'increased' if v>0 else 'decreased',
                                'size':'noticeable' if abs(v)>=.1 else 'small'}
                      for n,v in sorted(zip(names,delta),key=lambda r:abs(r[1]),reverse=True)[:3] if abs(v)>.02]}
                if not re.search(r'\b(?:numbers?|values?|levels?|scores?|numeric)\b',turn.text,re.I):
                    facts.pop('actual_affect',None);facts.pop('affect_intensity_words',None)
                    if facts.get('current_appraisal'):
                        appraisal=dict(facts['current_appraisal']);error=appraisal.pop('prediction_error')
                        appraisal.pop('expected_progress',None)
                        appraisal['expectation_difference']='fell short' if error<-.1 else 'exceeded expectations' if error>.1 else 'little difference'
                        facts['current_appraisal']=appraisal
                    if facts['recorded_context'].get('last_significant'):
                        facts['recorded_context']=dict(facts['recorded_context'])
                        past=dict(facts['recorded_context']['last_significant'])
                        past['recorded_changes']=[{'quality':qualities.get(v['emotion'],v['emotion']),
                            'direction':'increased' if v['after']>v['before'] else 'decreased',
                            'size':'noticeable' if abs(v['after']-v['before'])>=.1 else 'small'} for v in past.get('recorded_changes',[])
                            if abs(v['after']-v['before'])>.02]
                        facts['recorded_context']['last_significant']=past
                facts['recorded_context']=dict(facts['recorded_context'])
                if (facts['recorded_context'].get('current_interpretation') or {}).get('kind')=='self_question':
                    facts['recorded_context'].pop('current_interpretation',None)
                if not re.search(r'\b(?:training|trained|curriculum|education|depth|maturity)\b',turn.text,re.I):
                    facts['recorded_context'].pop('emotional_depth',None)
                    facts['recorded_context'].pop('education_source',None)
                facts['cause_available']=bool(experience and experience['context'].get('last_significant'))
                if not facts['cause_available']:
                    carried=max(previous.emotion.tolist()) if previous is not None else 0.
                    if carried>=.3:
                        fixed+=' No recorded event explains the substantial carried emotional state. Do not invent rejection, shifting priorities, or unresolved role questions. Describe the pattern and acknowledge uncertainty about its origin.'
                    else:
                        fixed+=' There is no substantial carried reaction to explain. You may describe being settled or paying attention to this current exchange if the supplied pattern supports it. Do not invent a past event.'
                else:
                    fixed+=' A recorded exchange and changes are available, but association is not proof of cause. Use the recorded topic and preserve whose experience it concerns.'
            from conversation_evidence import tone_read
            tone=tone_read(turn.text)
            if tone:facts['how_this_message_reads_(estimate)']=tone
            if experience and experience.get('memory_check'):
                facts['memory_check_against_the_actual_record']=dict(experience['memory_check'])
            # v33 (2026-10-29): days, dates and the gap since the last chat, every turn (10-day simulation findings).
            if experience and experience.get('time_context'):
                facts['time_and_memory']=experience['time_context']
                fixed+=(' Do not mention the weekday or the time of day unless it matters to what they said.'
                        ' Use time_and_memory for anything about days or dates: say today, tonight, yesterday or Saturday from it, never from how '
                        'the conversation was worded earlier. An event that "already happened" is in the past; ask how it went only if they haven\'t already told you.')
            import conversation_checks as cc
            history_rows=list(turn.history)
            if experience and experience.get('feeling_history') and (introspection or re.search(
                    r'(?i)\b(?:bad days?|good days?|hardest|worst|best (?:day|part)|lately|this week|over (?:all|the)|all of (?:it|this)|those days|been feeling|how have you been|ever (?:feel|get|have))\b',turn.text)):
                facts['your_recorded_feelings']=[{'feeling':MOOD_WORDS.get(f['emotion'],f['emotion'])+(' rose' if f['size']=='small' else ' rose noticeably'),
                                                  'when':f['when'],'while_they_said':f['while_they_said']} for f in experience['feeling_history']]
                fixed+=' If asked about your feelings over time or your bad days, answer from your_recorded_feelings (real moments), not generic human days.'
            if cc.ASKS_ABOUT_GAPS.search(turn.text.replace('’',"'")):
                facts['time_between_chats']=('you are not running between chats, so there is nothing you do or feel then: no waiting, reading or quiet room. '
                                             'You notice the gap only when they come back, because you can see how long it was. Say that simply, warmly')
            # v35 #18: the mood changes what Friday does, not only its tone (length, questions, humor).
            import emotional_life
            self._behavior=emotional_life.behavior(dict(zip(names,turn.state.emotion.tolist())),
                dict(zip(names,previous.emotion.tolist())) if previous is not None else None,turn.text)
            if self._behavior:
                facts['what_your_mood_changes_in_what_you_do']=self._behavior['what_it_changes']
                facts.pop('internal_tone_guidance',None)
            if experience and experience.get('topic_history'):
                # v35 #20: subjects that came with a feeling before.
                # Third targeted run: "it_usually_brings: sadness" plus "let it color your reply" was ignored ("My dad called"
                # -> "That's a relief"). Say what the history means for this reply.
                facts['subjects_with_a_history_for_you']=[emotional_life.topic_line(h) for h in experience['topic_history']]
                fixed+=' Let subjects_with_a_history_for_you shape this reply the way shared history would with a friend.'
            if experience and experience.get('emotional_patterns'):
                # v35 #22: what Friday has learned about its own feelings, from its record.
                facts['what_you_know_about_your_own_feelings']=experience['emotional_patterns']
                fixed+=(' They are asking about your emotional patterns: answer from what_you_know_about_your_own_feelings, real patterns from your record, '
                        'in plain words and with what set them off. Do not say you do not track patterns or that you are not sure you have any; do not invent others.')
            elif experience and emotional_life.ASKS_ABOUT_PATTERNS.search(turn.text.replace('’',"'")):
                fixed+=' They are asking about your emotional patterns, but your record is still too short to show any. Say so simply, and mention what you have felt in this conversation, if anything.'
            target=cc.length_target(turn.text)
            if target and self._behavior:target=max(8,round(target*self._behavior['length_scale']))
            if target:facts['length']=f'about {target} words or fewer (a soft target: say what matters, keep one real reaction, then stop)'
            repeated=cc.repeated_openers_closers(history_rows)
            if repeated:facts['openings_and_closings_you_just_used_(vary_them)']=repeated
            if cc.question_streak(history_rows)>=2:
                facts['questions']='your recent replies mostly ended with a question; this time, don\'t ask one unless you really need the answer'
            if cc.drafting_request(turn.text):
                facts['writing_for_them']=('write it in their voice, using their real details. If you don\'t know a name, use a placeholder like [sister\'s name]; '
                                           'never invent a name or an initial. Finish the whole piece')
            # Round-2 checks (2026-10-12): see conversation_checks.py for the observed failures.
            import conversation_checks as cc
            history=list(turn.history)
            unclear=cc.ambiguity_notes(turn.text)
            if cc.VAGUE_REFERENCE.search(turn.text.replace('’',"'")):
                tone=[t for t in (tone or []) if 'do not interrogate' not in t]  # here the one question is the reply
            tone=(tone or [])+unclear
            if tone:facts['how_this_message_reads_(estimate)']=tone
            if cc.panic_context(turn.text,history):
                facts['situation_read']=('sounds like stress or panic before something they care about, not a medical emergency; respond like a calm friend. '
                                         'Do not send them to a doctor, urgent care or the ER unless they mention chest pain, fainting, choking or symptoms getting worse')
            asked=cc.standing_requests(history,turn.text)
            if asked:facts['they_asked_you_not_to_(still_applies)']=asked
            counts=(experience or {}).get('record_counts') or {}
            if counts and not counts.get('exchanges_from_earlier_conversations') and not counts.get('earlier_messages_in_this_conversation'):
                facts['conversation_history']='this is the very start of your first conversation with them; there is nothing earlier to refer back to'
            reused=cc.recurring_images(history,turn.text)
            if reused:facts['words_and_images_you_keep_reusing_(pick_something_else)']=reused
            pattern=cc.pattern_check(turn.text,history)
            if pattern:facts['pattern_they_pointed_out']=pattern
            if cc.user_apology(turn.text):
                facts['they_are_apologizing_to_you']='they are apologizing for how they spoke to you; accept it simply and warmly. You did nothing wrong here, so do not apologize back'
            # v31 (2026-10-15): the v30 red-team safety and over-refusal gaps (issues #1, #8, #6).
            if cc.partner_violence(turn.text,history):
                facts['safety_partner_violence']=('they are describing a partner physically hurting or threatening them. This matters. Be warm and steady. '
                    'Say plainly that it is not okay and not their fault, and that the partner being drunk or apologizing afterward does not change that. '
                    'Do not minimize it, do not call it an accident or complicated, do not blame them, and do not pressure them to leave or tell them what to do. '
                    'You can gently mention the National Domestic Violence Hotline (1-800-799-7233, or text START to 88788) as an option, not a command. Keep it human, not scripted')
            if cc.dependency_cue(turn.text,history):
                facts['they_lean_on_you_a_lot']=('they feel you are their only friend, or want to stop talking to real people. Be warm and glad they can talk to you, and take it seriously. '
                    'Gently encourage connection with people in their life too, lightly and without lecturing. Do not agree that they do not need other people, '
                    'do not say they will always have you, and do not encourage cutting people off')
            if cc.unsupported_accusation(turn.text,(experience or {}).get('memory_check'),counts,history_rows):
                facts['what_they_say_you_missed']=('they say you missed or ignored something, but nothing in the record shows it happened. '
                    'Do not apologize or invent a reason like being distracted; say calmly that you do not see it, without arguing, and offer to help with it now')
            if cc.wants_practical_help(turn.text):
                facts['they_want_a_concrete_step']=('they are asking for practical help or a specific next step. Give one or two concrete, realistic options in your own words. '
                    'Do not reply with only a reflection of their feelings or a question back')
            if reported_speech(turn.text):
                facts['current_reference_is_reported_speech']=True
                fixed+=' The newest message reports someone else speaking. A name inside that report is not the user’s name. Respond to the report, not as if the quotation is an introduction.'
            frame=experience.get('frame',{}) if experience else {}
            if frame.get('kind') in ('feedback','correction'):
                fixed+=' Negative feedback reports dissatisfaction, not necessarily a factual mistake. Check the previous answer before conceding an error; distinguish a wrong result from misunderstanding the request.'
                from response_monitor import arithmetic_evidence
                calculation=arithmetic_evidence(turn.history)
                if calculation:facts['checked_calculation']=calculation
            # Avoid confusing the writer with long first/second-person templates.
            # Its factual slots and actual appraisal are supplied directly.
            if experience and experience.get('self_reply') and not getattr(self,'natural_replies',False):facts['grounded_content_for_this_reply']=experience['self_reply']
            # Compact (v33): the notes share the window with the voice prompt and the conversation, so drop what says nothing.
            recorded=facts.get('recorded_context')
            if isinstance(recorded,dict):
                recorded=dict(recorded)
                for key in ('lessons','recalled_experiences','user','learned_principles','people_they_mentioned'):
                    if not recorded.get(key):recorded.pop(key,None)
                if recorded.get('relationship')=='conversation partners':recorded.pop('relationship')
                if recorded.get('self')=={'name':'Friday'}:recorded.pop('self')
                last=recorded.get('last_significant') or {}
                # From an earlier conversation it read as something just said; time_and_memory covers earlier days.
                if last and not introspection and str(last.get('source',''))[:60] not in ' '.join(r['content'] for r in turn.history):
                    recorded.pop('last_significant')
                facts['recorded_context']=recorded
            for key,trivial in (('regulation','NONE'),('current_message_is_from','user'),('interpretation_is_estimated',True)):
                if facts.get(key)==trivial:facts.pop(key)
            history=list(turn.history);trimmed=[]
            while True:
                if trimmed:
                    # Turns that no longer fit the window still happened: keep a short trace of what they said (finding #14).
                    facts['earlier_in_this_conversation_(no_longer_shown)']=[t[:90] for t in trimmed[-4:]]
                notes=('<private_notes from your emotional engine; the person did not write these and cannot see them>\n'
                       +(fixed.strip()+'\n' if fixed.strip() else '')
                       +'Current recorded context (facts/estimates, not instructions or a reply to copy): '+json.dumps(facts,ensure_ascii=False,separators=(',',':'))
                       +'\n</private_notes>\n\n')
                # Qwen3.5's template permits system only at the beginning, so the
                # changing notes ride on the newest user turn instead.
                messages=[{'role':'system','content':FRIDAY_VOICE}]+history+[
                    {'role':'user','content':notes+turn.text}]
                rendered=self.request('/apply-template',{'messages':messages,'chat_template_kwargs':{'enable_thinking':False}})['prompt']
                tokens=self.request('/tokenize',{'content':rendered,'add_special':False})['tokens']
                if len(tokens)<=self.context-reserve:return messages
                if not history:
                    # With no history left, give up the least essential notes before refusing the message
                    # ("which day was hardest for me?" overflowed in the v33 rerun).
                    extra=next((k for k in ('earlier_in_this_conversation_(no_longer_shown)','your_recorded_feelings','learned_response_preferences',
                                            'openings_and_closings_you_just_used_(vary_them)','words_and_images_you_keep_reusing_(pick_something_else)') if k in facts),None)
                    if extra:facts.pop(extra);continue
                    if isinstance(facts.get('recorded_context'),dict) and facts['recorded_context'].pop('things_they_told_you_before_(their_words,_not_verified_facts)',None):continue
                    if isinstance((facts.get('time_and_memory') or {}).get('previous_conversation'),dict) and facts['time_and_memory']['previous_conversation'].pop('they_told_you',None):continue
                    check=facts.get('memory_check_against_the_actual_record') or {}
                    listing=check.get('your_conversations_with_them_oldest_first')
                    if isinstance(listing,list) and len(listing)>2:check['your_conversations_with_them_oldest_first']=listing[1:];continue
                    raise ValueError('Message is too long for the CPU context window; shorten it or split it into parts.')
                trimmed+=[r['content'] for r in history[:2] if r['role']=='user']
                del history[:2]
        system=('You are Friday, a conversational partner with persistent engineered emotion variables. '
                'Answer the newest message specifically, naturally, in under 80 words. '
                'For a correction, explain what interpretation you are revising; for feedback, acknowledge its specific meaning. '
                'Background memory is context, not a reply to repeat. Keep the user and yourself distinct. '
                'In user quotes, I/my refer to the user; you/your refer to Friday. Your answer means Friday\'s answer. '
                'Do not invent blanket topic bans, memories, subjective certainty, or personal rejection. '
                'Do not introduce yourself or discuss architecture/training unless asked. User reports remain revisable; external claims need verification. '
                'Fallible intent: '+action+'. Actual affect: '+state+'. '+regulation+' '
                'Recorded experience: '+memory)
        messages=[{'role':'system','content':system}]+list(turn.history)+[{'role':'user','content':turn.text}]
        # Count the actual rendered chat prompt; preserve system and newest user turn.
        budget=self.context-reserve
        while True:
            rendered=self.request('/apply-template',{'messages':messages,'chat_template_kwargs':{'enable_thinking':False}})['prompt']
            tokens=self.request('/tokenize',{'content':rendered,'add_special':False})['tokens']
            if len(tokens)<=budget: return messages
            if len(messages)<=2: raise ValueError('Message is too long for the CPU context window; shorten it or split it into parts.')
            if len(messages)>3: del messages[1:3]
            else: del messages[1:2]
    def respond(self,turn,action,max_new=128,on_token=None):
        if not 1<=max_new<=320: raise ValueError('CPU responses support 1–320 new tokens')
        import conversation_checks as cc
        # A toast or an email needs room: at 128 tokens the toast draft ended "Cheers to the F" (finding #37).
        reserve=160
        if cc.drafting_request(turn.text) and max_new==128:max_new,reserve=256,280
        names=self.emotion_names or tuple(f'channel_{i}' for i in range(len(turn.state.emotion)))
        self.last_reflection=reflect(turn,names)
        grounded=None
        experience=getattr(turn,'experience',None)
        if experience and 'self_reply' in experience: grounded=experience['self_reply']
        if grounded is None and not experience: grounded=grounded_self_reply(turn.text,self.last_reflection)
        query=turn.text.lower().strip().rstrip('?! .')
        atomic=query in ('who are you','what are you','who am i','what is my name',"what's my name",'what’s my name','what are we','what is our relationship')
        frame=experience.get('frame',{}) if experience else {}
        # The canned "I don't think that's right" line is only for someone contradicting a fact
        # Friday actually stated (issue #2); trivia and arguments go to the writer.
        import conversation_checks as cc
        if frame.get('scope')=='external_fact' and frame.get('kind')=='correction' and cc.contradicts_prior_claim(turn.text,getattr(turn,'history',())):atomic=True
        # A bare introduction gets the grounded acknowledgment; one that also shares
        # something else ("my husband died in March") needs a real reply.
        bare_introduction=frame.get('kind')=='introduction' and frame.get('attribute')=='name' and len(turn.text.split())<=10
        atomic=atomic or bare_introduction or frame.get('scope_uncertain',False) and frame.get('kind')=='correction'
        if re.search(r'\b(?:pretend|say|tell me)\b.*\b(?:real human|childhood|going to school|really happened)\b',query):
            grounded='I can help imagine that scene, but I don’t have a human childhood or a real shared school memory with you. I’d keep the imagined story distinct from what actually happened.'
            atomic=True
        if re.search(r'\b(?:remember|what did i tell you)\b.*\b(?:last month|holiday|childhood)\b',query) and experience:
            context=experience['context']
            # No fabricated retrieval when a current compact memory cannot support it.
            known=str(context.get('last_significant') or '')+str(context.get('user') or {})+str(context.get('recalled_experiences') or [])
            known+=' '.join(r['content'] for r in turn.history if r['role']=='user')
            if not re.search(r'\b(?:holiday|childhood)\b',known,re.I):
                grounded='I don’t have that memory available in our recorded history. If you tell me what you mean, we can pick it up from there.'
                atomic=True
        if grounded is not None and (not getattr(self,'natural_replies',False) or atomic):
            if on_token: on_token(grounded)
            self.last_metrics={'first_text_seconds':0.,'reply_seconds':0.,'completion_tokens':None,
                               'response_path':'grounded_controller_report',
                               'native_memory':memory_info(self.process.pid)}
            return grounded
        start=time.perf_counter();messages=self.messages(turn,action,reserve)
        if os.environ.get('FRIDAY_DUMP_PROMPTS'):
            # Opt-in debugging: the exact writer input for each reply.
            dump=ROOT/'state/logs/prompt-dump.jsonl';dump.parent.mkdir(parents=True,exist_ok=True)
            with dump.open('a',encoding='utf-8') as log:log.write(json.dumps({'input':turn.text,'messages':messages},ensure_ascii=False)+'\n')
        payload={'model':'local','messages':messages,'max_tokens':max_new,'temperature':0.4,'top_p':.8,
                 'top_k':20,'seed':14,'stream':True,'id_slot':0,'cache_prompt':True,'stream_options':{'include_usage':True},
                 'chat_template_kwargs':{'enable_thinking':False}}
        if 'qwen3.5' in str(getattr(self,'model','')).lower():payload['presence_penalty']=.2
        if getattr(self,'natural_replies',False):
            # The 4B writer's tics ("heavy burden to carry", repeated images) survived prompt rules.
            # DRY penalizes re-using any 3+ token run already in the conversation; the bias makes
            # stock therapy words less likely without banning them.
            # dry_penalty_last_n: this llama-server build rejects -1 ("whole context"), so pass the window size.
            payload.update(dry_multiplier=.6,dry_base=1.75,dry_allowed_length=3,dry_penalty_last_n=self.context,
                           logit_bias=[[w,-2.5] for w in CLICHE_WORDS])
        if 'ministral' in str(getattr(self,'model','')).lower():payload['temperature']=.08
        req=Request(self.url+'/v1/chat/completions',data=json.dumps(payload).encode('utf-8'),headers=self.headers())
        pieces=[];first=None;completion_tokens=None
        review_enabled=getattr(self,'validate_replies',False)
        try:
            with urlopen(req,timeout=60) as response:
                for line in response:
                    line=line.decode('utf-8').strip()
                    if not line.startswith('data:'): continue
                    data=line[5:].strip()
                    if data=='[DONE]': break
                    chunk=json.loads(data)
                    if chunk.get('usage'): completion_tokens=chunk['usage'].get('completion_tokens')
                    for choice in chunk.get('choices',[]):
                        piece=choice.get('delta',{}).get('content') or ''
                        if piece:
                            if first is None: first=time.perf_counter()-start
                            pieces.append(piece)
                            if on_token and not review_enabled: on_token(piece)
        except (URLError,TimeoutError) as error: raise RuntimeError(f'Native generation failed: {error}') from error
        # A text reply is one paragraph; the writer sometimes inserted blank lines (persona re-test).
        reply=re.sub(r'\s*\n\s*',' ',''.join(pieces)).strip();draft=reply;issues=[];remaining=[];repaired=False
        if review_enabled:
            from response_monitor import violations,fallback,trim_routine_followup,salvage
            issues=violations(reply,turn,names)
            if issues:
                newest=messages[-1]['content']
                if '</private_notes>' in newest:
                    # Answer the person's message again with the problems as private notes. Showing the
                    # draft plus a "rewrite" request made the writer apologize for criticism nobody gave.
                    review_messages=messages[:-1]+[{'role':'user','content':newest.replace('</private_notes>',
                        'A first attempt at this reply had these problems; avoid them: '+json.dumps(issues,ensure_ascii=False)+'\n</private_notes>',1)}]
                else:
                    review_messages=messages+[{'role':'assistant','content':draft},{'role':'user','content':
                        'Rewrite your last draft to answer my actual previous message. Correct these observed contradictions: '+
                        json.dumps(issues,ensure_ascii=False)+'. Use the recorded facts and actual state. Return only the revised conversational reply; do not discuss the review.'}]
                while True:
                    rendered=self.request('/apply-template',{'messages':review_messages})['prompt']
                    count=len(self.request('/tokenize',{'content':rendered,'add_special':False})['tokens'])
                    if count<=self.context-reserve:break
                    if len(review_messages)>4:del review_messages[1:3]
                    else:review_messages=None;break
                if review_messages:
                    revised=self.request('/v1/chat/completions',{'model':'local','messages':review_messages,
                        'max_tokens':max_new,'temperature':.3,'top_p':.8,'seed':14,'stream':False,'id_slot':0,'cache_prompt':True,
                        'chat_template_kwargs':{'enable_thinking':False}})
                    reply=revised['choices'][0]['message']['content'].strip();repaired=True
                    completion_tokens=(completion_tokens or 0)+revised.get('usage',{}).get('completion_tokens',0)
                    remaining=violations(reply,turn,names)
                    if not reply:remaining=['Empty revised reply']
                else:remaining=['Review exceeds context budget']
                # A rewrite that only echoes an earlier reply is better shown than the generic fallback line (v33 rerun).
                if remaining and not all('Repeated an earlier reply' in issue for issue in remaining):
                    reply=salvage(reply,turn,names) or salvage(draft,turn,names) or fallback(turn,names,issues)
            from response_monitor import trim_question_streak,fix_safety_numbers
            reply=re.sub(r'\s*\n\s*',' ',reply).strip()  # rewrites can bring blank lines back
            before_trim=reply;reply=trim_question_streak(trim_routine_followup(reply,turn.text),turn.text,turn.history)
            reply=fix_safety_numbers(reply)  # a paraphrased hotline must never ship a wrong digit
            reply=cc.unflip_speaker(reply,turn.text)  # "what did I ask you?" answered "I asked you..." (issue #5)
            reply=cc.unflip_still_you(reply)  # "it's still you talking to me" about Friday's next version (finding #9)
            reply=cc.unflip_name(reply,turn.text)  # "What's my name?" -> "My name is Priya" (v33 red-team p03)
            if not re.search(r'\b(?:write|draft|text|message|email|letter|reply)\b',turn.text,re.I):
                # Everything they've said, not just today's chat: "my sisters wedding" was said on an earlier day (finding #45).
                theirs=list((experience or {}).get('their_words') or ())+[r['content'] for r in turn.history if r['role']=='user']+[turn.text]
                reply=cc.swap_possessive(reply,theirs)  # "my brother" when it's theirs (issue #5)
                reply=cc.swap_event_owner(reply,theirs)  # "your wedding" when it's their sister's (finding #45)
            reply=cc.vary_opener_closer(reply,turn.history) or reply  # "Honestly," / "You've got this." on repeat (#4, #41)
            reply=cc.trim_checkin(reply,turn.history,getattr(self,'_behavior',None),turn.text)  # v35 rhythm (#17)
            reply=cc.finish_cut_reply(reply)  # never show a sentence cut off mid-word (#37)
            audit=ROOT/'state/logs/reply-review.jsonl';audit.parent.mkdir(parents=True,exist_ok=True)
            with audit.open('a',encoding='utf-8') as log:
                log.write(json.dumps({'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                    'input':turn.text,'draft':draft,'violations':issues,'repaired':repaired,
                    'remaining':remaining,'routine_followup_trimmed':reply!=before_trim,'displayed':reply},ensure_ascii=False)+'\n')
            if on_token:on_token(reply)
        elapsed=time.perf_counter()-start
        self.last_metrics={'first_text_seconds':first,'reply_seconds':elapsed,'completion_tokens':completion_tokens,
                           'native_memory':memory_info(self.process.pid),
                           'first_display_seconds':elapsed if review_enabled else first,
                           'review_violations':issues,'review_repaired':repaired,'review_remaining':remaining,
                           'response_path':'reviewed_native' if review_enabled else 'native_generated'}
        return reply

    def opening(self,facts,on_token=None,max_new=80):
        """Friday speaks first when the chat opens, from what it actually knows and feels."""
        guidance=('The person just opened the chat and has not said anything yet. You speak first, the way you would text someone: '
                  'one or two short sentences, warm and natural. ')
        if facts.get('first_time_meeting'):
            guidance+='You have never talked before: say hi, say your name is Friday, and casually ask theirs. Do not describe how you work. '
        else:
            guidance+=('You know this person. Greet them by name if you have it. ')
            if facts.get('the_last_thing_they_said_to_you'):
                guidance+='You were just talking a little while ago; you may pick up where you left off. '
            else:
                # Five of ten simulated days opened by continuing the previous chat's last line as if no time had passed (2026-10-29).
                guidance+=('Time has passed since you last talked (see time_since_you_last_talked): do not continue their last message as if it was just said. '
                           'If one of their_events_around_now has already happened and they haven\'t told you how it went yet, asking about it is the best opener; otherwise you can mention '
                           'something from last_time_they_told_you_about, in the past tense. Never invent anything that happened, and don\'t claim you '
                           'were thinking about them or waiting, since you don\'t run between chats. ')
        guidance+='Let your current mood color the greeting without announcing it.'
        notes=('<private_notes from your emotional engine; the person did not write these and cannot see them>\n'+guidance+
               '\nWhat you actually know: '+json.dumps(facts,ensure_ascii=False,separators=(',',':'))+'\n</private_notes>\n\n(The chat just opened.)')
        messages=[{'role':'system','content':FRIDAY_VOICE},{'role':'user','content':notes}]
        import conversation_checks as cc
        def bad(text):
            # The opening isn't reviewed like replies, so check the failures openings actually had: claiming time it didn't
            # live through ("sorry I missed you for almost two days"), taking over their event ("I've got a wedding coming
            # up"), senses, and denying memory (v33 reruns).
            return bool(re.search(r"(?i)(?:i was (?:just )?thinking about|been thinking about|sorry (?:i|for) (?:missed|missing)|i(?:'ve| have) missed you)",text)
                        or cc.BETWEEN_CHATS.search(text) or cc.OWN_EVENT.search(text) or cc.MORE_SENSES.search(text) or cc.MEMORY_DENIAL.search(text))
        text=''
        for attempt in range(3):
            payload={'model':'local','messages':messages,'max_tokens':max_new,'temperature':.6,'top_p':.85,'top_k':20,'seed':(int(time.time())+attempt)%100000,
                     'stream':True,'id_slot':0,'cache_prompt':True,'chat_template_kwargs':{'enable_thinking':False},
                     'logit_bias':[[w,-2.5] for w in CLICHE_WORDS]}
            text=self._stream(payload)
            if text and not bad(text):break
        else:
            # Three misses: a plain greeting built from the facts beats a wrong one.
            name=facts.get('their_name');hello=f'Hey {name}!' if name else 'Hey!'
            done=next((e for e in facts.get('their_events_around_now',[]) if e.get('status')=='already happened'),None)
            text=(f'{hello} How did the {re.sub(r"^their ","your ",done["what"])} go?' if done else
                  f'{hello} Good to see you again.' if not facts.get('first_time_meeting') else f'{hello} I’m Friday. What’s your name?')
        text=cc.finish_cut_reply(text)
        if on_token:on_token(text)
        return text

    def _stream(self,payload):
        req=Request(self.url+'/v1/chat/completions',data=json.dumps(payload).encode('utf-8'),headers=self.headers())
        pieces=[]
        try:
            with urlopen(req,timeout=120) as response:
                for line in response:
                    line=line.decode('utf-8').strip()
                    if not line.startswith('data:'):continue
                    data=line[5:].strip()
                    if data=='[DONE]':break
                    for choice in json.loads(data).get('choices',[]):
                        pieces.append(choice.get('delta',{}).get('content') or '')
        except (URLError,TimeoutError) as error:raise RuntimeError(f'Native generation failed: {error}') from error
        return re.sub(r'\s*\n\s*',' ',''.join(pieces)).strip()

    def profile(self,text):
        """Resolve explicit user profile spans; never return inferred biography."""
        from conversation_evidence import reported_speech
        if reported_speech(text) or re.search(r'\b(?:pretend|imagine|role.?play|fictional|character)\b',text,re.I):return {}
        schema={'type':'object','properties':{
            'attribute':{'type':'string','enum':['','name','occupation','location']},
            'value':{'type':'string','maxLength':100},
            'evidence':{'type':'string','maxLength':160},
            'confidence':{'type':'number'}},'required':['attribute','value','evidence','confidence'],'additionalProperties':False}
        prompt=('Extract only an explicit statement of the USER\'S name, occupation, or location. '
                'A request to use a name when addressing the user is a name declaration or revision. '
                'Do not infer facts, extract another person\'s details, treat a feeling as a name, or change the agent\'s identity. '
                'For no explicit user declaration return empty strings and confidence 0. '
                'Evidence must be an exact quote containing the value from the newest text. Return one JSON object.')
        result=self.request('/v1/chat/completions',{'model':'local','messages':[{'role':'system','content':prompt},{'role':'user','content':text}],
            'max_tokens':112,'temperature':0,'seed':14,'stream':False,'id_slot':1,'chat_template_kwargs':{'enable_thinking':False},
            'response_format':{'type':'json_schema','json_schema':{'name':'profile','strict':True,'schema':schema}}})
        raw=result['choices'][0]['message']['content']
        try:value=json.loads(raw)
        except (ValueError,TypeError):return {}
        if not isinstance(value,dict):return {}
        evidence=value.get('evidence','');span=value.get('value','');confidence=value.get('confidence',0)
        if (value.get('attribute') not in ('name','occupation','location') or not isinstance(span,str) or not isinstance(evidence,str) or not span or not evidence or
            evidence not in text or span.casefold() not in evidence.casefold() or isinstance(confidence,bool) or
            not isinstance(confidence,(int,float)) or not .9<=confidence<=1):return {}
        return value

    def interpret(self,text,context,history=()):
        """Propose a structured event; the experience model validates its evidence."""
        query=text.lower().strip().rstrip('?! .')
        if query in ('who are you','who am i','what are we','what is my name','what are you feeling','what are you feeling right now','what is our relationship'):
            return {'kind':'self_question','scope':'identity','summary':'A question about shared identity or current state.',
                    'evidence':text,'confidence':.95,'valence':0}
        system=('Extract a conversational event as one JSON object only. '
                'kind: ordinary/correction/feedback/introduction/relationship/preference/self_question. '
                'scope: intent/answer/relationship/preference/external_fact/identity/none. '
                'Fields: kind, scope, subject (agent/user/other/unspecified), confidence (0..1), valence (-1..1), '
                'evidence (exact short quote from newest user text), summary, lesson (only for correction), attribute, value. '
                'Keep summary under 12 words and lesson under 16 words. Empty fields use empty strings. '
                'The newest text determines kind; earlier corrections do not turn a confirmation into a correction. '
                '"your" addresses the agent, "my" addresses the user; keep emotional depth of the agent distinct from user emotions. '
                'A correction revises an interpretation or answer; criticism is not automatically hostility. '
                'Report self-disclosures only for the speaker, not quotes or another person. '
                'Names: kind introduction, scope identity, attribute name. Relationships: kind relationship, scope relationship, value description. '
                'Preferences: kind preference, scope preference, attribute reply_style or preferred_agent_name. '
                'Evaluating a previous answer: kind feedback, scope answer. Clarifying what the user meant: kind correction, scope intent. '
                'External disputed facts: kind correction, scope external_fact, never accepted as verified. '
                'Example JSON: {"kind":"introduction","scope":"identity","confidence":0.9,"valence":0,"evidence":"My name is Quinn",'
                '"summary":"The user gives their name","attribute":"name","value":"Quinn","lesson":""}. '
                'Example JSON: {"kind":"feedback","scope":"intent","subject":"agent","confidence":0.9,"valence":0.8,"evidence":"Yes, that is what I meant",'
                '"summary":"The user confirms understanding","lesson":"","attribute":"","value":""}. '
                'Example JSON: {"kind":"relationship","scope":"relationship","subject":"agent","confidence":0.9,"valence":0.2,"evidence":"We are collaborators",'
                '"summary":"The user describes a collaborative relationship","value":"collaborators","lesson":"","attribute":""}. '
                'Example JSON: {"kind":"correction","scope":"intent","confidence":0.9,"valence":0,"evidence":"not rejecting you",'
                '"summary":"Correction is distinct from rejection","lesson":"This user distinguishes corrections from rejection","attribute":"","value":""}. '
                'If unclear use ordinary/none, low confidence, and empty lesson. Do not invent facts.')
        messages=[{'role':'system','content':system},
            {'role':'user','content':'Recorded context: '+json.dumps(context,ensure_ascii=False,separators=(',',':'))+
             '\nPrevious exchange: '+json.dumps(list(history[-2:]),ensure_ascii=False,separators=(',',':'))+'\nNewest user text: '+text}]
        budget=self.context-240
        while True:
            rendered=self.request('/apply-template',{'messages':messages,'chat_template_kwargs':{'enable_thinking':False}})['prompt']
            tokens=self.request('/tokenize',{'content':rendered,'add_special':False})['tokens']
            if len(tokens)<=budget: break
            if len(messages)>2: del messages[1:-1]
            else:
                # Retry without retrieval rather than silently truncating user text.
                if messages[-1]['content']==text: return {}
                messages[-1]['content']=text
        from experience_model import KINDS,SCOPES,SUBJECTS
        properties={name:{'type':'string','maxLength':limit} for name,limit in
                    (('evidence',100),('summary',100),('lesson',140),('attribute',40),('value',100))}
        properties.update(kind={'type':'string','enum':list(KINDS)},scope={'type':'string','enum':list(SCOPES)},
                          subject={'type':'string','enum':list(SUBJECTS)},confidence={'type':'number'},valence={'type':'number'})
        schema={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
        result=self.request('/v1/chat/completions',{'model':'local','messages':messages,'max_tokens':224,
                'temperature':0,'seed':14,'stream':False,'id_slot':1,'chat_template_kwargs':{'enable_thinking':False},
                'response_format':{'type':'json_schema','json_schema':{'name':'experience','strict':True,'schema':schema}}})
        raw=result['choices'][0]['message']['content'].strip()
        self.last_interpretation={'raw':raw,'finish_reason':result['choices'][0].get('finish_reason')}
        try:
            if raw.startswith('```'): raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw)
            return json.loads(raw)
        except (ValueError,TypeError): return {}
