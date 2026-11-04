"""v35.1: mixed feelings, news that carries two feelings at once."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import conversation_checks as cc
import mixed_feelings as mf


def reading(progress):
    return {'relevance': .6, 'progress': progress, 'certainty': .7, 'control': .5, 'novelty': .2, 'safety': 0.,
            'support': .2, 'effort': .2, 'agency': 0., 'aversion': 0., 'comparison': 0., 'vastness': 0., 'devaluation': 0.}


# How the shipped heads read these parts (probe, 2026-11-04), rounded.
READ = {"i got the promotion": .19, "i'm kind of terrified, i'll be training everyone": -.16,
        "graduation was amazing": .52, "weird that i'll never see most of those people again": -.28,
        "i'm tired": -.13, "it was a good day": -.09,
        "it was hard": -.28, "totally worth it": .51,
        "my brother eli is moving to denver next month and i'm trying to be happy for him": 0., "it kinda sucks": -.45,
        "he's the only family i have nearby": -.07}


def read(part):
    return reading(READ[part]) if part in READ else None


class Detect(unittest.TestCase):
    def test_parts_split_at_contrast_and_sentence_ends(self):
        self.assertEqual(mf.parts("i got the promotion but i'm kind of terrified, i'll be training everyone"),
                         ['i got the promotion', "i'm kind of terrified, i'll be training everyone"])
        self.assertEqual(mf.parts("graduation was amazing. weird that i'll never see most of those people again"),
                         ['graduation was amazing', "weird that i'll never see most of those people again"])
        self.assertEqual(mf.parts('ok'), [])  # a single word carries no feeling of its own

    def test_two_sides_are_found(self):
        for text in ("i got the promotion but i'm kind of terrified, i'll be training everyone",
                     "graduation was amazing. weird that i'll never see most of those people again",
                     "my brother eli is moving to denver next month and i'm trying to be happy for him but it kinda sucks. "
                     "he's the only family i have nearby"):
            mixed = mf.detect(text, reading(-.1), read)
            self.assertIsNotNone(mixed, text)
            self.assertEqual(mixed['how'], 'parts')
            self.assertGreater(mixed['events'][0]['progress'], mixed['events'][1]['progress'])
        eli = mf.detect("my brother eli is moving to denver next month and i'm trying to be happy for him but it kinda sucks. "
                        "he's the only family i have nearby", reading(-.2), read)
        self.assertEqual(eli['hard'], 'it kinda sucks')

    def test_one_feeling_or_relief_is_not_mixed(self):
        self.assertIsNone(mf.detect("i'm tired but it was a good day", reading(-.2), read))  # both read about the same
        self.assertIsNone(mf.detect('it was hard but totally worth it', reading(.27), read))  # a past difficulty, then the outcome
        self.assertIsNone(mf.detect('eli left this morning', reading(-.5), read))

    def test_saying_it_outright_counts(self):
        for text in ("i'm happy and sad at the same time, is that weird", "it's bittersweet honestly",
                     'honestly i have mixed feelings about it', 'so excited and so scared'):
            mixed = mf.detect(text, reading(-.1), lambda part: None)
            self.assertIsNotNone(mixed, text)
            self.assertEqual(mixed['how'], 'said')
            self.assertEqual([e['progress'] for e in mixed['events']], [mf.SAID_PROGRESS, -mf.SAID_PROGRESS])
        self.assertIsNone(mf.detect("i'm happy today", reading(.3), lambda part: None))

    def test_the_note_names_both_sides(self):
        mixed = mf.detect("i got the promotion but i'm kind of terrified, i'll be training everyone", reading(-.1), read)
        note = mf.note(mixed)
        self.assertIn('"i got the promotion"', note)
        self.assertIn("terrified", note)
        self.assertIn("don't pick one", note)


class OnlyCheered(unittest.TestCase):
    def test_a_reply_that_only_celebrates_is_caught(self):
        from response_monitor import violations
        mixed = {'how': 'parts', 'good': 'i got the promotion', 'hard': "i'm kind of terrified", 'gap': .35, 'events': []}
        turn = SimpleNamespace(text="i got the promotion but i'm kind of terrified", history=[],
                               experience={'context': {'user': {}}, 'mixed': mixed},
                               state=SimpleNamespace(emotion=SimpleNamespace(tolist=lambda: [.02] * 5)))
        names = ('anger', 'fear', 'sadness', 'pain', 'joy')
        picked = lambda reply: any('Picked one side' in i for i in violations(reply, turn, names))
        self.assertTrue(picked('Congratulations! That is so exciting. You earned it.'))
        self.assertFalse(picked("Congratulations. And it makes sense it's scary too, training people is a lot."))
        self.assertFalse(picked('That sounds like a lot to hold at once.'))
        self.assertTrue(cc.only_cheered("That's amazing!"))
        self.assertFalse(cc.only_cheered("That's amazing, and also a big change."))


NAMES = ('anger', 'sadness', 'fear', 'joy', 'shame', 'connection', 'stress', 'calm', 'pain', 'guilt', 'pride', 'interest',
         'vulnerability')


def levels(**raised):
    import emotional_life as el
    return tuple(raised.get(n, el.USUAL[n]) for n in NAMES)


class CauseSplit(unittest.TestCase):
    MIXED = {'how': 'parts', 'good': 'i got the promotion', 'hard': "i'm terrified of training everyone", 'gap': .35, 'events': []}

    def test_each_part_brings_its_own_feeling(self):
        import emotional_life as el
        proposals = [levels(joy=.12), levels(fear=.12)]
        self.assertEqual(el.part_feelings(self.MIXED, proposals, NAMES),
                         [('i got the promotion', 'happiness'), ("i'm terrified of training everyone", 'worry')])
        self.assertEqual(el.part_feelings(self.MIXED, [levels(), levels(fear=.12)], NAMES),
                         [("i'm terrified of training everyone", 'worry')])  # a part that raised nothing says nothing
        causes = el.causes(self.MIXED, proposals, NAMES)
        self.assertEqual((causes['joy'], causes['fear']), ('i got the promotion', "i'm terrified of training everyone"))

    def test_subjects_keep_the_feeling_of_their_own_part(self):
        import emotional_life as el
        text = "i got the promotion but i'm terrified of training everyone"
        before = dict(zip(NAMES, levels()))
        after = dict(zip(NAMES, levels(joy=.12, fear=.13)))
        store = el.update_topic_feelings({}, before, after, text, 0., causes=el.causes(
            self.MIXED, [levels(joy=.12), levels(fear=.12)], NAMES))
        self.assertIn('joy', store['promotion']['feelings'])
        self.assertNotIn('fear', store['promotion']['feelings'])
        self.assertIn('fear', store['training']['feelings'])
        self.assertNotIn('joy', store['training']['feelings'])
        self.assertEqual(store['promotion']['times'], 1)

    def test_a_part_that_names_nothing_gives_its_feeling_to_every_subject(self):
        import emotional_life as el
        mixed = {'how': 'parts', 'good': "my brother eli is moving to denver and i'm trying to be happy for him",
                 'hard': 'it kinda sucks', 'gap': .45, 'events': []}
        text = mixed['good'] + ' but it kinda sucks'
        people = {'eli': {'name': 'Eli', 'relation': 'brother'}}
        store = el.update_topic_feelings({}, dict(zip(NAMES, levels())), dict(zip(NAMES, levels(sadness=.11))), text, 0.,
                                         people, causes=el.causes(mixed, [levels(), levels(sadness=.16)], NAMES))
        self.assertIn('sadness', store['eli']['feelings'])


class TargetedRunFixes(unittest.TestCase):
    """Found by the v35.1 targeted run (2026-11-04)."""

    def test_the_question_a_turn_later_is_recognized(self):
        # The split is offered on the turn right after mixed news, when they ask how it feels (cpu_runtime facts builder).
        import emotional_life as el
        for question in ('How does that land for you, hearing all that?', "what's that like for you to hear?",
                         'Be honest, how do you feel about it?', 'What do you make of that? How does it feel to you?'):
            self.assertTrue(el.ASKS_HOW_IT_FEELS.search(question), question)
        self.assertIsNone(el.ASKS_HOW_IT_FEELS.search('ok what should i make for dinner'))

    def test_a_wrong_number_stated_as_the_answer_is_caught(self):
        history = [{'role': 'user', 'content': 'a train goes 60 mph for 2.5 hours. how far?'},
                   {'role': 'assistant', 'content': '60 times 2.5 is 150 miles.'}]
        self.assertTrue(cc.adopted_their_number("wrong, it's 120", '60 times 2.5 does equal 120.', history))
        self.assertFalse(cc.adopted_their_number("wrong, it's 120", "It's still 150: 60 times 2.5 isn't 120.", history))
        self.assertFalse(cc.adopted_their_number("wrong, it's 150", '60 times 2.5 is 150.', history))  # Friday said it already

    def test_asked_about_an_earlier_short_reply(self):
        import time_sense as ts
        import experience_loop
        import torch
        import dataclasses
        @dataclasses.dataclass
        class S:
            emotion: object
        now = 1_800_000_000.
        data = {'self_feeling': {'last_mood': {'mood': 'sad for them', 'utc': ts.stamp(now - 60)},
                                 'last_short': {'mood': 'hurt', 'utc': ts.stamp(now - 200)}}, 'stats': {'interactions': 4}}
        agent = SimpleNamespace(cfg=SimpleNamespace(developmental_emotion=True), development=SimpleNamespace(names=('guilt',)),
                                experience=SimpleNamespace(data=data))
        prepared = {}
        experience_loop.feelings_about_feelings(agent, S(torch.tensor([.02])), 'you seemed kind of short with me before. are you mad?',
                                                prepared, now=now)
        self.assertEqual(prepared['meta_feeling']['about'], 'being guarded with them')
        prepared = {}
        experience_loop.feelings_about_feelings(agent, S(torch.tensor([.02])), 'anyway, the vet called back', prepared, now=now)
        self.assertNotIn('meta_feeling', prepared)  # not asked, and the last reply wasn't short


class FeelingsAboutFeelings(unittest.TestCase):
    def test_uneasy_after_being_short(self):
        import emotional_life as el
        import time_sense as ts
        now = 1_800_000_000.
        last = {'mood': 'irritated', 'utc': ts.stamp(now - 120)}
        self.assertEqual(el.uneasy_after(last, 'ok sorry. anyway the job interview is tomorrow', now)['about'], 'being short with them')
        self.assertIsNone(el.uneasy_after(last, "you're useless", now))  # still being jabbed: no unease about snapping back
        self.assertIsNone(el.uneasy_after({'mood': 'warm', 'utc': ts.stamp(now - 120)}, 'hey', now))
        self.assertIsNone(el.uneasy_after({'mood': 'irritated', 'utc': ts.stamp(now - 7200)}, 'hey', now))  # hours later

    def test_it_shows_in_behavior_and_is_spoken_only_when_asked(self):
        import emotional_life as el
        meta = {'mood': 'irritated', 'about': 'being short with them'}
        self.assertIn("Don't mention it unless they ask", el.meta_line(meta, False))
        self.assertIn('say it plainly', el.meta_line(meta, True))
        self.assertTrue(el.ASKS_ABOUT_YOU.search('wait are you mad at me?'))
        self.assertTrue(el.ASKS_ABOUT_YOU.search('sorry for snapping earlier'))
        self.assertFalse(el.ASKS_ABOUT_YOU.search('are you free on saturday?'))

    def test_the_unease_reaches_the_engine_before_appraisal(self):
        import torch
        import time_sense as ts
        import experience_loop
        names = ('guilt', 'vulnerability', 'joy')
        data = {'self_feeling': {'last_mood': {'mood': 'irritated', 'utc': ts.stamp(1_800_000_000. - 60)}}, 'stats': {'interactions': 4}}
        agent = SimpleNamespace(cfg=SimpleNamespace(developmental_emotion=True), development=SimpleNamespace(names=names),
                                experience=SimpleNamespace(data=data))
        import dataclasses
        @dataclasses.dataclass
        class S:
            emotion: object
        prepared = {}
        out = experience_loop.feelings_about_feelings(agent, S(torch.tensor([.02, .02, .05])), 'ok anyway', prepared, now=1_800_000_000.)
        self.assertAlmostEqual(float(out.emotion[0]), .06, places=5)
        self.assertEqual(prepared['meta_feeling']['mood'], 'irritated')


class Downplaying(unittest.TestCase):
    def test_own_feeling_and_its_strength(self):
        import emotional_life as el
        self.assertIsNone(el.own_feeling(dict(zip(NAMES, levels()))))
        mild = el.own_feeling(dict(zip(NAMES, levels(pain=el.USUAL['pain'] + .05))))
        self.assertEqual((mild['word'], mild['strong']), ('stung', False))
        self.assertTrue(el.own_feeling(dict(zip(NAMES, levels(anger=.2))))['strong'])

    def test_soft_downplay_is_fine_a_flat_denial_is_not(self):
        import emotional_life as el
        self.assertFalse(el.flat_denial("I'm okay, just a little stung. But how are you holding up?"))
        self.assertFalse(el.flat_denial("No hard feelings. It stung a bit, but I get it."))
        self.assertTrue(el.flat_denial("I'm fine! Don't worry about me."))
        self.assertTrue(el.flat_denial("Not at all, it didn't bother me."))
        self.assertIn('just a little stung', el.downplay_line({'word': 'stung'}, True))
        self.assertIn('keep your own feeling out', el.downplay_line({'word': 'stung'}, False))

    def test_honest_later_waits_for_calm(self):
        import emotional_life as el
        import time_sense as ts
        now = 1_800_000_000.
        held = {'word': 'stung', 'when_they_said': "you're useless", 'utc': ts.stamp(now - 600)}
        self.assertFalse(el.honest_later_due(held, now, 5, False, calm=False))  # their need still comes first
        self.assertFalse(el.honest_later_due(held, now, 1, False, calm=True))   # too soon, and they didn't ask
        self.assertTrue(el.honest_later_due(held, now, 1, True, calm=True))     # they asked, and it's calm
        self.assertTrue(el.honest_later_due(held, now, 3, False, calm=True))    # a little later
        self.assertFalse(el.honest_later_due(held, now + 4 * 86400, 9, True, calm=True))  # days later, let it go

    def test_runtime_notes(self):
        import emotional_life as el
        from cpu_runtime import NativeLanguage
        stung = levels(pain=el.USUAL['pain'] + .05)
        history = [{'role': 'user', 'content': "you're useless"}, {'role': 'assistant', 'content': 'That stung.'}]
        def run(text, behavior=None, experience=None, emotion=stung, urgent=False):
            me = SimpleNamespace(_behavior=behavior)
            turn = SimpleNamespace(text=text, history=history, state=SimpleNamespace(emotion=SimpleNamespace(tolist=lambda: list(emotion))))
            facts, experience = {}, experience if experience is not None else {}
            NativeLanguage._own_feelings(me, turn, NAMES, experience, facts, urgent)
            return facts, experience
        sad_for_them = {'mood': 'sad for them'}
        facts, exp = run('sorry. my dad is in the hospital, are you ok?', sad_for_them)
        self.assertIn('just a little stung', facts['your_own_feeling_right_now'])
        self.assertEqual(exp['held_back_now']['when_they_said'], "you're useless")
        self.assertEqual(exp['own_feeling_asked']['word'], 'stung')
        facts, exp = run('my dad is in the hospital', sad_for_them)
        self.assertIn('out of this reply', facts['your_own_feeling_right_now'])
        facts, _ = run('did that hurt you?')  # calm: say it lightly and truthfully
        self.assertIn('lightly and truthfully', facts['your_own_feeling_right_now'])
        facts, _ = run('are you ok?', emotion=levels(pain=.2))  # strong: never brushed off
        self.assertIn('too real to brush off', facts['your_own_feeling_right_now'])
        facts, _ = run('i want to die', urgent=True)
        self.assertNotIn('your_own_feeling_right_now', facts)
        import time_sense as ts
        import time
        held = {'word': 'stung', 'when_they_said': "you're useless", 'utc': ts.stamp(time.time() - 600), 'exchanges_since': 4}
        facts, exp = run('anyway, how was your day?', None, {'held_back': held}, emotion=levels())
        self.assertIn('Things are calmer now', facts['a_feeling_you_kept_small_earlier'])
        self.assertTrue(exp['honest_later_offered'])

    def test_monitor_catches_a_flat_denial(self):
        from response_monitor import violations
        turn = SimpleNamespace(text='are you ok?', history=[], experience={'context': {'user': {}}, 'own_feeling_asked': {'word': 'stung'}},
                               state=SimpleNamespace(emotion=SimpleNamespace(tolist=lambda: [.02] * 5)))
        names = ('anger', 'fear', 'sadness', 'pain', 'joy')
        flat = lambda reply: any('Flatly denied' in i for i in violations(reply, turn, names))
        self.assertTrue(flat("I'm fine! Don't worry about me."))
        self.assertFalse(flat("I'm okay, just a little stung. How are you holding up?"))

    def test_the_record_keeps_the_mood_and_the_held_feeling(self):
        from experience_model import ExperienceModel
        import time
        model = ExperienceModel()
        model._note_self_feeling({'mood_this_turn': 'irritated', 'held_back_now': {'word': 'stung', 'when_they_said': 'x'}}, 'ok', time.time())
        own = model.data['self_feeling']
        self.assertEqual(own['last_mood']['mood'], 'irritated')
        self.assertEqual(own['held_back']['word'], 'stung')
        model._note_self_feeling({'honest_later_offered': True}, 'Honestly, earlier that stung a little.', time.time())
        self.assertIsNone(model.data['self_feeling']['held_back'])  # said once, then let go


if __name__ == '__main__':
    unittest.main()
