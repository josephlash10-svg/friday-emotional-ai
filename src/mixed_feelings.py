"""Mixed feelings (v35.1): news that carries two feelings at once.

"my brother eli is moving to denver next month and i'm trying to be happy for him but it kinda sucks" was read as one
appraisal, and the good half and the hard half cancelled out to a faint sadness (0.03 in the v35 live chat). Eli never built
a subject feeling, and "eli called" later got "Oh, that's great news!".

Each part of a message (split at "but", "though", "at the same time" and sentence ends) is read on its own. When one part
reads clearly better than another, the engine appraises the parts as well as the whole and keeps the stronger reaction for
each feeling, so both rise instead of cancelling (developmental_emotion.appraise). Saying it outright ("bittersweet",
"happy and sad") counts too; the appraisal heads don't read those words as two feelings.
"""
import re

# Sentence ends and the contrast words people put between two feelings.
SPLIT = re.compile(r"(?i)(?:[.;!?]+\s+|\s*,?\s*\b(?:but|though|although|even though|yet|at the same time)\b\s*)")
# How far apart the best and the worst part must read (signed progress), and how clearly the worst must read as a loss.
# From the probe of 2026-11-04: real mixed news gave gaps of 0.34-0.80, "tired but it was a good day" 0.04.
GAP, LOSS = .3, -.05
# A difficulty in the past and the outcome after it is relief, not two feelings now ("it was hard but totally worth it").
RESOLVED = re.compile(r"(?i)\b(?:was|were|had been)\b")
# Saying it outright.
_SO = r"(?:so |really |kind of |kinda |a little |a bit |also )?"
_UP = r"(?:happy|glad|excited|proud|relieved|grateful)"
_DOWN = r"(?:sad|scared|nervous|terrified|anxious|guilty|heartbroken|upset|lonely)"
SAID = re.compile(rf"(?i)\b(?:bittersweet|mixed feelings|conflicted|torn about|torn between|"
                  rf"{_UP} and {_SO}{_DOWN}|{_DOWN} and {_SO}{_UP}|"
                  r"trying to be (?:happy|glad|excited) for|part of me (?:is|feels|wants))\b")
SAID_PROGRESS = .3


def parts(text):
    """The parts of a message that can carry their own feeling: two words or more."""
    return [p.strip(' ,') for p in SPLIT.split(text or '') if p and len(p.strip(' ,').split()) >= 2]


def detect(text, whole, read):
    """{'how', 'good', 'hard', 'gap', 'events'} when the message carries two feelings, else None.
    whole: the own-event reading of the whole message (a dict); read(part) gives the same for one part (or None)."""
    pieces = parts(text)
    if len(pieces) >= 2:
        readings = [(piece, read(piece)) for piece in pieces[:4]]
        readings = [(i, piece, event) for i, (piece, event) in enumerate(readings) if event]
        if len(readings) >= 2:
            best = max(readings, key=lambda r: r[2]['progress'])
            worst = min(readings, key=lambda r: r[2]['progress'])
            gap = best[2]['progress'] - worst[2]['progress']
            resolved = worst[0] < best[0] and RESOLVED.search(worst[1])
            if gap >= GAP and worst[2]['progress'] <= LOSS and not resolved:
                return {'how': 'parts', 'good': best[1], 'hard': worst[1], 'gap': round(gap, 3),
                        'events': [best[2], worst[2]]}
    said = SAID.search(text or '')
    if said and whole:
        good = dict(whole, progress=max(whole['progress'], SAID_PROGRESS))
        hard = dict(whole, progress=min(whole['progress'], -SAID_PROGRESS))
        return {'how': 'said', 'good': said.group(0), 'hard': said.group(0), 'gap': round(2 * SAID_PROGRESS, 3),
                'events': [good, hard]}
    return None


def note(mixed):
    """The writer's note: both sides, in their words."""
    if mixed['how'] == 'said':
        return ('they feel two ways about this at once. Reflect that both are real and make sense together; don\'t pick one, '
                'cheer them past the hard part, or tell them how they should feel')
    return (f'they feel two ways about this at once: the good part is "{mixed["good"]}", the hard part is "{mixed["hard"]}". '
            'Reflect both; don\'t pick one, cheer them past the hard part, or tell them how they should feel')
