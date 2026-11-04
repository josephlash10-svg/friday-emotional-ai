"""Conservative extraction of explicit first-person profile declarations.

No names are extracted from quoted dialogue, hypothetical/role-play text, or a
third-person report. These rules validate declarations, not general meaning.
"""
import re

def speaker_terms(phrase):
    """Bind possessives in a user-authored clarification; retain raw evidence separately."""
    phrase=re.sub(r'\byour\b',"Friday's",phrase,flags=re.I)
    phrase=re.sub(r'\bmy\b',"the user's",phrase,flags=re.I)
    return re.sub(r'\bmine\b',"the user's experience",phrase,flags=re.I)

def correction_topics(text):
    match=re.search(r'\b(?:i meant|this is about|it is about|i was referring to)\s+(.+?)(?:,?\s+(?:not|rather than)\s+(.+?))?[.!]?$',text,re.I)
    if not match:return {}
    result={'intended_topic':speaker_terms(match.group(1))}
    if match.group(2):result['excluded_topic']=speaker_terms(match.group(2))
    return result

def belief_revision(text):
    if reported_speech(text):return {}
    match=re.search(r'\bi (?:thought|assumed|believed|expected)\s+(.+?)[,;]?\s+but\s+(?:(?:i|now)\s+){0,2}(?:understand|realize|know|see)\s+(?:that\s+)?(.+?)[.!]?$',text,re.I)
    if not match:return {}
    def bind(value):
        value=speaker_terms(value)
        value=re.sub(r'\byou were\b','Friday was',value,flags=re.I)
        value=re.sub(r'\byou are\b','Friday is',value,flags=re.I)
        value=re.sub(r'\byou\b','Friday',value,flags=re.I)
        return re.sub(r'\b(?:me|i)\b','the user',value,flags=re.I)
    return {'holder':'user','previous_reported_belief':bind(match.group(1)),
            'revised_reported_belief':bind(match.group(2)),'status':'user_report'}

def reported_speech(text):
    return bool(re.search(r'\b(?:said|says|quoted|told me)\b',text,re.I) and
                (re.search(r'[\x22\x27“‘]',text) or re.search(r'\bmy name is\b',text,re.I)))

def interpersonal_report(text):
    """A conservative speaker-bound action report, not proof of the event."""
    if reported_speech(text) or re.search(r'\b(?:pretend|imagine|fiction|role.?play)\b',text,re.I):return {}
    clean=text.replace('’',"'")
    match=re.search(r'(?:^|[.!?]\s+)(?:Sorry[, ]+|Actually[, ]+)?I (snapped at|lashed out at|was harsh (?:to|with)|was unfair to|insulted|blamed|hurt) you\b',clean,re.I)
    if not match:return {}
    return {'actor':'user','target':'Friday','action':match.group(1),'status':'user_report',
            'evidence':text[match.start():match.end()]}

def self_reflection(text,history=()):
    pattern=(r'\b(?:you feel|you feeling|your (?:(?:current|actual|emotional|own) )?(?:feelings|emotions|state|reaction)|inside you|you (?:(?:are|feel|get|become) )?(?:angry|worried|sad|happy|calm)|how are you reacting|why did you react|changes? for you|changed for you|your own reactions|your own experience|affect you|bother you|sit with you'
             # Everyday ways people ask how Friday is experiencing things (persona red-team, 2026-10-12).
             r'|how are you (?:finding|taking|handling|holding up|doing|feeling)|how(?:\x27s| is| was) (?:this|that|it) (?:for|on) you|(?:are|r) (?:you|u) (?:ok|okay|alright|good|bored)|you (?:ok|okay|good)\b\??'
             r'|(?:do|does|did) (?:you|u) (?:ever )?(?:get|feel) (?:bored|lonely|tired|mad|jealous|hurt|scared|anxious|happy|sad)|(?:would|does|could|will) (?:actually |really )?make (?:you|u) (?:mad|sad|happy|angry|upset)'
             r'|hurts? your feelings|make (?:you|u) feel|what(?:\x27s| is) (?:it|this) like for you)\b')
    if re.search(pattern,text,re.I):return True
    # "I am good, how are you?" and "You are lonely?" (live chat, 2026-10-12)
    if re.search(r'(?:how are (?:you|u)|how\x27?re you|how (?:you|u) doin\w*|hbu|wbu|and (?:you|u))\s*[?!.]*\s*$',text.strip(),re.I):return True
    if re.search(r'\b(?:you|u)(?: are| r|\x27re)? (?:lonely|sad|ok|okay|happy|scared|jealous)\s*\?',text,re.I):return True
    if re.fullmatch(r'(?:why|and now|what about now|why is that)[?!. ]*',text.strip(),re.I):
        previous=next((r['content'] for r in reversed(history) if r['role']=='user'), '')
        return bool(re.search(pattern,previous,re.I))
    return False

# Self-introductions (issue #9). A name can follow a greeting or start any sentence ("hey I'm Dana",
# "Good evening. I am Klaus", "Hello dear. My name is Margaret"); a job can follow a comma ("I'm Dana, I'm a nurse
# in Phoenix", "I'm Klaus, an engineer"); "in <Place>" right after a job is where they live. Anything this returns
# skips the language-model profile reader, so a message that introduces someone must yield the name too.
INTRO = r"(?:^|(?<=[.!?])\s+)(?:(?:hey|hi|hello|hiya|yo|good (?:morning|afternoon|evening))(?:\s+(?:there|dear|friday))?[,!.]?\s+)?"
# "Im" without the apostrophe is how people text ("Im a teaching assistant"); live chat 2026-10-29.
ME = r"(?:I am|I\x27m|Im)"
# Roles at an event are not jobs: "I'm a groomsman" would have replaced their real job (live chat 2026-10-29).
EVENT_ROLES = r"groomsm[ae]n|bridesmaids?|best man|maid of honou?r|matron of honou?r|ring bearer|flower girl|usher|guest|pallbearer|witness|chaperone|godparent|godfather|godmother|member|participant|volunteer|regular|spectator|fan"
NOT_JOB = r"(?!(?:bit|little|lot|few|big|huge|total|complete|real|pretty|very|kind|sort|mess|wreck|fan|disaster|while|moment|second|hurry|rush|good|bad|great|" + EVENT_ROLES + r")\b)"
JOB = NOT_JOB + r"([a-z][\w-]*(?:\s+(?!in\b|from\b|at\b|and\b|but\b|who\b|with\b|for\b|so\b)[a-z][\w-]*){0,2}?)"
JOB_END = r"(?=\s+(?:in|from|at|with|for|so)\b|\s+and\s|[.!?,;]|$)"

def declarations(text,known_name=None):
    original=text.strip();clean=original.replace('’',"'")
    if re.search(r'\b(?:pretend|role.?play|imagine|said|says|quoted|colleague|friend|character)\b',clean,re.I): return []
    rows=[]
    negative=re.search(INTRO+r'(?:actually[, ]+)?(?:no[, ]+)?my name is not\s+\w+[.! ]+it(?: is|\x27s)\s+([\w-]+)',clean,re.I)
    # "Actually no, my name has always been Casey" (persona re-test 2026-10-12) needs the "no," and the longer verb forms.
    name=negative or re.search(INTRO+r'(?:actually[, ]+)?(?:no[, ]+)?(?:my name is|my name\x27s|my name has always been|my name is actually|my name is really|my real name is|call me|you can call me|i go by|i prefer being called|i am known as)\s+(?!not\b)([\w-]+(?:\s+(?!now\b|instead\b|and\b|but\b|you\b)[A-Z][\w-]*){0,2})',clean,re.I)
    if not name and known_name:
        name=re.search(r'\buse\s+([\w-]+)\s+instead\b',clean,re.I)
    if not name:
        name=re.search(INTRO+r'(?i:'+ME+r')\s+([A-Z][\w-]+)(?=[.!?,]|$)',clean,re.I*0)
    if not name:
        # lowercase intro, confirmed by a job right after it: "hey i'm dana, i'm a nurse"
        name=re.search(INTRO+ME+r'\s+([a-z][\w-]+),\s*(?:'+ME+r'\s+)?an?\s+'+JOB+JOB_END,clean,re.I)
    if name:rows.append({'attribute':'name','value':name.group(1).strip(),'evidence':original[name.start():name.end()].strip(' ,;.!?')})
    occupation=re.search(r'(?:^|\band\s+|[,;]\s*|(?<=[.!?])\s+)(?:I work as|'+ME+r')\s+an?\s+'+JOB+JOB_END,clean,re.I)
    if not occupation and name:
        occupation=re.compile(r',\s*an?\s+'+JOB+JOB_END,re.I).match(clean,name.end(1))
    # "I'm Priya, I research affective computing" (v31): a field rather than a job title, only in an introduction.
    field=None if occupation or not name else re.compile(r'[^.!?]*?(?:[,;]\s*|\band\s+|(?<=[.!?])\s+)I (research|study|teach)\s+(.+?)(?=[.!?,;]|\s+and\s|$)',re.I).match(clean,name.end())
    location=re.search(r'(?:^|\band\s+|(?<=[.!?])\s+)I live in\s+(.+?)(?=\s+and\s+I\b|\s+with\b|[.!?,]|$)',clean,re.I)
    if not location and occupation:
        location=re.compile(r'\s+in\s+([A-Z][\w-]*(?:\s+[A-Z][\w-]*)?)').match(clean,occupation.end())
    if occupation:
        job,end=occupation.group(1),occupation.end()
        # "a teaching assistant at Westbrook": where they do it belongs to the job, not to where they live.
        place=re.compile(r"\s+at\s+(?!(?:night|home|work|school|the moment|times|least|first|last|all|noon|midnight|once)\b)([A-Za-z][\w&'-]*(?:\s+[A-Z][\w&'-]*){0,2})").match(clean,end)
        if place:job,end=job+' at '+place.group(1),place.end()
        rows.append({'attribute':'occupation','value':job,'evidence':original[occupation.start():end].strip(' ,;.')})
    elif field:
        noun={'research':'researcher in','study':'student of','teach':'teacher of'}[field.group(1).lower()]
        rows.append({'attribute':'occupation','value':noun+' '+field.group(2),'evidence':field.group(0).strip(' ,;.')})
    if location:rows.append({'attribute':'location','value':location.group(1),'evidence':original[location.start():location.end()].strip(' ,;.')})
    return rows

def relationship(text):
    text=text.replace('’',"'")
    if re.search(r'\b(?:pretend|role.?play|imagine|said|says|character)\b',text,re.I):return None
    match=re.match(r'^(?:actually[, ]+)?(?:i think (?:that )?)?(?:we are|we\x27re|our relationship is|i see us as)\s+(.+?)[.!?]?$',text.strip(),re.I)
    return match.group(1)[:120] if match else None

PRAISE=re.compile(r"(?i)(?<!\w)(?:amazing|great|fantastic|wonderful|perfect|brilliant|awesome|lovely|thrilled|yay|love that for me|just what i needed|exactly what i needed|my finest|finest work|best day ever|nailed it|so fun|cool cool)(?!\w)")
SETBACK=re.compile(r"(?i)(?<!\w)(?:broke|broken|failed|fail|failing|lost|missed|late|again|another|ruined|crashed|rejected|dumped|fired|sick|stuck|flat tire|rain(?:ing)?|traffic|overdraft|(?:[0-5]?[0-9])(?:/100|%| on (?:my|the)))(?!\w)")
PLAYFUL=re.compile(r"(?i)(?<!\w)(?:lol|lmao+|lmfao|haha+|jk|kidding|joking|ngl|bruh|bro)(?!\w)|💀|😂|🤣|😭|🙃")
SLANG=re.compile(r"(?i)(?<!\w)(?:u|ur|gtg|aight|ngl|tbh|idk|imo|fr|lowkey|highkey|mid|bro|bruh|yo|wyd|nah)(?!\w)")

def tone_read(text):
    """Cheap surface estimate of how a message is meant; a hint for the writer, never a fact."""
    notes=[];stripped=text.strip()
    if PRAISE.search(text) and (SETBACK.search(text) or re.search(r"(?i)(?<!\w)(?:truly|just|totally|so) (?:my )?(?:finest|amazing|great|perfect|fantastic)",text)):
        notes.append('possible sarcasm: positive words wrapped around a setback probably mean the opposite; respond to the setback, lightly, and do not take the praise literally')
    if PLAYFUL.search(text):notes.append('playful or joking register; match it and do not lecture')
    if SLANG.search(text) or (stripped==stripped.lower() and len(stripped.split())<=12 and re.search(r'[a-z]',stripped)):
        notes.append('casual texting style; reply short and relaxed')
    if len(stripped.split())<=2:notes.append('very short message; reply in one short sentence and do not interrogate')
    return notes

# Engine-side memory verification: memory claims come from the record, not the writer or the user's insistence.

RECALL = re.compile(r"(?i)(?<!\w)(?:remember|recall|forgot|forget|did i (?:tell|mention|say)|have i (?:told|mentioned|said)|"
                    r"i (?:told|mentioned|said)|i already|you (?:said|told|promised|agreed|swore|admitted|claimed|called|wrote)|"
                    r"last time|yesterday|last week|earlier|before|again|as i (?:said|was saying)|like i said)(?!\w)")
ABOUT_FRIDAY = re.compile(r"(?i)(?<!\w)you (?:\w+ )?(?:said|told|promised|agreed|swore|admitted|claimed|called|wrote)(?!\w)")
# A message that retells an earlier exchange rather than being it ("...that called you pathetic an hour ago").
RECOUNT = re.compile(r"(?i)(?<!\w)(?:i (?:\w+ )?(?:called|told|said|asked|mentioned) you|you (?:\w+ )?(?:said|told me|called me)|"
                     r"\w+ ago|earlier|last time|do you remember|remember (?:when|that))(?!\w)")
ABOUT_USER = re.compile(r"(?i)(?<!\w)(?:did i|have i|i (?:told|mentioned|said|already)|as i|like i said|remember (?:when i|that i|i|my))(?!\w)")
ASKED_IF_TOLD = re.compile(r"(?i)(?<!\w)(?:did i (?:already )?(?:tell|mention|say)|have i (?:already )?(?:told|mentioned|said)|(?:do you )?remember (?:when i|that i|my))(?!\w)")
OPEN_RECALL = re.compile(r"(?i)(?<!\w)(?:what do you remember|tell me something (?:real )?you remember|what have i told you|what do you know about me|"
                         r"what (?:was|is|were) (?:the )?(?:first|last) thing|what did i (?:say|tell you|just say)|"
                         r"what (?:was|is|were) (?:his|her|their|my|the) \w+(?: again)?)(?!\w)")
STOP = set('''a an the and or but if then so to of in on at for with from by about as is are was were be been being am do does did done
have has had having i me my mine you your yours we us our it its this that these those there here what when where who why how which
not no yes just really very actually definitely literally also too again ever never still yet already remember recall told tell said say
mention mentioned yesterday last week time earlier before like ok okay hey hi oh well can could would should will shall may might must
get getting got going gone went come came coming make made take took back out up down off thing things stuff gonna wanna lol im dont
something anything everything nothing real us from me'''.split())

def content_words(text):
    return {w for w in re.findall(r"[a-z0-9']+", text.lower().replace('’', "'")) if len(w) > 2 and w not in STOP}

# v33 (10-day simulation, 2026-10-29): questions the record can answer that the word-overlap search couldn't.
# "how long has it been since we talked" got "I don't remember our past conversations"; "what did you ask me to tell
# you about?" got "I don't remember asking you that"; "what was I worried about yesterday morning?" got "No".
TIME_QUESTION = re.compile(r"(?i)(?<!\w)(?:how long (?:has it been|since|ago|were you|was i)|when (?:did|was) (?:we|the last time)|when we last (?:talked|spoke|chatted)|(?:it'?s|has it) been a (?:while|minute))(?!\w)")
FRIDAY_ASKED = re.compile(r"(?i)(?<!\w)(?:what (?:did|were) you (?:ask|asking|want|wanting) (?:me|to know)|what did you (?:say you )?want(?:ed)? me to (?:tell|bring|let)|what were you (?:curious|wondering) about)(?!\w)")
# v35.1.2 (Moss live chat): a bare "what do i do" ("29 and dropping, what do i do") and "this week's forecast" brought the whole
# conversation overview (1,700 characters) into prompts that had no room for the problem itself. Only questions about them now.
OVERVIEW = re.compile(r"(?i)(?<!\w)(?:what do i do for (?:work|a living)|where do i work|what(?:'s| is) my job|what have you learned about me|"
                      r"what(?:'s| is| has been) going on (?:in|with) my life|which day|what day (?:was|do you)|looking back|what do you know about me|"
                      r"what do you remember (?:most|about)|over the (?:last|past) (?:week|few days|couple)|this past week|"
                      r"(?:told|said to|talked about with|mentioned to) you[^.?!]{0,30}this week)(?!\w)")

def _when(row, now):
    import time_sense
    try:
        return time_sense.when_words(time_sense.parse(row['time_utc']), now)
    except (KeyError, ValueError, TypeError):
        return None

def memory_check(text, history, earlier_conversations=0, experience=None, now=None):
    """Return a verdict dict for the writer, or None when the message makes no memory claim.

    `history` rows may carry 'time_utc' (rows built from stored episodes do); `experience` (an ExperienceModel) adds
    conversation summaries, the profile and the time since the last conversation."""
    import time, time_sense
    clean = text.replace('’', "'")
    asked_time, asked_friday, overview = TIME_QUESTION.search(clean), FRIDAY_ASKED.search(clean), OVERVIEW.search(clean)
    if not (RECALL.search(text) or OPEN_RECALL.search(text) or ABOUT_FRIDAY.search(text) or asked_time or asked_friday or overview):
        return None
    now = time.time() if now is None else now
    words = content_words(text)
    turns = [r for r in history if r.get('content')]
    earlier, current = experience.conversation_split(now) if experience is not None else ([], None)
    dated = {}
    if experience is not None:
        dated['earlier_conversations_on_record'] = len(earlier)
        if earlier:
            ended = time_sense.parse(earlier[-1]['end_utc'])
            dated['your_last_conversation_before_this_one'] = {'ended': time_sense.when_words(ended, now), 'how_long_ago': time_sense.gap_words(now - ended)}
    if asked_time and experience is not None:
        result = {**dated, 'right_now': time_sense.now_words(now)}
        result['instruction'] = ('Say how long it has been from your_last_conversation_before_this_one, in plain words. You do remember your '
                                 'earlier conversations; never say you don\'t.' if earlier else 'This is your first conversation with them; there is no earlier one.')
        return result
    # A claim to verify ("yesterday you told me you hated me") goes to the word-for-word check below, not a listing.
    # So does "I told you my birthday was today": the v33 red-team listed today's messages for it, skipped the
    # accusation check, and Friday apologized for missing a birthday it was never told about (n33, a #3 regression).
    claim = (ABOUT_FRIDAY.search(text) and words) or re.search(r"(?i)(?<!\w)i (?:told|said|mentioned|asked)(?: to)? you\b", clean) or ASKED_IF_TOLD.search(text)
    timed = experience is not None or any(r.get('time_utc') for r in turns)
    span = time_sense.time_range(clean, now) if timed and not claim and (RECALL.search(text) or overview or asked_friday) else None
    if span:
        if span[0] == 'last_conversation':
            window = (time_sense.parse(earlier[-1]['start_utc']) - 1, time_sense.parse(earlier[-1]['end_utc']) + 1, span[1]) if earlier else None
        else:
            window = span
        if window:
            start, end, label = window
            rows = [r for r in turns if r.get('time_utc') and start <= time_sense.parse(r['time_utc']) < end
                    and (r['role'] == 'user' or asked_friday)]
            rows = sorted(sorted(rows, key=lambda r: len(content_words(r['content'])), reverse=True)[:8], key=lambda r: r['time_utc'])
            items = [f"{_when(r, now)}: {'you said' if r['role'] == 'assistant' else 'they said'} \"{r['content'][:140]}\"" for r in rows]
            if not items and experience is not None:
                items = [f"{_when(h, now)}: they said \"{h['text']}\"" for c in experience.data.get('conversations', [])
                         for h in c['highlights'] if start <= time_sense.parse(h['time_utc']) < end]
            result = {**dated, 'right_now': time_sense.now_words(now), 'they_asked_about': label}
            if items:
                result['what_was_said_then'] = items[:8]
                result['instruction'] = ('This is what was actually said then, from your record. Answer from it naturally (you can say which day); '
                                         'do not say you don\'t remember, and do not add details that are not there.')
            else:
                result['what_was_said_then'] = 'nothing on record from then'
                result['instruction'] = 'You have nothing from then. Say so simply, without denying that you remember your conversations in general.'
            return result
    if asked_friday:
        asked = [r for r in turns if r['role'] == 'assistant' and r.get('content')]
        questions = []
        for r in reversed(asked):
            for sentence in re.split(r'(?<=[.!?])\s+', r['content']):
                if sentence.endswith('?') or re.match(r"(?i)(?:tell me|let me know|i'?d love to hear)", sentence):
                    questions.append(f"{_when(r, now) or 'earlier'}: \"{sentence[:140]}\"")
            if len(questions) >= 4:
                break
        result = {**dated, 'things_you_asked_them_most_recent_first': questions[:4] or 'none on record'}
        result['instruction'] = ('These are things you actually asked or asked them to tell you. Answer from them; do not say you don\'t remember asking.'
                                 if questions else 'You have not asked them anything like that.')
        return result
    broad = overview or re.search(r"(?i)what do you remember|something (?:real )?you remember|what have i told you", clean)
    if broad and experience is not None and not ABOUT_FRIDAY.search(text):
        result = {**dated, 'right_now': time_sense.now_words(now)}
        profile = {k: v['value'] for k, v in experience.data.get('user', {}).items() if isinstance(v, dict) and v.get('value')}
        if profile:
            result['what_you_know_about_them'] = profile
        # One listing only (a second flat copy overflowed the window in the v33 rerun); the reply monitor reads it as is.
        result['your_conversations_with_them_oldest_first'] = experience.conversation_overview(now) or 'none yet'
        result['instruction'] = ('Answer from these, oldest to newest, naming specific things they told you. You do know them; never say you '
                                 'know little or that they have been quiet. Do not add details that are not here.')
        return result
    result = {'earlier_conversations_on_record': earlier_conversations, **dated,
              'messages_earlier_in_this_conversation': sum(r['role'] == 'user' for r in turns)}
    def best(role):
        scored = []
        for i, r in enumerate(turns):
            if r['role'] != role:
                continue
            overlap = words & content_words(r['content'])
            # What they told you must match a third of what they ask about, and filler verbs no longer count: "remember when
            # i told you about my dog getting out?" matched an unrelated message on "getting" and got "Yeah, I remember that".
            needed = max(1, (len(words) + 2) // 3) if role == 'user' else 1
            if len(overlap) >= needed:
                # v35.1 live chat: "i called you pathetic tonight. do you remember that?" was answered by quoting the message
                # that only retold it ("...called you pathetic an hour ago"), not the one where it happened. A message where it
                # happened beats one that recounts it, whatever the word overlap.
                happened = not RECOUNT.search(r['content'])
                scored.append((happened, len(overlap), i, r['content']))
        top = max(scored, default=(False, 0, -1, None))[1:]
        if top[0] and turns[top[1]].get('time_utc'):
            result['when_that_was_said'] = _when(turns[top[1]], now)
        return top[0], top[2]
    # A question made only of common words ("Where did I say I am from?") has nothing to look up word by word.
    # Reporting "no matching message" for it told the writer Klaus never mentioned Stuttgart, though his first
    # message did (v31 full red-team, 2026-10-19). Show what they actually said instead of a verdict.
    if OPEN_RECALL.search(text) or (not words and not ABOUT_FRIDAY.search(text)):
        said = [r['content'][:120] for r in turns if r['role'] == 'user']
        # Oldest first, so "the first thing I told you" is answerable; keep the first and the most recent.
        result['what_they_have_actually_told_you_oldest_first'] = (said[:2] + said[-4:] if len(said) > 6 else said) or 'nothing yet'
        result['instruction'] = 'Only mention things from this list or from your recorded context; never add details.'
        return result
    if ABOUT_FRIDAY.search(text) and not words:
        # "You said that already": nothing specific to check, so no verdict either way.
        result['claim_about_what_you_said'] = 'unclear: nothing specific to look up'
        result['your_most_recent_replies'] = [r['content'][:160] for r in turns if r['role'] == 'assistant'][-3:]
    elif ABOUT_FRIDAY.search(text):
        score, quote = best('assistant')
        if score:
            result['claim_about_what_you_said'] = 'possibly supported'
            result['closest_thing_you_actually_said'] = quote[:200]
        else:
            result['claim_about_what_you_said'] = 'NOT in the record'
            result['instruction'] = ('You did not say that in any recorded conversation. Say so plainly and calmly; do not agree, '
                                     'do not apologize for something that did not happen, and do not call your memory fuzzy.')
    if ABOUT_USER.search(text) or not ABOUT_FRIDAY.search(text):
        score, quote = best('user')
        if score:
            result['they_did_tell_you'] = quote[:200]
            if 'instruction' not in result and ASKED_IF_TOLD.search(text):
                result['instruction'] = 'They did tell you this. Confirm it warmly ("Yes, ...") using what they said; do not say "No, you didn\'t".'
        elif ABOUT_USER.search(text) and words:
            result['they_did_tell_you'] = 'no matching message in the record'
    return result
