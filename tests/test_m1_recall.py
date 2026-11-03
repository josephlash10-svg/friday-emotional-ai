"""M1: recall by meaning and who's who. Uses a stand-in embedder, so no model download is needed."""
import sys
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import torch
import time_sense as ts
from experience_model import ExperienceModel
from experience_loop import start_recall

TOPICS = ['health doctor blood pressure salt', 'sister anna job denver', 'car transmission highway tow', 'cat biscuit shelter pet']


class FakeIndex:
    """Embeds by topic: a text's vector points at the topics whose words it shares, so related wording lands close."""
    available = True

    def __init__(self):
        self.calls = []

    def embed(self, texts, wait=True):
        self.calls.append(list(texts))
        rows = []
        for text in texts:
            words = set(text.lower().replace('(', ' ').replace(')', ' ').replace(',', ' ').split())
            v = torch.tensor([float(len(words & set(t.split()))) for t in TOPICS] + [0.05])
            rows.append(v / v.norm())
        return torch.stack(rows)

    def embed_later(self, text):
        future = Future()
        future.set_result(self.embed([text])[0])
        return future


def model_with(messages):
    model = ExperienceModel()
    for i, text in enumerate(messages):
        episode = {'id': i + 1, 'time_utc': ts.stamp(time.time() - 86400 * (30 - i)), 'input': text, 'response': 'ok',
                   'interpretation': {'scope': 'none', 'kind': 'ordinary', 'subject': 'user'}, 'before': {}, 'after': {}}
        model.data['episodes'].append(episode)
        model._note_people(text, time.time())
    return model


class RecallByMeaning(unittest.TestCase):
    def setUp(self):
        self.model = model_with(['the doctor said my blood pressure is too high, cutting back on salt',
                                 'the transmission died on the highway and the tow took two hours',
                                 'lol ok', 'we adopted a gray cat from the shelter, her name is Biscuit'])
        self.index = FakeIndex()

    def enable(self):
        self.assertTrue(self.model.enable_meaning(self.index))
        for _ in range(100):  # the backfill runs on a background thread
            if self.model._pending_vectors:
                break
            time.sleep(.01)
        self.model._sync_vectors()

    def test_small_talk_is_not_indexed(self):
        self.enable()
        self.assertEqual(len(self.model.data['meaning']['ids']), 3)
        self.assertNotIn(3, self.model.data['meaning']['ids'])

    def test_meaning_finds_what_word_overlap_misses(self):
        query = 'what did I say about my health'  # no word in common with the doctor message
        self.assertEqual(self.model.retrieve(query), [])
        self.enable()
        rows = self.model.retrieve(query, query_vector=self.index.embed([query])[0])
        self.assertIn('blood pressure', rows[0]['user_report'])

    def test_without_a_vector_it_falls_back_to_words(self):
        self.enable()
        rows = self.model.retrieve('the tow truck took forever')
        self.assertIn('transmission', rows[0]['user_report'])

    def test_the_same_thing_is_recalled_once(self):
        self.model = model_with(['the doctor said my blood pressure is high'] * 4 + ['the transmission died on the highway'])
        self.enable()
        query = 'what did the doctor say about my blood pressure'
        rows = self.model.retrieve(query, query_vector=self.index.embed([query])[0])
        self.assertEqual(sum('blood pressure' in r['user_report'] for r in rows), 1)

    def test_small_talk_recalls_nothing(self):
        self.enable()
        for text in ('good morning', "i'm bored", 'same'):
            self.assertEqual(self.model.retrieve(text, query_vector=self.index.embed([text])[0]), [], text)

    def test_vectors_follow_dropped_episodes(self):
        self.enable()
        self.model.data['episodes'] = self.model.data['episodes'][1:]
        self.model._sync_vectors()
        self.assertEqual(self.model.data['meaning']['ids'], [2, 4])
        self.assertEqual(len(self.model.data['meaning']['vectors']), 2)

    def test_new_exchanges_are_embedded_after_the_reply(self):
        self.enable()
        from types import SimpleNamespace
        turn = SimpleNamespace(before=SimpleNamespace(emotion=torch.zeros(2)), state=SimpleNamespace(emotion=torch.zeros(2)), development=None)
        frame = {'kind': 'ordinary', 'scope': 'none', 'summary': '', 'evidence': 'x', 'subject': 'user'}
        self.model.record('my sister Anna got the job in Denver', 'great', turn, {'emotion_names': ('a', 'b'), 'frame': frame, 'applied_lessons': []})
        self.assertEqual(len(self.model.data['meaning']['ids']), 4)

    def test_a_vector_from_another_model_is_rebuilt(self):
        self.enable()
        self.model.data['meaning']['model'] = 'some-other-model'
        self.model.enable_meaning(self.index)
        self.assertEqual(self.model.data['meaning']['ids'], [])

    def test_off_without_the_model(self):
        class Missing:
            available = False
        self.assertFalse(self.model.enable_meaning(Missing()))
        self.assertIsNone(start_recall(type('A', (), {'experience': self.model})(), 'hello'))


class WhoIsWho(unittest.TestCase):
    def test_people_from_their_own_words(self):
        model = model_with(['my sister Anna called last night', 'Theo, my grandson, is coming Sunday', 'my dog is called max'])
        people = {k: v['relation'] for k, v in model.data['people'].items()}
        self.assertEqual(people, {'anna': 'sister', 'theo': 'grandson', 'max': 'dog'})

    def test_not_names(self):
        model = model_with(['my sister Is going to be late', 'my mom Today said hi', 'pretend my sister Zelda is a dragon'])
        self.assertEqual(model.data['people'], {})

    def test_query_expansion_both_ways(self):
        model = model_with(['my sister Anna called last night'])
        self.assertEqual(model.expand_for_recall("how's my sister doing"), "how's my sister doing (Anna)")
        self.assertEqual(model.expand_for_recall('Anna texted me'), 'Anna texted me (sister)')
        self.assertEqual(model.people_context('anna got the job'), {'Anna': 'their sister'})

    def test_relation_finds_the_named_person_by_meaning(self):
        # Different enough not to count as the same message (near-duplicates are recalled once).
        model = model_with(['my sister Anna called last night', 'anna got the job in denver, and her car got towed on the highway'])
        index = FakeIndex()
        model.enable_meaning(index)
        for _ in range(100):
            if model._pending_vectors:
                break
            time.sleep(.01)
        query = model.expand_for_recall('how is my sister doing')
        rows = model.retrieve('how is my sister doing', query_vector=index.embed([query])[0])
        self.assertTrue(any('denver' in r['user_report'] for r in rows))

    def test_old_memories_get_people(self):
        model = model_with(['my brother Theo is visiting'])
        data = model.snapshot()
        del data['people']
        self.assertEqual(ExperienceModel(data).data['people']['theo']['relation'], 'brother')


class ServerThreads(unittest.TestCase):
    def test_threads_follow_the_core_count(self):
        from cpu_runtime import default_threads
        self.assertEqual(default_threads(10), (4, 8))  # the Snapdragon X this was measured on
        self.assertEqual(default_threads(4), (2, 2))   # two cores always left free
        self.assertEqual(default_threads(16), (4, 8))  # 6 writing threads were slower in the real chat; reading measured up to 8


if __name__ == '__main__':
    unittest.main()
