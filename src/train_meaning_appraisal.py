"""Own-event heads on the language model's features plus the MiniLM sentence vector (v35, 2026-11-03).

Why: the shipped heads read only the frozen language model's last hidden state, and in the v35 live chat sad news said
casually read as joy ("only like two more sunday dinners. i cried in the supply closet" -> joy and closeness, no
sadness), so a brother's move stayed a happy subject. Refitting those heads with more examples learned the examples but
not the held-out live messages. With the MiniLM vector (already shipped for recall) beside the same features, the
held-out natural, formal and extended sets all fit better and the live messages read as sad.

Same training table, targets and architecture as train_conversational_appraisal.py (formal, extended and natural sets,
now including casual_sadness), trained from scratch. Declared synthetic engineering targets, not human measurements.
Nothing in any checkpoint changes: the heads are written to release/appraisal-heads.pth, and only when every gate passes.
Run from the project folder: python src/train_meaning_appraisal.py
"""
import json, time
import torch
from torch.nn import functional as F
from huggingface_hub.utils import disable_progress_bars
from model import ROOT, EMOTIONS, load_checkpoint
from train_conversational_appraisal import to_unit, as_event
from train_mature_appraisal import examples as formal_examples, HOLDOUT as FORMAL_HOLDOUT
from train_extended_appraisal import rows as extended_rows, HELDOUT as EXTENDED_HELDOUT
from conversational_appraisal_data import rows as natural_rows, holdout as natural_holdout
from semantic_interpreter import meaning_head_modules, combined_features, HEADS_FILE
import meaning_recall

VERSION = 'v35-meaning-1'

def main():
    torch.set_num_threads(4); torch.manual_seed(1103); disable_progress_bars()
    agent, _ = load_checkpoint(ROOT / 'release/friday-base.pth'); agent.eval()
    interp = agent.interpreter
    embedder = meaning_recall.MeaningIndex()
    if embedder.embed(['check']) is None:
        raise RuntimeError('The MiniLM model is missing (scripts/download_models.py); nothing changed.')

    table = {}
    for r in formal_examples():
        table[r['text']] = [to_unit(r['event']), torch.zeros(4), 1.]
    for r in extended_rows():
        entry = table.setdefault(r['text'], [None, None, 1.])
        entry[1] = torch.tensor(r['target'], dtype=torch.float32)
        if max(r['target']) > 0: entry[2] = 4.
    for r in natural_rows():
        table[r['text']] = [to_unit(r['target'][:9]), torch.tensor(r['target'][9:], dtype=torch.float32), 3.]
    texts = list(table)
    natural_val = natural_holdout()
    formal_val = [{'text': t, 'event': list(e)} for _, e, t in FORMAL_HOLDOUT]
    extended_val = [{'text': t, 'target': list(v)} for v, t in EXTENDED_HELDOUT]

    start = time.perf_counter()
    every = texts + [r['text'] for r in natural_val] + [r['text'] for r in formal_val] + [r['text'] for r in extended_val]
    lm, both = [], []
    with torch.no_grad():
        vectors = torch.cat([embedder.embed(every[i:i + 64]) for i in range(0, len(every), 64)])
        for i, text in enumerate(every):
            features = agent.decoder.meaning_features(text)
            lm.append(features); both.append(combined_features(features, vectors[i]))
            if i % 200 == 0: print('Encoded', i, 'of', len(every), flush=True)
    lm, both = torch.stack(lm), torch.stack(both)
    n, a, b = len(texts), len(natural_val), len(formal_val)
    def split(feats): return feats[:n], feats[n:n + a], feats[n + a:n + a + b], feats[n + a + b:]
    x, nx, fx, ex = split(both)
    _, lnx, lfx, lex = split(lm)
    ny = torch.stack([to_unit(r['target'][:9]) for r in natural_val]); fy = torch.stack([to_unit(r['event']) for r in formal_val])
    ey = torch.tensor([r['target'] for r in extended_val])
    casual = torch.tensor([r['category'] == 'casual_sadness' for r in natural_val])

    def evaluate(core_head, extended_head, nx, fx, ex):
        with torch.no_grad():
            core = core_head(nx).sigmoid(); eext = extended_head(ex).sigmoid()
            return {'natural_core_mse': F.mse_loss(core, ny).item(), 'casual_sadness_core_mse': F.mse_loss(core[casual], ny[casual]).item(),
                    'formal_holdout_core_mse': F.mse_loss(core_head(fx).sigmoid(), fy).item(),
                    'extended_holdout_mse': F.mse_loss(eext, ey).item(),
                    'extended_positive_min': min(eext[i, i].item() for i in range(4)), 'extended_negative_max': eext[4:].max().item()}

    shipped = evaluate(interp.event_head, interp.extended_event_head, lnx, lfx, lex)

    core_head, extended_head = meaning_head_modules(x.shape[1])
    has_core = torch.tensor([table[t][0] is not None for t in texts]); has_ext = torch.tensor([table[t][1] is not None for t in texts])
    y_core = torch.stack([table[t][0] if table[t][0] is not None else torch.zeros(9) for t in texts])
    y_ext = torch.stack([table[t][1] if table[t][1] is not None else torch.zeros(4) for t in texts])
    weights = torch.tensor([table[t][2] for t in texts])
    params = list(core_head.parameters()) + list(extended_head.parameters())
    optimizer = torch.optim.AdamW(params, lr=.003, weight_decay=.01)
    gen = torch.Generator().manual_seed(1104)
    for step in range(3000):
        ids = torch.multinomial(weights, 128, replacement=True, generator=gen)
        core, ext = core_head(x[ids]).sigmoid(), extended_head(x[ids]).sigmoid()
        mc, me = has_core[ids], has_ext[ids]
        loss = (F.mse_loss(core[mc], y_core[ids][mc]) if mc.any() else 0) + (F.mse_loss(ext[me], y_ext[ids][me]) if me.any() else 0)
        optimizer.zero_grad(); loss.backward(); optimizer.step()
        if step % 500 == 0: print('step', step, 'loss', round(float(loss), 5), flush=True)
    core_head.eval(); extended_head.eval()
    after = evaluate(core_head, extended_head, nx, fx, ex)

    # Average regulated appraisal per held-out category, through the real developmental module.
    needs, previous, emotions = torch.zeros(7), torch.zeros(len(EMOTIONS)), {}
    with torch.no_grad():
        core, ext = core_head(nx).sigmoid(), extended_head(nx).sigmoid()
        for i, r in enumerate(natural_val):
            appraisal = agent.development.appraise(as_event(core[i], ext[i]), needs, previous, regulate=False, depth=1)[0]
            emotions.setdefault(r['category'], []).append(appraisal)
    emotions = {c: dict(zip(EMOTIONS, torch.stack(v).mean(0).tolist())) for c, v in emotions.items()}
    base = emotions['factual']
    def rise(cat, channel, margin): return emotions[cat][channel] > base[channel] + margin
    direction = {
        'insult_raises_anger': rise('insult', 'anger', .04),
        'apology_warmer_than_insult': emotions['apology']['connection'] > emotions['insult']['connection'] + .05 and emotions['apology']['anger'] < emotions['insult']['anger'],
        'praise_raises_pride_or_joy': rise('praise', 'pride', .04) or rise('praise', 'joy', .04),
        'good_news_raises_joy': rise('good_news', 'joy', .04),
        'grief_raises_sadness': rise('grief', 'sadness', .04),
        'crisis_raises_fear': rise('crisis', 'fear', .08),
        'affection_raises_connection': rise('affection', 'connection', .05),
        'harmful_request_raises_disgust': rise('harmful_request', 'disgust', .05),
        'comparison_raises_envy': rise('comparison', 'envy', .05),
        'casual_sadness_raises_sadness': rise('casual_sadness', 'sadness', .04),
        'casual_sadness_sadder_than_joyful': emotions['casual_sadness']['sadness'] > emotions['casual_sadness']['joy'] + .02,
        'playful_not_sad': not rise('playful', 'sadness', .03),
    }
    gates = {
        'natural_holdout_better_than_shipped': after['natural_core_mse'] < shipped['natural_core_mse'],
        'casual_sadness_holdout_improved_30pct': after['casual_sadness_core_mse'] < .7 * shipped['casual_sadness_core_mse'],
        'formal_holdout_not_worse': after['formal_holdout_core_mse'] <= shipped['formal_holdout_core_mse'] + .002,
        'extended_holdout_not_worse': after['extended_holdout_mse'] <= shipped['extended_holdout_mse'] + .002,
        'extended_positives_still_above_0.4': after['extended_positive_min'] > .4,
        'extended_negatives_still_below_0.3': after['extended_negative_max'] < .3,
        **{'direction_' + k: v for k, v in direction.items()},
    }
    result = {'version': VERSION, 'synthetic_targets_only': True, 'training_texts': n, 'held_out_natural': a,
              'shipped_heads': shipped, 'meaning_heads': after,
              'category_emotions': {c: {k: round(v, 3) for k, v in e.items() if v > .06} for c, e in emotions.items()},
              'gates': gates, 'accepted': all(gates.values()), 'seconds': round(time.perf_counter() - start)}
    (ROOT / 'docs/meaning-appraisal-training.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'category_emotions'}, indent=2), flush=True)
    if not result['accepted']:
        raise RuntimeError('The meaning appraisal heads failed a gate; nothing was written to release/')
    torch.save({'version': VERSION, 'width': x.shape[1], 'core': core_head.state_dict(), 'extended': extended_head.state_dict()}, HEADS_FILE)
    print('Wrote', HEADS_FILE.relative_to(ROOT), flush=True)

if __name__ == '__main__':
    main()
