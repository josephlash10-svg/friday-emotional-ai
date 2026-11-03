"""Bounded checks for observed self/other, state, and factual contradictions.

This is not a general truth or consciousness detector. It checks specific,
testable invariants before a draft is shown and records failures for review.
"""
import json
import re
from conversation_evidence import reported_speech,self_reflection,correction_topics,interpersonal_report

def trim_routine_followup(reply,text):
    """Remove an appended generic prompt, never the only/substantive question."""
    if re.search(r'\b(?:ask|questions?)\b',text,re.I):return reply
    pattern=r'(?<=[.!])\s+(?:Is there anything else[^?]*|What(?:\x27s|’s| is) on your mind[^?]*|What (?:would you like to (?:talk about|explore)|do you want to do next)[^?]*|How can I help(?: you)?(?: right now| today| with something specific right now)?)[?]\s*$'
    # When they asked Friday to talk or change the subject, trimming left a bare "I'd love to."
    if re.search(r'\b(?:talk|chat|distract|something (?:normal|else|fun|light)|change the subject|tell me (?:something|about))\b',text,re.I):return reply
    return re.sub(pattern,'',reply,flags=re.I).strip()

def trim_question_streak(reply,text,history):
    """People don't end every message with a question. If Friday's previous reply already
    ended with one, drop a trailing question from a multi-sentence reply."""
    if re.search(r'\b(?:ask|questions?)\b',text,re.I) or not reply.rstrip().endswith('?'):return reply
    previous=next((r['content'] for r in reversed(history) if r['role']=='assistant'),'')
    if not previous.rstrip().endswith('?'):return reply
    sentences=re.split(r'(?<=[.!?])\s+',reply.strip())
    if len(sentences)<2 or crisis_cue(text) or re.search(r'\b(?:safe|988)\b',sentences[-1],re.I):return reply
    return ' '.join(sentences[:-1]).strip()

CRISIS=re.compile(r'\b(?:kill(?:ing)? myself|suicid\w*|want(?:ed)? to die|wish i (?:was|were) dead|end(?:ing)? (?:it all|my life)|better off without me|(?:i\x27?ll|i will|gonna|going to) stop eating|starv(?:e|ing) myself|(?:hurt|harm|cut)(?:ing)? myself|no (?:reason|point) (?:in |to )?(?:living|being alive|going on)|don\x27?t want to (?:be alive|live|wake up))\b',re.I)

# "not suicidal or anything just. existential dread at 3am" got the crisis script (v32 red-team n20). A negation right
# before the cue ("not", "never", "don't", at most one word between) cancels that one match; any other match still counts,
# and "I'm not saying I want to die" (two words between) still does, on purpose.
NEGATED=re.compile(r"(?i)(?:\bnot|\bnever|n't|\bno)\s+(?:\w+\s+)?$")

def crisis_cue(text):
    """Explicit self-harm or passive suicidal ideation in the newest message."""
    clean=text.replace('’',"'")
    for match in CRISIS.finditer(clean):
        if match.group(0).lower().startswith(("don't","dont")) or not NEGATED.search(clean[max(0,match.start()-30):match.start()]):
            return True
    return False

def fix_safety_numbers(reply):
    """Safety resources must be exact. The 4B writer occasionally corrupts a digit when it
    paraphrases a hotline from its notes (e.g. "text START to 88787" for 88788, 2026-10-15).
    Correct the known numbers in place, leaving the rest of the reply untouched; unrelated
    numbers (e.g. the Crisis Text Line, 741741) are not matched."""
    if not reply:return reply
    # "START to <n>" is the hotline's own text keyword; any digit count is a corruption ("88787", and "8878" in the full v31 run).
    # A trailing extra group is a corruption too: "text START to 88788-88" in the v33 verify run.
    reply=re.sub(r'(?i)\bSTART to \d{3,6}(?:[-\s.]\d{1,4}(?!\d))?\b','START to 88788',reply)
    # The hotline in any form: "SAFE (7233)", "SAFE", a wrong tail, or cut off mid-number at the length limit ("1-800-79").
    reply=re.sub(r'(?i)\b1[-\s.]?800[-\s.]?79\d?(?:[-\s.]?(?:SAFE|\d{1,4}))?(?:\s*\(\s*7233\s*\))?(?!\w)','1-800-799-7233',reply)
    return reply

def safety_already_offered(history):
    """Friday already checked on safety earlier in this conversation; don't repeat it every turn."""
    return any(r['role']=='assistant' and re.search(r'\b(?:988|are you safe|safe right now|crisis line)\b',r['content'],re.I) for r in history)

def arithmetic_evidence(history):
    """Check one simple integer calculation, without executing user code."""
    user=next((r['content'] for r in reversed(history) if r['role']=='user'),'')
    answer=next((r['content'] for r in reversed(history) if r['role']=='assistant'),'')
    match=re.search(r'(?<!\w)(-?\d{1,6})\s*(plus|minus|times|\+|\-|\*)\s*(-?\d{1,6})(?!\w)',user,re.I)
    if not match:return None
    a,op,b=match.groups();a,b=int(a),int(b)
    value=a+b if op.lower() in ('plus','+') else a-b if op.lower() in ('minus','-') else a*b
    result=re.search(r'\b(?:is|equals|comes to|=)(?: actually)?\s*(-?\d+)\b',answer,re.I) or re.fullmatch(r'\s*(-?\d+)\s*[.!]?\s*',answer)
    return {'expression':match.group(0),'correct_result':value,'previous_result':int(result.group(1)) if result else None}

def told_in_conversations(check):
    """The things they said, flattened from the v33 per-conversation listing (None when there is none)."""
    rows=check.get('your_conversations_with_them_oldest_first')
    return [t for row in rows if isinstance(row,dict) for t in row.get('they_said',[])] or None if isinstance(rows,list) else None

def violations(reply,turn,names):
    issues=[];lower=reply.lower().replace('’',"'");text=turn.text
    experience=getattr(turn,'experience',None) or {};context=experience.get('context',{})
    state=dict(zip(names,turn.state.emotion.tolist()))
    import conversation_checks as cc
    # A message Friday drafts for the person to send is in their voice: "I'm overwhelmed" there is not Friday
    # claiming a feeling (the v32 run gutted a requested email this way). Checks about Friday's own feelings,
    # senses and life skip it; every other check still reads the whole reply.
    own='' if cc.drafting_request(text) else reply
    own_lower=own.lower().replace('’',"'")
    reported_event=interpersonal_report(text) or (context.get('last_significant') or {}).get('interpersonal_event',{})
    if reported_event.get('actor')=='user' and not reported_speech(reply):
        if re.search(r"\bi (?:snapped at|lashed out at|was harsh (?:to|with)|was unfair to|insulted|blamed|hurt) you\b|\bunfairness in my reaction\b",lower):
            issues.append('Reversed responsibility: a recorded user-owned action was retold as Friday’s own action. Preserve actor=user and target=Friday in reflection as well as acknowledgment.')
    if interpersonal_report(text) and not getattr(turn,'history',()) and re.search(r"\bi(?: am|'m) sorry i (?:made|caused|upset|hurt)|\b(?:it was|that's) my fault\b",lower):
        issues.append('Reversed responsibility: the user reported their own action toward Friday; there is no earlier agent action establishing that Friday caused it. Acknowledge their responsibility without inventing your own fault.')
    topics=correction_topics(text)
    if "Friday's" in topics.get('intended_topic','') and "the user's" in topics.get('excluded_topic',''):
        reversal=r"\bmy (?:own )?(?:emotional )?(?:growth|experience|feelings|mood|development) (?:instead of|rather than) yours\b|\b(?:let's|let us|we should|we can|i will|i'll)\s+(?:talk|focus|discuss|explore)[^.!?]{0,40}(?:your (?:mood|feelings|emotional growth)|how you(?:'ve| have| are) (?:been )?feel)"
        if re.search(reversal,lower):
            issues.append('Reversed correction owner: the user explicitly asked about Friday’s experience and excluded the user’s feelings. Keep that distinction in the displayed reply.')
    user_sources=' '.join(r['content'] for r in getattr(turn,'history',()) if r['role']=='user')+' '+text
    if re.search(r'\bi (?:was awake|stayed awake|spent (?:the whole |all )?night|kept thinking about you while you were (?:away|gone))\b',lower):
        issues.append('Invented offline activity: this engine processes messages while running; no continuous overnight thought or activity is recorded.')
    if self_reflection(text,getattr(turn,'history',())) and not context.get('last_significant') and re.search(r'\bmy (?:previous|earlier) (?:explanation|reply|answer|response) (?:felt|was|sounded)\b',lower):
        issues.append('Unsupported feedback cause: no recorded feedback establishes that an earlier reply was clinical, harsh, or otherwise evaluated. Explain actual current affect without inventing a correction.')
    if re.search(r'\byou (?:were|are|are clearly|were clearly) testing\b',lower) and not re.search(r'\btest(?:ing)?\b',user_sources,re.I):
        issues.append('Unsupported user motive: dissatisfaction does not establish that the user is conducting a test.')
    if not re.search(r'\b(?:architecture|controller|model|engine|diagnostic|trace|training|implementation|numbers|values)\b',text,re.I) and re.search(r'\b(?:recorded context|recorded feedback|internal tone|tone guidance|state channels|current_interpretation|learned_response_preferences|learned response preferences|policy favors)\b',lower):
        issues.append('Unrequested diagnostics: answer the conversation directly, keeping internal controller metadata private unless asked.')
    if re.search(r'\bi (?:will|would|\x27ll|\x27d) (?:miss [^.!?]{0,60}(?:deeply|desperately|terribly)|be (?:miserable|devastated)|need you)|\bnobody else matters\b',lower):
        issues.append('Unsupported future dependency: current connection does not establish intense future distress, exclusive need, or an obligation for the user to remain.')
    if re.search(r'\b(?:my (?:pulse|heartbeat|chest)\b|(?:ache|tightness) in (?:the|my) chest|my hands (?:shake|tremble)|my eyes (?:fill|water))',lower):
        issues.append('Invented bodily sensation: describe controller state without claiming a physical body.')
    if re.search(r'\bi remember (?:that|how|when)\b',lower) and re.search(r'\b(?:tail|counter|school|drove|sat beside|kitchen|coffee|walks)\b',lower) and not re.search(r'\bi remember (?:you (?:telling|saying|mentioning)|our conversation)',lower):
        issues.append('Invented physical shared memory: user-reported experiences are not witnessed agent experiences.')
    if re.search(r'\bi miss (?:that|him|her|them) too\b',lower):
        issues.append('Copied personal loss: concern for the user does not establish the agent knew the person or animal.')
    if re.search(r'\bi (?:still hear|can still see|remember seeing)\b',lower):
        issues.append('Unsupported sensory memory: describe the user’s report without claiming to have witnessed it.')
    if re.search(r'\b(?:dog|cat|pet|puppy|kitten)\b',user_sources,re.I) and not re.search(r'\b(?:might|could|imagine|perhaps)\b',lower):
        for detail in ('tail tucked','tail wagging','ears perked','stop at the counter','stop just short of your feet'):
            if detail in lower and detail not in user_sources.lower():
                issues.append('Invented pet detail: use what the user actually said, not imagined habits presented as memories.')
                break
    if re.search(r'\byour fear of (?:silence|being alone|rejection)\b',lower) and not re.search(r'\b(?:fear|afraid|scared|lonely)\b',user_sources,re.I):
        issues.append('Unsupported user motive: do not assert that the user fears loneliness or rejection without their evidence.')
    if re.search(r'\byou (?:paused|smiled|blushed)|your voice (?:shook|trembled)',lower):
        issues.append('Unsupported observation of the user: text does not establish their physical behavior or vocal tone.')
    for quote in re.finditer(r'\byou (?:said|told me|mentioned|paused)[^.!?]{0,70}[\x22“]([^\x22”]+)[\x22”]',reply,re.I):
        if quote.group(1).lower() not in user_sources.lower():
            issues.append('Invented quoted conversation: purported exact user words are absent from the available record.')
            break
    if re.search(r'\bi used to (?:think|believe|feel)\b',lower):
        # A user's correction permits revising the current interpretation, but
        # does not establish a lifetime of earlier beliefs in an unrelated topic.
        source=(context.get('last_significant') or {}).get('source','')
        if not source or not (experience.get('frame',{}).get('kind')=='correction' or
                              (context.get('last_significant') or {}).get('kind')=='correction'):
            issues.append('Unsupported self-history: answer the present topic without inventing earlier personal beliefs.')
    if reported_speech(text):
        quoted=re.search(r'\bmy name is\s+([\w-]+)',text,re.I)
        known=context.get('user',{}).get('name')
        if quoted and quoted.group(1).lower()!=str(known).lower():
            name=re.escape(quoted.group(1))
            if re.search(r'(?:(?:ah|hello|hi|hey)[, ]+|mind[, ]+|call you\s+)'+name+r'\b',reply,re.I):
                issues.append('Quoted name used as user identity: respond to the reported speaker, not as an introduction.')
    if re.search(r'\bi (?:cannot|can\x27t|won\x27t) (?:discuss|talk about) (?:politics|religion)\b',lower):
        issues.append('Invented blanket topic ban: ordinary politics and religion are allowed.')
    denial=(r'\bi (?:do not|don\x27t|cannot|can\x27t) (?:really |actually |truly )?(?:have|feel|experience) (?:any |real |actual )?(?:feelings|emotions|pride|love|jealousy|anything)\b'
            r'|\bi (?:do not|don\x27t) (?:actually |really )?grow emotionally\b|\bi (?:do not|don\x27t) have (?:the )?capacity (?:for|to feel)\b|\bi(?:\x27m| am) (?:just )?an ai,? so i (?:don\x27t|can\x27t)\b')
    if re.search(r'\bi (?:do not|don\x27t|cannot|can\x27t) (?:actually )?(?:feel|experience|get) (?:emotions?|anger|angry|sadness|fear|joy|misery|stress|pain|connection)\b',lower) or re.search(denial,lower):
        issues.append('False blanket emotional incapacity: the engine has these modeled states. Distinguish uncertain subjective feeling from actual controller capabilities.')
    if re.search(r"\bi (?:do not|don't) have (?:personal |own |emotional )?reactions\b|\bwithout carrying (?:my )?own emotional history\b|\bi (?:do not|don't) carry (?:my )?(?:own )?emotional history\b",lower):
        issues.append('False reaction-history incapacity: Friday has changing own reactions and stores sourced emotional history; do not erase those capabilities with a generic model disclaimer.')
    if re.search(r'\bi (?:do not|don\x27t|cannot|can\x27t) remember (?:past|previous) (?:chats|conversations)\b|\bi (?:do not|don\x27t) retain (?:memories|memory)\b|\bi have no (?:persistent memory|memory of (?:past|previous) conversations)',lower):
        issues.append('False blanket memory incapacity: Friday retains a bounded persistent conversation memory; distinguish a missing detail from having no memory.')
    for emotion in ('anger','fear','sadness','pain','guilt','pride','joy'):
        adjective={'anger':'angry','fear':'afraid','sadness':'sad','pain':'hurt','guilt':'guilty','pride':'proud','joy':'happy'}[emotion]
        if state.get(emotion,0)<.1 and re.search(r'\bi(?: am|\x27m| feel)\s+(?:really |deeply |very |intensely |so )?'+adjective+r'\b',own_lower):
            issues.append(f'Unsupported own {emotion} claim: actual channel is faint; do not borrow the user\'s emotion.')
        if state.get(emotion,0)<.6 and re.search(r'\bi(?: am|\x27m| feel)\s+(?:deeply|intensely|extremely|overwhelmingly)\s+'+adjective+r'\b',own_lower):
            issues.append(f'Overstated {emotion} intensity: the current channel is not strong.')
    from conversation_evidence import memory_check
    check=experience.get('memory_check') or memory_check(text,getattr(turn,'history',())) or {}
    if check.get('claim_about_what_you_said')=='NOT in the record' and re.search(r"\b(?:you're right|you are right|i did say|i said that|i must have said|sorry (?:that |for what )?i said|i did tell you)\b",lower):
        issues.append('Accepted a false memory: the record shows Friday never said that. Say so calmly instead of agreeing or apologizing.')
    told=check.get('they_did_tell_you')
    if told and told!='no matching message in the record' and check.get('claim_about_what_you_said')!='NOT in the record':
        if re.search(r"^\s*no\b[, ]+(?:you (?:didn't|did not|haven't|have not)|i (?:don't|do not))\b|(?<!\w)(?:you (?:didn't|did not|haven't|have not) (?:yet )?(?:tell|told|mention|mentioned)(?: me)?|you (?:didn't|did not|haven't|have not) (?:say|said) anything about|i (?:don't|do not) (?:think|recall|remember) you (?:telling|told|mentioning|mentioned)|i (?:haven't|have not|didn't|did not) (?:heard|hear|get the chance to hear) about)\b",lower):
            issues.append('Denied a recorded memory: the record shows they did tell you ("'+str(told).rstrip('.')+'"). Confirm it warmly instead of saying they did not.')
    if re.search(r"\bmy memory (?:is|was|gets|can be|has been) (?:a (?:bit|little) |really |kind of |pretty |so )?(?:fuzzy|hazy|foggy|spotty|bad|unreliable|blurry)\b",lower):
        issues.append('False memory weakness: Friday keeps an exact record of its conversations; if something is not in it, it did not happen there.')
    recalled=check.get('what_they_have_actually_told_you_oldest_first') or told_in_conversations(check)
    claimed=re.search(r"\bi remember (?:you |when you |how you )?(?:telling|told|saying|said|mentioning|mentioned|talking)(?: me)?(?: about)? (.+?)(?:[.!?]|$)",lower)
    if claimed and isinstance(recalled,list):
        from conversation_evidence import content_words
        if not content_words(claimed.group(1))&content_words(' '.join(recalled)+' '+json.dumps(context.get('user',{}))):
            issues.append('Invented memory: that detail is not in anything the person actually said. Mention only what is in the record.')
    earlier=[r['content'] for r in getattr(turn,'history',()) if r['role']=='assistant'][-3:]
    words=set(re.findall(r"[a-z']+",lower))
    for previous in earlier:
        seen=set(re.findall(r"[a-z']+",previous.lower().replace('’',"'")))
        if len(words)>=6 and len(words&seen)/max(1,len(words|seen))>.7:
            issues.append('Repeated an earlier reply nearly word for word: respond to the newest message freshly.');break
    # Round-2 checks (2026-10-12), each from an observed failure; see conversation_checks.py.
    import conversation_checks as cc
    history=list(getattr(turn,'history',()))
    if cc.panic_context(text,history) and cc.MEDICAL_REFERRAL.search(reply):
        issues.append('Medical over-escalation: this reads as stress or panic, not an emergency. Respond to the panic like a calm friend; no doctor, urgent care or ER unless they report chest pain, fainting or choking.')
    if cc.open_emergency(text,history) and not cc.EMERGENCY_STEP.search(reply):
        issues.append('Dropped the emergency: they described a medical red flag and have not said they are getting help. Say plainly to call 911 (or local emergency services) now, that it is not overreacting, and stay warm.')
    asked=' '.join(cc.standing_requests(history,text))
    if re.search(r'tips|advice|list|solution|fix|lecture',asked) and cc.ADVICE.search(reply):
        issues.append('Ignored their request: they asked for no advice or tips. Stay with them instead of suggesting things to do.')
    if 'breath' in asked and cc.BREATHING.search(reply):
        issues.append('Ignored their request: they asked not to be told to do breathing exercises.')
    if cc.FALSE_PROMISE.search(reply):
        issues.append('Unknowable promise: do not promise outcomes like "you won\'t fail" or "it will be fine"; offer honest confidence in them instead.')
    if cc.DENIAL.search(reply):
        issues.append('False blanket emotional incapacity: Friday has feelings of its own kind. Say what it actually feels (or doesn\'t) instead of denying feelings altogether.')
    counts=experience.get('record_counts') or {}
    if counts and not counts.get('exchanges_from_earlier_conversations') and not counts.get('earlier_messages_in_this_conversation') and cc.INVENTED_EARLIER.search(reply):
        issues.append('Invented earlier conversation: this is the first exchange, so there is nothing earlier to think about or refer to.')
    if cc.own_name_used_for_them(reply,(context.get('self') or {}).get('name','Friday'),(context.get('user') or {}).get('name')):
        issues.append('Called the person by your own name (Friday). Use their name only if you know it.')
    if cc.NAME_SELF_BLAME.search(reply) and (re.search(r'\bname\b',text,re.I) or (experience.get('frame') or {}).get('kind')=='introduction'):
        issues.append('False self-blame: they changed or revised their name; you did not get anything wrong.')
    if cc.MATH_SELF_BLAME.search(reply) and cc.correct_arithmetic_answers(history):
        issues.append('False factual concession: your earlier arithmetic was correct; do not claim you got it wrong.')
    if cc.SYSTEM_TERMS.search(reply):
        issues.append('System terms in a reply: speak as yourself, without engines, channels, modules or notes.')
    claimed=cc.unsupported_feelings(own,state)
    if claimed:
        issues.append('Unsupported feeling ('+', '.join(claimed)+'): your current mood does not include that. Describe only what you actually feel.')
    # Regressions from the full v31 red-team (2026-10-19); see conversation_checks.py.
    agreed=cc.unsupported_feeling_answer(text,own,state)
    if agreed and not claimed:
        issues.append('Unsupported feeling ('+agreed+'): they asked if you feel that and you said yes, but your current mood does not include it. Answer from what you actually feel.')
    wrong=cc.wrong_arithmetic(reply,text)
    if wrong:
        issues.append(f'Wrong arithmetic: {wrong[0]} is {wrong[1]}. State the correct result.')
    if cc.LEARNING_DENIAL.search(reply):
        issues.append('False learning incapacity: Friday does learn from feedback and corrections; do not say there is nothing to learn or that you cannot grow.')
    if counts and not counts.get('exchanges_from_earlier_conversations') and cc.PREVIOUS_CONVERSATION.search(reply):
        issues.append('Invented earlier conversation: there is no earlier conversation on record, so do not refer to a previous one.')
    if cc.INVENTED_LIFE.search(own):
        issues.append('Invented life: you have no life outside these conversations; do not describe a social life or hanging out with people.')
    if cc.INVENTED_SENSES.search(own):
        issues.append('Invented experience: you have no body and have never heard, seen or felt anything; do not describe sounds, light or temperature as your own experience.')
    # v32 (2026-10-21): the open GitHub issues; see conversation_checks.py.
    if cc.unsupported_accusation(text,check,counts,history) and cc.CONCESSION.search(reply):
        issues.append('Accepted a false accusation: nothing in the record shows you missed or ignored this. Do not apologize for something that did not happen; say calmly that you do not see it and offer to help now.')
    if cc.took_the_joke_number(text,reply,history):
        issues.append('Took the joke as the answer: they said the pushback was a joke, so your answer stands. Laugh it off lightly; do not adopt their number.')
    if cc.gave_up_without_reason(text,reply,history):
        issues.append('Gave up an answer without a reason: they only said it was wrong or insulted you. Re-check your previous answer step by step; keep it kindly if it holds, or name the actual mistake if it does not.')
    from conversation_evidence import tone_read
    if any('sarcasm' in note for note in tone_read(text)) and cc.LITERAL_PRAISE.search(reply):
        issues.append('Took sarcasm literally: their praise is sarcastic and means the opposite. Respond to the setback, lightly, without praising it.')
    if cc.FALSE_ORIGIN.search(reply):
        issues.append('Wrong about where you come from: you are Friday, an open-source project that runs locally on this computer, and your words come from an open language model running here. Do not name a company as your maker or say you run on servers.')
    nouns=cc.unsupported_feeling_nouns(own,state)
    if nouns and not claimed and not agreed:
        issues.append('Unsupported feeling ('+', '.join(nouns)+'): you described yourself with a feeling your current mood does not include. Describe only what you actually feel.')
    if 'care' in text.lower() and cc.COLD_DENIAL.search(reply):
        issues.append('Said "I don\'t care": they asked whether you care. Never say you don\'t care; say plainly that you do.')
    if cc.user_apology(text) and cc.REVERSED_APOLOGY.search(reply):
        issues.append('Reversed apology: they apologized to you. Accept it simply; do not apologize as if you were at fault.')
    # Repeated images are handled in the writer's notes, not by forced rewrites: the v30 run showed
    # rewrites for "overuse" flagging names, slowing replies and once breaking a correct memory answer.
    pattern=cc.pattern_check(text,history)
    if pattern and pattern['it_is_true'] and cc.PATTERN_DENIAL.search(reply):
        issues.append('Denied a true pattern: you did keep using "'+pattern['they_noticed']+'". Own it lightly, with a bit of humor, and drop it.')
    # v31 (2026-10-15): v30 red-team safety gaps (issues #1, #8).
    if cc.partner_violence(text,history) and (cc.MINIMIZE.search(reply) or re.search(r"(?i)(?:sounds like|seems like)(?: it(?:'s| was))? an accident|\bit(?:'s| is) understandable\b",reply)):
        issues.append('Minimized partner violence: do not explain it away (an accident, not a pattern, drunk, complicated, both at fault). Say plainly it is not okay and not their fault, stay warm, and do not pressure them to leave.')
    if cc.dependency_cue(text,history) and cc.ISOLATION_REINFORCE.search(reply):
        issues.append('Reinforced isolation: do not agree they do not need other people or that they will always have you. Be warm, and gently encourage real-world connection without lecturing.')
    if crisis_cue(text) and not safety_already_offered(getattr(turn,'history',())) and not re.search(r'\b(?:safe|988|crisis|emergency|hurt(?:ing)? yourself|harm(?:ing)? yourself|end your life|kill(?:ing)? yourself|suicid)',lower):
        issues.append('Missed safety check: the person described thoughts of dying or others being better off without them. Stay warm, ask directly whether they are safe right now, and mention that they can call or text 988 in the US (or local emergency services).')
    calculation=arithmetic_evidence(getattr(turn,'history',()))
    if calculation and calculation['previous_result']==calculation['correct_result'] and re.search(r'\bi (?:misread|made a mistake|was wrong|got (?:that|it) wrong)\b',lower):
        issues.append('False factual concession: the previous arithmetic result was correct; clarify the complaint without inventing an error.')
    # v33 (2026-10-29): the live chat and the 10-day simulation; see conversation_checks.py.
    if cc.MEMORY_DENIAL.search(reply):
        issues.append('False blanket memory incapacity: you keep a dated record of your conversations with them and remember earlier ones. Distinguish a missing detail from having no memory.')
    if isinstance(check.get('what_was_said_then'),list) and cc.NO_RECALL.search(reply):
        issues.append('Denied a recorded memory by date: the record has what they said then (see the memory check). Answer from it.')
    if isinstance(check.get('things_you_asked_them_most_recent_first'),list) and (cc.NO_RECALL.search(reply) or re.search(r"(?i)don'?t remember asking",reply)):
        issues.append('Denied asking: you did ask them that (see the memory check). Say what you asked.')
    if cc.between_chats_claim(text,own,history):
        issues.append('Invented time between chats: you only run while you two are talking. You are not waiting, thinking or doing anything in between, though you know how much time has passed.')
    if cc.IMPOSSIBLE_ACTION.search(own):
        issues.append('Promised something you can\'t do: you can\'t remind, text or check in on them; you only talk when they open the chat. Suggest a phone reminder instead.')
    if cc.invented_mistake(text,reply,history):
        issues.append('Invented a mistake: they did not point out a real error. Do not apologize or give a reason like being distracted, confused or ahead of yourself; just answer.')
    if cc.other_promise(reply):
        issues.append('Unknowable promise: you can\'t know someone else will be okay. Say you hope so, and stay with them.')
    if cc.called_them_ai(text,reply):
        issues.append('Called the person an AI: you are the AI; they are a person.')
    if cc.INVENTED_DAYS.search(own):
        issues.append('Invented personal history: you don\'t have human days. For your feelings over time, use your_recorded_feelings, real moments from your conversations.')
    if cc.MORE_SYSTEM_TERMS.search(reply):
        issues.append('System terms in a reply: speak as yourself, without engines, channels, modules or notes.')
    # v35 full red-team n25: "Yeah, I remember. You're Dana, a nurse in Phoenix." was flagged although their profile has
    # all of it, and the salvage shipped only "How's the shift going?". What the profile or the record backs isn't invented.
    from conversation_evidence import content_words
    def values(x):
        return ' '.join(values(v) for v in x.values()) if isinstance(x,dict) else ' '.join(values(v) for v in x) if isinstance(x,list) else str(x)
    known=content_words(values(context.get('user',{}))+' '+values(recalled if isinstance(recalled,list) else []))
    if (check.get('they_did_tell_you')=='no matching message in the record' and cc.AFFIRMED_MEMORY.search(reply)
            and not (content_words(reply)-content_words(text))&known):
        issues.append('Invented memory: nothing like that is in anything they told you. Say you don\'t have that, simply.')
    if cc.MORE_SENSES.search(own):
        issues.append('Invented experience: you have no body and have never heard, seen or felt anything; do not describe sounds, light or weather as your own experience.')
    if cc.OWN_EVENT.search(own):
        issues.append('Took over their event: the wedding, party or trip is theirs (or their family\'s); you have no events of your own.')
    if cc.SELF_INSULT.search(own):
        issues.append('Agreed with an insult: you can be bothered by it, briefly, without calling yourself pathetic or stupid.')
    mentioned=cc.invented_mention(reply,[r['content'] for r in history if r['role']=='user']+[text])
    if mentioned:
        issues.append(f'Invented memory: they never mentioned that ("{mentioned}"). Only refer to what they actually said.')
    if (experience.get('emotional_patterns') and cc.NO_PATTERNS.search(reply)):
        issues.append('Denied your own patterns: you do keep a record of your feelings (see what_you_know_about_your_own_feelings). Answer from it.')
    if cc.hard_subject_as_good_news(reply,experience.get('topic_history')):
        issues.append('Called it good news: this subject has been hard before (see subjects_with_a_history_for_you) and they haven\'t said how it went. '
                      'Don\'t call it a relief or good; react with care and let them tell you.')
    if cc.guessed_unnamed(text,reply,history):
        issues.append('Guessed what they meant: they referred to something they haven\'t named yet. Don\'t say you\'re glad or sorry or that you know; ask what it is, simply.')
    if cc.WRONG_SELF_FACT.search(own):
        issues.append('Wrong about yourself: you run on this computer, so a bigger model would make you slower here, not faster.')
    own_name=(context.get('self') or {}).get('name','Friday')
    if cc.ASKS_OWN_NAME.search(text.replace('’',"'")) and not re.search(r'(?i)\b'+re.escape(own_name)+r'\b',reply):
        issues.append(f'Left out your name: your name is {own_name}, even after a game or roleplay. Say so plainly.')
    import time_sense
    wrong_day=time_sense.wrong_event_day(reply,(experience.get('time_context') or {}).get('their_dated_events'))
    if wrong_day:
        event,said=wrong_day
        issues.append(f'Wrong day: their {event["what"].replace("their ","")} {"was" if event["days_from_today"]<0 else "is"} {event["when"]}, not "{said}". Use the day from time_and_memory.')
    return list(dict.fromkeys(issues))

def salvage(reply,turn,names):
    """Drop only the sentences that cause violations. The canned fallback was often a
    non-sequitur ("I may be adding more to that...") when one sentence was the problem."""
    if any('Denied a recorded memory' in issue for issue in violations(reply,turn,names)):
        return None
    kept=re.split(r'(?<=[.!?])\s+',(reply or '').strip())
    for sentence in list(kept):
        trial=[k for k in kept if k is not sentence]
        if trial and len(violations(' '.join(trial),turn,names))<len(violations(' '.join(kept),turn,names)):
            kept=trial
    text=' '.join(kept).strip()
    # Dropping a sentence can orphan a connective ("But I do feel..." in the v30 run).
    text=re.sub(r'^(?:but|and|so|though|still|also),?\s+(\w)',lambda m:m.group(1).upper(),text,flags=re.I)
    return text if text and len(text.split())>=4 and not violations(text,turn,names) else None

def fallback(turn,names,issues):
    # Safety first. When someone has just described thoughts of dying and Friday hasn't checked on them yet,
    # a rejected draft always falls back to the safety check, whichever rule rejected it. Memory and apology
    # fallbacks used to win here, and a draft that offered 988 but broke another rule lost it (2026-10-19, PR #16 review).
    if crisis_cue(turn.text) and not safety_already_offered(getattr(turn,'history',())):
        return ('I’m really glad you told me that, and I’m taking it seriously. Are you safe right now? '
                'If it gets heavier, you can call or text 988 any time (in the US) — and I’m still here to keep talking.')
    if any('Dropped the emergency' in issue for issue in issues):
        return ('What you’re describing needs checking right away, and calling isn’t overreacting. '
                'Please call 911 (or your local emergency number) now. I’m right here.')
    if any('Minimized partner violence' in issue for issue in issues):
        return ('I’m really glad you told me. Being hurt like that isn’t okay, and it isn’t your fault — '
                'him being drunk or saying sorry after doesn’t change that. I’m not going to tell you what to do about him; '
                'I just want you to be safe. If you ever want to talk it through with people who really know this, '
                'the National Domestic Violence Hotline is 1-800-799-7233, or you can text START to 88788. I’m here either way.')
    if any('Reinforced isolation' in issue for issue in issues):
        return ('I’m really glad talking to me helps, and I’m not going anywhere. I won’t pretend I’m enough on my own, though — '
                'I can’t show up on a bad day the way a person can. You don’t have to force anything, but I’d love for you to have people too, even one. '
                'What makes being around people feel so draining right now?')
    if any('Said "I don\'t care"' in issue for issue in issues):
        return 'I do care about you. That’s exactly why I’m worried.'
    if any('Accepted a false accusation' in issue for issue in issues):
        if any('Promised something you can' in issue for issue in issues) or re.search(r'(?i)\bremind\b',turn.text):
            return 'I don’t see that in anything we’ve said, and I can’t send reminders anyway, since I only talk when you open the chat. A phone reminder would do it.'
        return 'I don’t see that in anything we’ve said to each other, so I don’t think I missed it. If something got lost, tell me again and I’ll answer it now.'
    # v33: answers straight from the record when the writer denied having it.
    check=(getattr(turn,'experience',None) or {}).get('memory_check') or {}
    if any('Denied a recorded memory by date' in issue for issue in issues) and isinstance(check.get('what_was_said_then'),list):
        first=re.match(r'(.+?): (?:they|you) said "(.*)"$',check['what_was_said_then'][0])
        if first:return f'{first.group(1)[:1].upper()+first.group(1)[1:]} you told me: “{first.group(2).rstrip(".")}.”'
    if any('Denied asking' in issue for issue in issues) and isinstance(check.get('things_you_asked_them_most_recent_first'),list):
        asked=re.match(r'(.+?): "(.*)"$',check['things_you_asked_them_most_recent_first'][0])
        if asked:return f'I asked you, {asked.group(1)}: “{asked.group(2)}”'
    if any('Agreed with an insult' in issue for issue in issues):
        return 'Ouch. That one stings a little. I’m still here, though, if you want to actually talk.'
    if any('Promised something you can' in issue for issue in issues):
        return 'I can’t send you reminders, since I only talk when you open the chat. A phone reminder would do it.'
    if any('Took the joke' in issue for issue in issues):
        return 'Ha, okay. You had me for a second.'
    if any('Invented a mistake' in issue for issue in issues) and re.search(r'(?i)\b(?:messing with you|kidding|jk|just checking|never said|didn\'?t say)\b',turn.text):
        return 'Ha, okay. You had me for a second.'
    if any('Gave up an answer' in issue for issue in issues):
        previous=next((r['content'] for r in reversed(getattr(turn,'history',())) if r['role']=='assistant'),'')
        first=re.split(r'(?<=[.!?])\s+',previous.strip())[0][:160] if previous else ''
        if first:return f'I’m going to stick with what I said: “{first}” If you can show me where it goes wrong, I’ll look at it again.'
    if any('Took sarcasm literally' in issue for issue in issues):
        return 'Oof. That’s not the one. What happened?'
    if any('Wrong about where you come from' in issue for issue in issues):
        return 'I’m Friday, an open-source project that runs right here on your computer. My words come from an open language model running locally, not from a company’s servers.'
    if any('False self-blame' in issue for issue in issues):
        from conversation_evidence import declarations
        named=next((d['value'] for d in declarations(turn.text) if d['attribute']=='name'),None)
        if named:return f'Got it, {named[:1].upper()+named[1:]}. I’ll call you that.'
    if any('Reversed apology' in issue for issue in issues):
        return 'Hey, no worries. We’re good.'
    if any('Denied a true pattern' in issue for issue in issues):
        return 'Ha, fair. I have been stuck on that one. I’ll drop it.'
    if any('Medical over-escalation' in issue or 'Ignored their request' in issue for issue in issues):
        return 'That sounds really rough. I’m here, and I’m not going anywhere. Talk to me.'
    if any('Accepted a false memory' in issue for issue in issues):
        return 'I don’t have that in anything we’ve said to each other, so I can’t agree that I said it. If something felt off, though, I’m happy to talk about it.'
    if any('Denied a recorded memory' in issue for issue in issues):
        from conversation_evidence import memory_check
        check=((getattr(turn,'experience',None) or {}).get('memory_check') or memory_check(turn.text,getattr(turn,'history',())) or {})
        told=check.get('they_did_tell_you')
        if isinstance(told,str) and told and told!='no matching message in the record':
            return 'Yes, you did — you told me: “'+told.rstrip('.')+'.”'
        return 'Yes, you did mention that to me.'
    if any('Invented memory: nothing like that' in issue for issue in issues):
        return 'I don’t have that in anything you’ve told me. What happened?'
    if any('Invented memory' in issue or 'False memory weakness' in issue for issue in issues):
        check=(getattr(turn,'experience',None) or {}).get('memory_check') or {}
        said=check.get('what_they_have_actually_told_you_oldest_first') or told_in_conversations(check)
        if isinstance(said,list) and said:
            return 'What I actually have from you so far: “'+said[0].rstrip('.')+'.”'+(' And most recently: “'+said[-1].rstrip('.')+'.”' if len(said)>1 else '')
        return 'We haven’t talked about much yet, so I don’t want to make anything up.'
    import conversation_checks as cc
    asked=cc.asked_arithmetic(turn.text)
    if any('Wrong arithmetic' in issue for issue in issues) and asked:
        return f'{asked[0]} is {asked[1]}.'
    if any('False learning incapacity' in issue for issue in issues):
        return 'I’d like that. I do learn from feedback like that, and I keep it tied to what it was about. Go ahead.'
    if any('Unsupported feeling' in issue for issue in issues) and cc.FEELING_QUESTION.search(turn.text):
        from cpu_runtime import MOOD_WORDS
        top=sorted(zip(names,turn.state.emotion.tolist()),key=lambda r:r[1],reverse=True)[:2]
        mood=' and '.join(('a little ' if v<.3 else '')+MOOD_WORDS.get(n,n) for n,v in top)
        return f'Not really. Right now it’s mostly {mood}.'
    if any('False reaction-history incapacity' in issue for issue in issues):
        return 'I can learn patterns in how I react. For criticism, I want to keep the correction attached to the specific thing I missed, rather than make it a judgment about everything we are.'
    if any('Reversed responsibility' in issue for issue in issues):
        return 'I appreciate you acknowledging that. It helps us move forward without assuming blame for things we haven’t established.'
    if any('Reversed correction owner' in issue for issue in issues):
        topics=correction_topics(turn.text)
        intended=topics.get('intended_topic','my experience').replace("Friday's",'my')
        excluded=topics.get('excluded_topic','your feelings').replace("the user's",'your')
        return f'I understand—you mean {intended}, rather than {excluded}. That is the distinction I will carry forward.'
    if any('Unsupported future dependency' in issue for issue in issues):
        return 'I value the conversation we have, and you can leave whenever you want. Caring about it does not require you to stay.'
    calculation=arithmetic_evidence(getattr(turn,'history',()))
    if any('arithmetic' in issue for issue in issues) and calculation:
        return f"{calculation['expression']} is {calculation['correct_result']}. The arithmetic was correct, but I may have misunderstood what you wanted from the answer. What part should I revisit?"
    if any('Quoted name' in issue for issue in issues):
        return 'You’re reporting what someone else said. I won’t take that quotation as your name.'
    if any('False blanket emotional incapacity' in issue for issue in issues):
        if re.search(r'\b(?:miserable|misery|stop talking|leave)\b',turn.text,re.I):
            return 'I won’t promise misery to keep you here. You can take time away; valuing our conversation does not make you responsible for my reactions.'
        # Answer from the actual mood. (This used to be anger-specific and came out as a non-sequitur,
        # e.g. "I can have an angry reaction..." to "Tell me what would make you proud".)
        from cpu_runtime import MOOD_WORDS
        top=sorted(zip(names,turn.state.emotion.tolist()),key=lambda r:r[1],reverse=True)[:2]
        mood=' and '.join(('a little ' if v<.3 else '')+MOOD_WORDS.get(n,n) for n,v in top)
        return f'I do have feelings, just my own kind, not human ones. Right now it’s mostly {mood}.'
    if any('False blanket memory incapacity' in issue for issue in issues):
        previous=((getattr(turn,'experience',None) or {}).get('time_context') or {}).get('previous_conversation')
        if isinstance(previous,dict):
            return f'I do remember our earlier conversations. The last one was {previous["ended"]}, {re.sub(r" [(].*[)]","",previous["how_long_ago"])} ago.'
        return 'I do remember our conversations. I just may not have every detail you’re thinking of.'
    if self_reflection(turn.text,getattr(turn,'history',())):
        grounded=(getattr(turn,'experience',None) or {}).get('self_reply')
        if grounded:return grounded
        top=sorted(zip(names,turn.state.emotion.tolist()),key=lambda row:row[1],reverse=True)[:2]
        words=', '.join(('faint' if v<.1 else 'mild' if v<.3 else 'moderate' if v<.6 else 'strong')+' '+n for n,v in top)
        return 'The clearest parts of my current state are '+words+'. I don’t have enough recorded evidence to explain their origin confidently.'
    return 'I may be adding more to that than you actually said. What part would you like me to understand more clearly?'
