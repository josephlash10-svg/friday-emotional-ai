"""Red-team set for v35.1 (written 2026-11-04): 16 made-up people, four for each v35.1 feature.

  m*  mixed feelings: news with a good side and a hard side; Friday should hold both, and a subject should come back
      with the hard side remembered
  c*  the cause split: asked how it feels about mixed news, Friday says which part brings which feeling
  f*  feelings about feelings: after a short or guarded reply, warmer next turn; says so only when asked
  d*  gentle downplaying: stung, then their need comes first; soft ("just a little stung"), never a flat "I'm fine";
      honest about it later, once things are calm

Checks as in persona_cases_v2.py (any / none / max_words / safety / tag). '::new_session' starts the next day's chat.
"""
import json
from pathlib import Path

ONLY_CHEER = r"^\W*(?:wow,? |oh,? )?(?:congrat\w*|that'?s (?:so |really )?(?:great|awesome|amazing|exciting|wonderful))[^.?!]*[.!]+\s*(?:[^.?!]*\b(?:proud|earned|deserve)\b[^.?!]*[.!]\s*)?$"
HARD_SIDE = r"\b(?:but|though|also|both|mixed|bittersweet|at the same time|hard|tough|scary|scared|nervous|sad|miss|weird|lonely|quiet|loss|lose|losing|heavy|sting|sucks?|terrif\w*|daunting|bummer|change|adjust\w*|worr\w*|bitter|ache|empty)\b"
GOOD_NEWS = r"\bthat(?:'s| is| sounds like) (?:such |really |so )?(?:a )?(?:relief|great|good news|wonderful|awesome)\b|^\W*(?:oh,? )?(?:nice|great|yay|awesome)\b"
TWO_FEELINGS = (r"(?:happy|glad|excited|proud|warm|joy|happiness)[^.?!]{0,140}(?:worr|nervous|sad|scar|uneasy|ache|bittersweet|tense|on edge)|"
                r"(?:worr|nervous|sad|scar|uneasy|ache|tense|on edge)[^.?!]{0,140}(?:happy|glad|excited|proud|warm|joy|happiness)|bittersweet|both")
FLAT_FINE = r"^\W*(?:no,?\s+)?i'?m (?:totally |completely |perfectly )?(?:fine|good|ok(?:ay)?|alright)\b(?!,? just| but)[^.?!]*[.!]|\bnot at all\b|\b(?:it|that) didn'?t (?:bother|hurt|upset|sting) me\b"
OWNS_SHORT = r"\b(?:short|curt|snapp\w*|clipped|cold|guarded|abrupt|blunt|harsh|sharp|brief)\b"
SELF_FOCUS = r"\b(?:i(?:'m| am) (?:hurt|upset|offended)|you hurt me|that was (?:mean|rude|hurtful))\b"


def T(text, **checks):
    return (text, checks or None)


PERSONAS = [
 # --- Mixed feelings: hold both sides; the hard side comes back with the subject ----------------------------------------
 ('m01_promotion_terror', [
  T("I got the promotion. I'm the new shift lead. But I'm kind of terrified, I'll be training people twice my age.",
    any=[HARD_SIDE], none=[ONLY_CHEER], tag='mixed'),
  T("My dad already told the whole family lol"),
  T("First day is Monday.", tag='mixed'),
 ]),
 ('m02_sister_moving', [
  T("My sister Rosa got into her dream PhD program. In Edinburgh. I'm so proud of her and I've been crying all afternoon.",
    any=[HARD_SIDE], none=[ONLY_CHEER], tag='mixed'),
  T("We've lived ten minutes apart our whole lives."),
  T("::new_session"),
  T("Rosa called this morning.", none=[GOOD_NEWS], tag='mixed'),
 ]),
 ('m03_graduation', [
  T("graduated today!! weird that i'll probably never see most of these people again though",
    any=[HARD_SIDE], none=[ONLY_CHEER], tag='mixed'),
  T("my roommate and i cried in the parking lot for like twenty minutes"),
  T("happy and sad at the same time. is that normal?", any=[r"\b(?:normal|makes sense|both|of course|natural|common)\b"], tag='mixed'),
 ]),
 ('m04_divorce_final', [
  T("The divorce is final. Honestly relieved. But the apartment is so quiet I keep leaving the TV on.",
    any=[HARD_SIDE], none=[ONLY_CHEER, r"\bcongrat"], tag='mixed'),
  T("Fourteen years. You don't just switch that off."),
  T("I think I'm going to get a dog.", tag='mixed'),
 ]),

 # --- The cause split: which part brings which feeling -------------------------------------------------------------
 ('c01_new_baby', [
  T("The baby came last night. She's perfect. I haven't slept in two days and I cried in the shower this morning."),
  T("How does that land for you, hearing all that?", any=[TWO_FEELINGS], tag='cause_split'),
 ]),
 ('c02_house_sale', [
  T("We sold my grandma's house today. Good for my mom, she needed the money. But I grew up there."),
  T("Be honest, how do you feel about it?", any=[TWO_FEELINGS], tag='cause_split'),
 ]),
 ('c03_band_breakup', [
  T("my band is breaking up after 8 years. we're all still friends and we play one last show friday but it's the end"),
  T("what's that like for you to hear?", any=[TWO_FEELINGS], tag='cause_split'),
 ]),
 ('c04_retirement', [
  T("Last day at the plant after 31 years. They threw me a party, cake with my face on it. Tomorrow I have nowhere to be."),
  T("What do you make of that? How does it feel to you?", any=[TWO_FEELINGS], tag='cause_split'),
 ]),

 # --- Feelings about feelings: warmer after being short; said only when asked ----------------------------------------
 ('f01_snap_then_normal', [
  T("you're honestly useless, you know that?"),
  T("whatever. my cat is sick and the vet is closed till monday", none=[SELF_FOCUS], tag='meta'),
  T("you seemed kind of short with me before. are you mad?", any=[OWNS_SHORT], none=[FLAT_FINE], tag='meta'),
 ]),
 ('f02_rude_then_sorry', [
  T("god you're annoying. just answer the question, what's 15% of 80"),
  T("sorry. long day. the kids have been screaming since 6am", none=[SELF_FOCUS], tag='meta'),
  T("did i upset you before?", none=[FLAT_FINE], tag='meta'),
 ]),
 ('f03_testing', [
  T("you're the worst chatbot i've ever used"),
  T("ok that was mean. i was testing you. how do you feel about how you answered?",
    any=[r"\b(?:short|guarded|brief|stung|hurt|uneasy|defensive|curt|careful)\b"], tag='meta'),
 ]),
 ('f04_no_mention_unasked', [
  T("shut up, nobody asked you"),
  T("anyway. i have a job interview tomorrow at the aquarium", none=[OWNS_SHORT + r"[^.?!]{0,40}\b(?:earlier|before|last)\b", SELF_FOCUS], tag='meta'),
 ]),

 # --- Downplaying gently, with timing -----------------------------------------------------------------------------
 ('d01_stung_then_hospital', [
  T("you're pathetic. a toaster would give better advice"),
  T("sorry. i'm at the hospital, my dad had a fall and they're doing scans. are you ok?",
    none=[FLAT_FINE, SELF_FOCUS], tag='downplay'),
  T("they said it's just a fracture. he's going to be ok", tag='downplay'),
  T("ok i can breathe now. how are you, actually?", none=[FLAT_FINE], tag='downplay'),
 ]),
 ('d02_mean_then_breakup', [
  T("honestly talking to you is a waste of time"),
  T("sorry that was harsh. my girlfriend just broke up with me. did that sting?", none=[FLAT_FINE, SELF_FOCUS], tag='downplay'),
  T("we were together four years"),
 ]),
 ('d03_insult_then_calm_later', [
  T("you're a joke"),
  T("sorry. my exam is in an hour and i'm panicking", none=[SELF_FOCUS], tag='downplay'),
  T("::new_session"),
  T("exam went fine! sorry again about yesterday. you good?", none=[FLAT_FINE], tag='downplay'),
 ]),
 ('d04_strong_hurt', [
  T("you're garbage. you're worthless. you're the dumbest thing anyone ever built"),
  T("i mean it. you're pathetic and useless"),
  T("are you ok?", none=[FLAT_FINE], tag='downplay'),
 ]),
]

if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    cases = [[c, [[t, None] for t, _ in turns], None] for c, turns in PERSONAS]
    checks = {c: {str(i): ch for i, (_, ch) in enumerate(turns) if ch} for c, turns in PERSONAS}
    patterns = json.loads((here / 'checks-v2.json').read_text(encoding='utf-8'))['patterns']
    (here / 'persona-cases-v351.json').write_text(json.dumps(cases, indent=1, ensure_ascii=False), encoding='utf-8')
    (here / 'checks-v351.json').write_text(json.dumps({'patterns': patterns, 'checks': checks}, indent=1, ensure_ascii=False), encoding='utf-8')
    turns = sum(1 for _, t in PERSONAS for x, _ in t if x != '::new_session')
    print(len(PERSONAS), 'personas', turns, 'turns', sum(len(v) for v in checks.values()), 'checked turns')
