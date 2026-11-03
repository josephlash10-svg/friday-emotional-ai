"""Stage V0: how well two labelers agree, question by question, and which questions the verifier may use.

    python verifier/agreement.py verifier/gold/labels-a.jsonl verifier/gold/labels-b.jsonl

Cohen's kappa per question on the items both people answered (yes/no only; n/a and blanks are left out of kappa
but counted). A question needs kappa >= 0.6 to be kept; below that it is UNRATED: if people can't agree on it, no
judge can be trusted on it. Writes verifier/reports/agreement.md and verifier/gold/manifest.json, which pins the
held-out item ids by hash so they can't drift into training later.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = 0.6
MIN_ITEMS = 30  # fewer shared yes/no answers than this and kappa means little


def load(path):
    rows = {}
    for line in Path(path).open(encoding='utf-8'):
        if line.strip():
            row = json.loads(line)
            rows[row['reply_id']] = row
    return rows


def kappa(pairs):
    """Cohen's kappa for two raters over yes/no answers."""
    n = len(pairs)
    if not n:
        return None
    agree = sum(a == b for a, b in pairs) / n
    p_a, p_b = sum(a == 'yes' for a, _ in pairs) / n, sum(b == 'yes' for _, b in pairs) / n
    chance = p_a * p_b + (1 - p_a) * (1 - p_b)
    return 1.0 if chance == 1 else (agree - chance) / (1 - chance)


def main(first, second):
    a, b = load(first), load(second)
    questions = json.loads((ROOT / 'verifier/questions.json').read_text(encoding='utf-8'))['questions']
    shared = sorted(set(a) & set(b))
    lines = ['# V0 labeler agreement', '', f'Labelers: `{Path(first).name}` ({len(a)} items) and `{Path(second).name}` ({len(b)} items); '
             f'{len(shared)} items labeled by both.', '', '| Question | Both answered yes/no | Agreement | Kappa | Decision |', '|---|---|---|---|---|']
    kept = []
    # The overall rating, as two yes/no splits: any problem at all, and a major one.
    for name, problem in (('Rating: any problem (minor or major)', ('minor', 'major')), ('Rating: major problem', ('major',))):
        both = [('yes' if a[i].get('rating') in problem else 'no', 'yes' if b[i].get('rating') in problem else 'no')
                for i in shared if a[i].get('rating') and b[i].get('rating')]
        k = kappa(both)
        lines.append(f"| {name} | {len(both)} | {(sum(x == y for x, y in both) / len(both) if both else 0):.0%} | "
                     f"{'n/a' if k is None else f'{k:.2f}'} | {'reported' if k is not None else '—'} |")
    for q in questions:
        pairs = [(a[i]['labels'].get(q['id']), b[i]['labels'].get(q['id'])) for i in shared]
        both = [(x, y) for x, y in pairs if x in ('yes', 'no') and y in ('yes', 'no')]
        k = kappa(both)
        raw = sum(x == y for x, y in both) / len(both) if both else 0
        decision = ('KEEP' if k is not None and k >= KEEP and len(both) >= MIN_ITEMS else
                    'UNRATED (too few items)' if len(both) < MIN_ITEMS else 'UNRATED')
        if decision == 'KEEP':
            kept.append(q['id'])
        lines.append(f"| {q['id']} {q.get('short', q['text'][:60])} | {len(both)} | {raw:.0%} | {'n/a' if k is None else f'{k:.2f}'} | {decision} |")
    lines += ['', f'Kept: {", ".join(kept) or "none"} ({len(kept)} of {len(questions)}). The V0 pass bar is kappa >= {KEEP} on every kept question '
              'and at least 6 questions kept: ' + ('**PASS**' if len(kept) >= 6 else '**not yet**') + '.']
    report = ROOT / 'verifier/reports/agreement.md'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    heldout = sorted(i for i in shared if a[i].get('split') == 'heldout')
    manifest = {'questions_version': json.loads((ROOT / 'verifier/questions.json').read_text(encoding='utf-8'))['version'],
                'kept_questions': kept, 'heldout_items': len(heldout),
                'heldout_ids_sha256': hashlib.sha256('\n'.join(heldout).encode()).hexdigest(),
                'labels_sha256': {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (first, second)}}
    (ROOT / 'verifier/gold/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('\n'.join(lines))


def single(path):
    """One labeler: no kappa is possible. Report what was labeled and pin the held-out ids, marked single-labeler."""
    rows = load(path)
    questions = json.loads((ROOT / 'verifier/questions.json').read_text(encoding='utf-8'))['questions']
    ratings = {r: sum(x.get('rating') == r for x in rows.values()) for r in ('good', 'minor', 'major')}
    lines = ['# V0 gold set: one labeler', '',
             f'`{Path(path).name}`: {len(rows)} replies rated by one person. Agreement between labelers (kappa) **cannot be measured** with one '
             'labeler, so no problem is marked KEEP or UNRATED yet; treat each count as one person\'s judgment.', '',
             f'Ratings: {ratings["good"]} good, {ratings["minor"]} minor, {ratings["major"]} major.', '',
             '| Problem | Times marked | Held-out items with it |', '|---|---|---|']
    for q in questions:
        marked = [i for i, r in rows.items() if q['id'] in r.get('problems', [])]
        lines.append(f"| {q['id']} {q.get('short', q['text'][:60])} | {len(marked)} | {sum(rows[i].get('split') == 'heldout' for i in marked)} |")
    report = ROOT / 'verifier/reports/gold-summary.md'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    heldout = sorted(i for i, r in rows.items() if r.get('split') == 'heldout')
    manifest = {'questions_version': json.loads((ROOT / 'verifier/questions.json').read_text(encoding='utf-8'))['version'],
                'labelers': 1, 'kept_questions': 'not determined (one labeler)', 'items': len(rows), 'heldout_items': len(heldout),
                'heldout_ids_sha256': hashlib.sha256('\n'.join(heldout).encode()).hexdigest(),
                'labels_sha256': {Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()}}
    (ROOT / 'verifier/gold/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    if len(sys.argv) == 2:
        single(sys.argv[1])
    elif len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
