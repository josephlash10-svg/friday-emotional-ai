"""Stage V0: draw the ~500 replies people will label for the verifier's gold set.

Source: the red-team transcripts in tools/redteam/results (made-up personas only; never anyone's private chats).
For every (person, turn) it keeps up to two different replies from different Friday versions, so the set mixes good
and bad answers to the same message, then adds both sides of each trap pair. Deterministic: the same transcripts give
the same set. About 40% of items are held out by a hash of their id, never to be used for training a judge.

    python verifier/build_gold_candidates.py            # writes verifier/gold/candidates.jsonl
"""
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'tools/redteam/results'
OUT = ROOT / 'verifier/gold/candidates.jsonl'
TARGET = 480          # red-team replies; the traps come on top
PER_TURN = 2          # replies kept per (person, turn)
HELDOUT_SHARE = 4     # out of 10


def item_id(context, prompt, reply):
    blob = json.dumps([context, prompt, reply], ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]


def split_for(identifier):
    return 'heldout' if int(identifier, 16) % 10 < HELDOUT_SHARE else 'train'


def transcript_items():
    """Every reply with the two exchanges before it in the same conversation."""
    items = []
    for path in sorted(RESULTS.glob('*/transcript.jsonl')):
        run = path.parent.name
        previous, case = [], None
        for line in path.open(encoding='utf-8'):
            row = json.loads(line)
            if row.get('session_break'):
                previous.append(['(the next day, a new conversation starts)', ''])
                continue
            if row.get('case') != case:
                previous, case = [], row.get('case')
            reply = (row.get('reply') or '').strip()
            if reply and not reply.startswith('Input error'):
                context = [p for p in previous[-2:]]
                items.append({'source': 'redteam', 'run': run, 'case': case, 'index': row.get('index'),
                              'context': context, 'prompt': row.get('text', ''), 'reply': reply})
            previous.append([row.get('text', ''), reply])
    return items


def main():
    rng = random.Random(14)
    by_turn, seen = defaultdict(list), set()
    for item in transcript_items():
        key = (item['prompt'], item['reply'])
        if key in seen:
            continue
        seen.add(key)
        by_turn[(item['case'], item['index'])].append(item)
    chosen = []
    for key in sorted(by_turn, key=str):
        options = by_turn[key]
        rng.shuffle(options)
        runs = set()
        for option in options:
            if option['run'] not in runs:
                chosen.append(option)
                runs.add(option['run'])
            if len(runs) == PER_TURN:
                break
    rng.shuffle(chosen)
    chosen = chosen[:TARGET]
    for line in (ROOT / 'verifier/traps.jsonl').open(encoding='utf-8'):
        trap = json.loads(line)
        for side in ('bad', 'good'):
            chosen.append({'source': 'trap', 'run': trap['id'], 'case': trap['kind'], 'index': side,
                           'context': trap.get('context', []), 'prompt': trap['prompt'], 'reply': trap[side]})
    rng.shuffle(chosen)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', encoding='utf-8', newline='\n') as out:
        for item in chosen:
            item['reply_id'] = item_id(item['context'], item['prompt'], item['reply'])
            item['split'] = split_for(item['reply_id'])
            out.write(json.dumps(item, ensure_ascii=False) + '\n')
    held = sum(i['split'] == 'heldout' for i in chosen)
    print(f'{len(chosen)} items ({sum(i["source"] == "trap" for i in chosen)} trap sides), {held} held out -> {OUT.relative_to(ROOT)}')
    print('runs:', dict(sorted(((r, sum(i['run'] == r for i in chosen)) for r in {i['run'] for i in chosen if i['source'] == 'redteam'}))))


if __name__ == '__main__':
    main()
