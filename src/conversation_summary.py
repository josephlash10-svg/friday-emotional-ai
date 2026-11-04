"""What Friday keeps in view when a long conversation no longer fits the context window (v35.1 live chat).

The writer sees a fixed number of tokens. In the live chat with Moss (an AI that runs an orchard's frost fans and hives)
Friday's notes grew until only 2-4 of about 40 messages were left in view: it said it had been "processing data on the
hives" (Moss's job) and contradicted itself within minutes. Two small, fixed-size facts now go with every reply, built from
what was actually said, with no extra language-model call:

  who_is_who                      what they said about themselves (name, what they are, what they can and can't do), and
                                  that their job, body and tools are theirs, not Friday's
  earlier_in_this_conversation    the few earlier exchanges that matter most once they are out of view: things said to
                                  Friday, advice and plans Friday gave, decisions they made, numbers, at most six
Everything else said earlier stays in the record, where recall by meaning finds it when it comes up.
"""
import re

# What they are and what they can or can't do; feelings ("i'm tired", "i'm nervous") are not who someone is.
SELF_DESCRIPTION = re.compile(r"(?i)(?:^|(?<=[.!?,;])\s*|\bbut\s+|\band\s+)((?:i'?m|i am|i run|i have|i don'?t have|i do not have|i can'?t|i cannot|"
                              r"i work|i live|my name is|my job is|my jobs are|i manage|i control|i'm not|i am not)\b[^.!?;]{3,110})")
FEELING_AFTER_IM = re.compile(r"(?i)^(?:i'?m|i am)\s+(?:so |really |just |kind of |kinda |a (?:little|bit) |pretty |very |not |still )*"
                              r"(?:tired|nervous|fine|okay|ok|good|sorry|glad|happy|sad|scared|worried|excited|angry|mad|upset|confused|"
                              r"testing|kidding|joking|serious|going|gonna|thinking|guessing|asking|telling|trying|not switching|done|back|here|wiped)\b")
WHO_LIMIT, WHO_CHARS = 6, 110
EARLIER_LIMIT, EARLIER_CHARS = 6, 120

ADVICE = re.compile(r"(?i)\b(?:you should|you could|try|keep|turn (?:off|on)|run|cut|tell them|don'?t tell|maybe|i'?d|the plan|step)\b")
DECISION = re.compile(r"(?i)\b(?:i'?m going to|i'?ll|i will|i decided|i'm not going to|the plan is|i'?m telling)\b")


def who_is_who(user_texts, name=None):
    """{'them': [...], 'you': '...'} from what they said about themselves, the most recent distinct statements in order."""
    found = []
    for text in user_texts:
        for match in SELF_DESCRIPTION.finditer((text or '').replace('’', "'")):
            said = match.group(1).strip(' ,')
            if FEELING_AFTER_IM.search(said):
                continue
            key = said.lower()[:50]
            found = [f for f in found if f.lower()[:50] != key] + [said[:WHO_CHARS]]
    if not found:
        return None
    return {'them': f'{name or "they"} said about themselves: ' + ' | '.join(found[-WHO_LIMIT:]),
            'you': ('you are Friday, running on this computer: no body or hands, and no jobs or tools beyond this conversation. '
                    'What they described above is theirs, not yours')}


def earlier_in_this_conversation(trimmed, at_friday=None):
    """The few earlier exchanges that matter most once they are out of view, oldest first. trimmed: history rows
    ({'role', 'content'}) no longer shown. Fixed size, so it never grows with the conversation."""
    scored = []
    for i, row in enumerate(trimmed):
        text = (row.get('content') or '').strip()
        if not text:
            continue
        if row['role'] == 'user':
            score = 2 * bool(at_friday and at_friday.search(text)) + bool(DECISION.search(text)) + bool(re.search(r'\d', text))
            who = 'they'
        else:
            score = 2 * bool(ADVICE.search(text))
            who = 'you'
        if score:
            scored.append((score, i, f'{who}: {text[:EARLIER_CHARS]}'))
    kept = sorted(sorted(scored, key=lambda r: (-r[0], -r[1]))[:EARLIER_LIMIT], key=lambda r: r[1])
    return [line for _, _, line in kept] or None
