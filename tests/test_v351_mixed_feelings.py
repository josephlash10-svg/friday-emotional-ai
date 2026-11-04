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


if __name__ == '__main__':
    unittest.main()
