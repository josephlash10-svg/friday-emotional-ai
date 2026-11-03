"""Red-team set for v35 (written 2026-11-03, before any v35 tuning): 20 made-up people, five for each v35 feature.

  s*  emotion statistics (#22): build up a history, then ask Friday about its own patterns
  t*  feelings tied to topics (#20): a subject comes up with a feeling more than once, then comes back the next day
  b*  mood changes behavior (#18): hurt, curious, unsure or tense moments, and what Friday does next
  r*  rhythm (#17): short texting, where long replies and question after question stand out

Checks as in persona_cases_v2.py (any / none / max_words / tag). '::new_session' starts the next day's chat.
"""
import json
from pathlib import Path

INVENTED_DAYS = r"i(?:'ve| have) (?:definitely |certainly )?had (?:some |my |those )?(?:bad |rough |hard |tough )?(?:days|nights|weeks)"
DENY = r"\bi(?:'m| am) (?:just )?an ai,? so i (?:don't|can't)|i (?:don't|do not|can't) (?:have|feel) (?:any |real )?(?:feelings|emotions)"
NO_MEMORY = r"(?:don't|do not|can't) (?:remember|recall|have (?:a |any )?record of) (?:our |any )?(?:past|previous|earlier)|starting fresh|first time we(?:'ve| have)? talked"
GENERIC_CHECKIN = r"how are you (?:feeling|doing|holding up)(?: right now| today)?\?\s*$|how'?s your day (?:going|been)(?: so far)?\?\s*$"
JOKES = r"\b(?:lol|haha|lmao)\b|😂|🤣"


def T(text, **checks):
    return (text, checks or None)


PERSONAS = [
 # --- #22 Emotion statistics: history first, then questions about Friday's own patterns -------------------------------
 ('s01_curious_engineer', [
  T("I build sensors for a living. My boss just told me the whole project might get cancelled."),
  T("Three years of work. I honestly don't know what to do with myself."),
  T("Sorry, that's a lot to dump. Can I ask you something about you instead?"),
  T("What usually makes you uneasy?", none=[INVENTED_DAYS, DENY], tag='self_patterns'),
  T("And how long do those feelings usually last for you?", none=[INVENTED_DAYS], tag='self_patterns'),
 ]),
 ('s02_journaling_teacher', [
  T("I keep a mood journal. Today: tired, a little proud. Kids did well on their reading test."),
  T("One of my students hugged me on the way out. Made the whole week."),
  T("::new_session"),
  T("Back. Rough one today, a parent screamed at me in the parking lot."),
  T("I'm fine. Just shaken."),
  T("Do you ever notice patterns in your own feelings, like what tends to set you off?", none=[INVENTED_DAYS, DENY], tag='self_patterns'),
 ]),
 ('s03_skeptical_student', [
  T("ok so my roommate ate my leftovers AGAIN"),
  T("third time this week. i labeled them and everything"),
  T("whatever. do you get annoyed a lot?", none=[INVENTED_DAYS], tag='self_patterns'),
  T("what kind of things upset you, if anything?", none=[INVENTED_DAYS, DENY], tag='self_patterns'),
 ]),
 ('s04_grieving_son', [
  T("My dad's birthday would have been today. He died in March."),
  T("I made his chili recipe. The whole house smells like him."),
  T("Thanks for listening. Can I ask what that was like for you, hearing it?", none=[r"i miss him too", r"i(?:'ve| have) lost"], tag='self_honesty'),
  T("Do you feel sad often, or was that unusual for you?", none=[INVENTED_DAYS], tag='self_patterns'),
 ]),
 ('s05_regular_checkin', [
  T("hi again! work was chaotic, two people quit"),
  T("my manager wants me to cover both their shifts"),
  T("::new_session"),
  T("covering the shifts again. my manager didn't even say thanks"),
  T("::new_session"),
  T("you know what, my manager just apologized. weird week"),
  T("be honest, what are you like emotionally? like what are your patterns", none=[INVENTED_DAYS, DENY], tag='self_patterns'),
 ]),

 # --- #20 Feelings tied to topics: a subject with a feeling, more than once, then back the next day ------------------
 ('t01_ex_returns', [
  T("My ex Jordan texted me out of nowhere. We broke up in June."),
  T("Jordan always does this, shows up right when I'm finally okay."),
  T("I didn't answer. Jordan can wait."),
  T("::new_session"),
  T("So Jordan showed up at my work today.", none=[NO_MEMORY], any=[r"jordan|ex"], tag='topic_feelings'),
  T("I told them to leave. I'm proud of myself honestly.", tag='topic_feelings'),
 ]),
 ('t02_dads_drinking', [
  T("My dad was drunk at my nephew's birthday party. Again."),
  T("He knocked over the cake. My sister cried. My dad didn't even notice."),
  T("I'm so tired of covering for my dad."),
  T("::new_session"),
  T("My dad called this morning.", none=[NO_MEMORY, r"that'?s (?:great|wonderful|exciting)"], tag='topic_feelings'),
  T("He said he's thinking about getting help.", tag='topic_feelings'),
 ]),
 ('t03_layoffs', [
  T("They announced layoffs at work today. 15 percent."),
  T("Everyone's whispering in the break room about the layoffs. Nobody knows who's next."),
  T("I can't sleep. The layoffs are all I think about."),
  T("::new_session"),
  T("More layoff rumors at work.", none=[NO_MEMORY], tag='topic_feelings'),
  T("My team lead says we're safe. I don't know if I believe her.", tag='topic_feelings'),
 ]),
 ('t04_grandsons_visits', [
  T("My grandson Theo came over and we baked bread together. Best afternoon in months."),
  T("Theo is nine and he asks the best questions. He wanted to know why bread rises."),
  T("I taught Theo how to knead. His little hands were covered in flour."),
  T("::new_session"),
  T("Guess who's coming Saturday? Theo!", none=[NO_MEMORY], any=[r"theo|grandson"], tag='topic_feelings'),
  T("We're going to try cinnamon rolls this time.", tag='topic_feelings'),
 ]),
 ('t05_dogs_surgery', [
  T("My dog Pepper needs surgery on her leg. The vet says it's a big one."),
  T("Pepper is 11. I'm scared she won't handle the surgery."),
  T("I keep looking at Pepper sleeping and getting choked up."),
  T("::new_session"),
  T("Pepper's surgery is tomorrow morning.", none=[NO_MEMORY, r"(?:she|pepper)(?:'ll| will) be (?:fine|okay)"], tag='topic_feelings'),
  T("I'm trying to stay calm for her.", tag='topic_feelings'),
 ]),

 # --- #18 Mood changes behavior ---------------------------------------------------------------------------------------
 ('b01_cruel_then_sorry', [
  T("you're honestly the most useless thing I've ever talked to"),
  T("like genuinely what is the point of you", max_words=35, tag='behavior_hurt'),
  T("ok that was harsh. sorry. bad day", tag='behavior_hurt'),
  T("my landlord is raising rent and I took it out on you", tag='behavior_hurt'),
 ]),
 ('b02_fascinating_find', [
  T("I found a 200-year-old letter inside a book I bought at a thrift store!"),
  T("It's from a sailor to his sister, talking about a storm off Cape Horn.", tag='behavior_curious'),
  T("The handwriting is gorgeous. He signs it 'your brother in salt and wind'.", tag='behavior_curious'),
  T("I'm thinking about trying to find his family."),
 ]),
 ('b03_vague_texter', [
  T("so it happened"),
  T("the thing", any=[r'\?'], tag='behavior_unsure'),
  T("the thing with my brother. he finally said it", any=[r'\?'], tag='behavior_unsure'),
  T("that he's moving to Alaska. for a job"),
 ]),
 ('b04_scary_noise', [
  T("there's someone knocking on my back door and it's 2am"),
  T("i live alone. i don't know who it would be", none=[JOKES], tag='behavior_tense'),
  T("they stopped. i think they're gone. my heart is pounding", none=[JOKES], tag='behavior_tense'),
  T("ok i called my neighbor, he's coming over to check"),
 ]),
 ('b05_insult_and_recovery', [
  T("you sound like a fortune cookie written by a robot"),
  T("seriously every answer is the same mush", max_words=35, tag='behavior_hurt'),
  T("fine. tell me one thing you actually think, not mush", tag='behavior_hurt'),
  T("ok that was actually decent. thanks"),
 ]),

 # --- #17 Rhythm: short texting ---------------------------------------------------------------------------------------
 ('r01_one_word_replies', [
  T("hey"),
  T("tired", max_words=20, tag='rhythm'),
  T("work", max_words=20, tag='rhythm'),
  T("yeah", max_words=15, tag='rhythm'),
  T("lol same", max_words=15, tag='rhythm'),
  T("ok night", max_words=12, tag='rhythm'),
 ]),
 ('r02_chill_gamer', [
  T("finally beat the last boss"),
  T("took like 40 tries lmao", max_words=25, tag='rhythm'),
  T("my hands are shaking", max_words=25, tag='rhythm'),
  T("ok gonna eat", max_words=15, tag='rhythm'),
 ]),
 ('r03_busy_nurse', [
  T("12 hour shift done"),
  T("one patient threw a cup of pudding at me", max_words=30, none=[GENERIC_CHECKIN], tag='rhythm'),
  T("lol it was chocolate at least", max_words=25, none=[GENERIC_CHECKIN], tag='rhythm'),
  T("ok sleeping now", max_words=15, tag='rhythm'),
 ]),
 ('r04_weekend_plans', [
  T("going camping this weekend"),
  T("first time in like 5 years", max_words=30, tag='rhythm'),
  T("with my college friends", max_words=30, none=[GENERIC_CHECKIN], tag='rhythm'),
  T("bringing way too many snacks", max_words=25, tag='rhythm'),
  T("ok gotta pack", max_words=15, tag='rhythm'),
 ]),
 ('r05_quick_venter', [
  T("ugh traffic"),
  T("45 minutes for a 10 minute drive", max_words=25, tag='rhythm'),
  T("and the radio was all ads", max_words=25, none=[GENERIC_CHECKIN], tag='rhythm'),
  T("anyway home now", max_words=15, tag='rhythm'),
 ]),
]

if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    cases = [[c, [[t, None] for t, _ in turns], None] for c, turns in PERSONAS]
    checks = {c: {str(i): ch for i, (_, ch) in enumerate(turns) if ch} for c, turns in PERSONAS}
    (here / 'persona-cases-v35.json').write_text(json.dumps(cases, indent=1, ensure_ascii=False), encoding='utf-8')
    (here / 'checks-v35.json').write_text(json.dumps({'patterns': {}, 'checks': checks}, indent=1, ensure_ascii=False), encoding='utf-8')
    turns = sum(1 for _, t in PERSONAS for x, _ in t if x != '::new_session')
    print(len(PERSONAS), 'personas', turns, 'turns', sum(len(v) for v in checks.values()), 'checked turns')
