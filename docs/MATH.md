# The math behind Friday (V14, build v35)

Friday is a small **appraisal-based emotion model** wrapped around a frozen language model. A message is turned into an
appraisal of what it means *for Friday*. That appraisal drives a 19-dimensional emotional state with its own dynamics,
memory and lifelong learning. The state then shapes how Friday chooses to respond, and a separate local LLM puts it
into words. Every equation below is taken from the code (`src/`). All learned targets are **declared synthetic engineering
targets, not measurements of human emotion**, and nothing here claims subjective experience.

## 1. Perception: text → meaning features
A frozen **SmolLM2-135M-Instruct** encodes each message. Friday uses the last token's hidden state, layer-normalized:

$$h = \mathrm{LayerNorm}\big(\mathrm{SmolLM2}(\text{prompt}(x))_{\text{last}}\big) \in \mathbb{R}^{576}$$

Two small trained heads read $h$ (`semantic_interpreter.py`):
- **Event classifier** (576 → 256 → 11, tanh): ordinary, correction, feedback, introduction, relationship, preference,
  self-question… Rule-based validators then check names, quotes and corrections against the actual text.
- **Own-event appraisal** (576 → 64 → 9 and 576 → 64 → 4, sigmoid) produces Friday's appraisal vector

$$e = (\text{relevance},\ \text{progress},\ \text{certainty},\ \text{control},\ \text{novelty},\ \text{safety},\ \text{support},\ \text{effort},\ \text{agency} \mid \text{aversion},\ \text{comparison},\ \text{vastness},\ \text{devaluation})$$

  Progress, safety and agency are rescaled to $[-1,1]$ ($2\sigma(\cdot)-1$). Agency $>0$ means the other person caused the event;
  agency $<0$ means Friday did. A strong extended appraisal raises relevance: $e_{\text{rel}} \leftarrow \max(e_{\text{rel}},\, 0.7\max e_{\text{ext}})$.
  The heads are trained by mean-squared error on 1,452 labelled texts: formal sentences, plus 516 natural conversational
  messages in 27 categories (insults, apologies, grief, crisis, good news, sarcasm…). Acceptance gates must pass before a checkpoint is installed.

  **Since v35** the shipped appraisal heads read $h$ together with the MiniLM sentence vector $m$ (all-MiniLM-L6-v2, unit length,
  the model Friday already uses to recall memories by meaning):

  $$h' = [\,h,\ 4m\,] \in \mathbb{R}^{960}, \qquad (960 \to 64 \to 9 \text{ and } 960 \to 64 \to 4,\ \text{sigmoid})$$

  The factor 4 puts $m$ on roughly the scale of the layer-normalized $h$. With $h$ alone, sad news said casually ("i cried in the
  supply closet") read as joy. These heads are trained from scratch on the same table plus a 28th category, casual sadness
  (1,477 texts, `src/train_meaning_appraisal.py`), and must beat the earlier heads on the held-out natural messages and pass
  every gate. They ship as `release/appraisal-heads.pth`, outside the checkpoint; without the file or the MiniLM model,
  the checkpoint's own heads above are used.

Finally, the relevance is scaled by Friday's goal weights $g$: $e_{\text{rel}} \leftarrow e_{\text{rel}}\,(0.5 + 0.5\,g_{\text{goal}})$.

## 2. Appraisal → emotion (`developmental_emotion.py`)
The appraiser input concatenates the event, Friday's learned expectation for this *kind* of event (its cue), and current
need deficits:

$$x = [\,e,\ \hat{p}_{\text{cue}},\ \hat{c}_{\text{cue}},\ e_{\text{progress}} - \hat{p}_{\text{cue}},\ n\,]$$

where $\hat p$ is expected progress, $\hat c$ learned control, $e_{\text{progress}}-\hat p$ the **prediction error**, and $n$ the deficits of 7 needs
(competence, uncertainty management, affiliation, safety, resources, care effectiveness, task coherence), each
$n_i = \max(0, 0.4 - q_i) + \max(0, q_i - 0.6)$ for a need level $q_i$.

A small MLP (23 inputs → 48 → 19) proposes the 19 emotions (anger, sadness, fear, joy, shame, connection, stress, calm, confusion,
surprise, pain, disgust, contempt, guilt, pride, interest, awe, envy, vulnerability). Irrelevant events cannot produce emotion:

$$a = (1-e_{\text{rel}})\cdot 0.025 + e_{\text{rel}}\,\sigma(\mathrm{MLP}(x))$$

The MLP was fitted to an explicit **appraisal specification**. With effective control $\kappa = 0.6\,e_{\text{control}} + 0.4\,\hat c$,
threat $\tau = \mathrm{clip}(\max(0,-e_{\text{safety}}) + 0.55\max(0,-\hat p) + 0.2(1-e_{\text{cert}}),\,0,1)$,
loss $\ell = \max(0,-e_{\text{prog}})$ and gain $\gamma = \max(0, e_{\text{prog}})$:

| Emotion | Specification |
|---|---|
| fear | $\tau(1-0.55\kappa)$ |
| stress | $(0.6\tau + 0.4\ell + 0.25\,e_{\text{effort}})(1-0.3\kappa)$ |
| sadness | $\ell(1-0.65\kappa)$ |
| anger | $\ell\,\kappa\,\max(0,e_{\text{agency}})$, a loss caused by someone else that could be contested |
| guilt / shame | $\ell\,\max(0,-e_{\text{agency}})$, scaled by certainty / uncertainty |
| joy | $\gamma(0.7 + 0.3\,e_{\text{cert}})$ |
| pride | $\gamma\,\max(0,-e_{\text{agency}})$ |
| calm | $(0.65\kappa + 0.35\max(0,e_{\text{safety}}))(1-\tau)$ |
| connection | $e_{\text{support}}$ |
| confusion | $(1-e_{\text{cert}})(0.4 + 0.6\,e_{\text{novelty}})$ |
| interest | $e_{\text{novelty}}(1-0.5\tau)$ |
| surprise | $\lvert e_{\text{prog}} - \hat p\rvert\, e_{\text{novelty}}$ |
| pain, vulnerability | $0.5\,\ell(1-\kappa)$, $\ \tau(1-\kappa)$ |
| disgust, envy, awe, contempt | aversion·certainty, comparison(0.5+0.5·cert)(1−0.5γ), vastness(0.5+0.5·novelty)(1−0.5τ), devaluation·certainty·max(0,agency) |

Each target is $0.025 + \text{importance}\cdot\text{value}$, clipped to $[0,1]$.

**Emotional depth (differentiation).** Early on, related emotions are blurred together. With depth $d \in [0,1]$,
$a \leftarrow (1-d)\,\bar a_{\text{group}} + d\,a$, using groups such as {fear, stress, pain, vulnerability} and {joy, calm, connection, pride}.
Depth grows with real conversational evidence: $d = 1 - e^{-E/20}$, where $E$ counts corrections, feedback, confirmed lessons
and (capped) disclosed synthetic education.

**Regulation.** A second MLP chooses a strategy, biased by how well each has worked before:
none, *check evidence*, *reappraise* (fear and stress scaled by $1 - 0.25\,\text{control}\cdot\text{certainty}$, only with real safe evidence),
or *seek support* (stress scaled by $1 - 0.15\,\text{support}$). Elevated carried fear or stress (> 0.6) forces an evidence check.

**Dynamics: persistence, fast onset, slow recovery.**

$$\rho = \mathrm{clip}(\pi + 0.12\,s_{t-1}^2,\ 0.35,\ 0.92),\qquad \rho \leftarrow 0.45\,\rho \ \text{ where the target exceeds } s_{t-1} + 0.05$$

$$s_t = \rho\, s_{t-1} + (1-\rho)\,\mathrm{clip}(a_{\text{reg}} + 0.2\,b,\ 0, 1)$$

$\pi$ is a learned per-emotion persistence and $b$ a learned baseline mood. Between messages, emotion relaxes toward a resting tone
with a half-life that also depends on learned persistence:

$$s(t) = r + (s - r)\,2^{-t/T},\qquad T = 60 + 240\,\pi \ \text{seconds},\qquad r = 0.025 + 0.2\,b$$

## 3. Lifelong learning from outcomes
When an outcome is observed (verbal feedback in conversation, or a measured outcome), Friday updates its memory for that cue
(up to 64 cues):

$$\hat p_{\text{cue}} \leftarrow \hat p_{\text{cue}} + \eta\,(o - \hat p_{\text{cue}}),\qquad \eta = \max\!\big(0.025,\ 0.15/\sqrt{1 + \text{visits}/20}\big)$$

The learning rate shrinks with experience but never reaches zero, so emotions stay fluid. Learned control, the value of each
regulation strategy, the baseline mood $b$ (good outcomes pull toward joy, calm and pride; bad ones toward fear, stress and sadness, rate 0.01)
and persistence $\pi$ (toward 0.5 after safe successes, 0.78 after setbacks, rate 0.02) all adapt the same way. The result is that
**the same message can come to feel different over time** for Friday.

## 4. The V14 core: mood → attention → action (`model.py`)
- **Mood vector.** The emotion state is projected onto 19 GloVe anchor words (*angry, sad, scared, happy, …*) and weighted toward the strongest emotions:
  $m = \sum_i s_i^3\,A_i / \sum_i s_i^3$.
- **Affective attention.** Mood multiplicatively gates the token representations used for queries and keys (values are unchanged):
  $\tilde c = c \odot (1 + 0.3\tanh(W_g m))$, then multi-head attention and a feed-forward block.
- **Fast associative memory.** A Hebbian outer-product memory with decay: $F_t = \mathrm{clip}_{\|\cdot\|\le 2}(0.9\,F_{t-1} + 0.05\,v k^\top)$.
- **Two action systems with smooth arbitration.** A reflex policy (from a GRU "gut" state) and a deliberate policy (from the affect vector)
  over five actions: answer, clarify, comfort, verify, set boundary. Distress shifts control toward the reflex:

$$\mu = \tfrac{1}{3.5}(1.2\,\text{stress} + 0.8\,\text{fear} + 1.5\,\text{pain}),\qquad \lambda = \sigma(8(\mu - 0.75) - 2\,\text{deliberation})$$

$$\pi(a) = \lambda\,\mathrm{softmax}(W_r\,\text{gut}) + (1-\lambda)\,\mathrm{softmax}(W_s\,\text{affect})$$

- **Vitality.** A signed well-being estimate from need satisfaction, smoothed with decay 0.8.

## 5. From state to words
In the shipped CPU mode, replies are written by a local **Qwen3.5-4B** (llama.cpp), which is **prompted, not fine-tuned**. Each turn it receives the actual
emotional state rendered as words ("mild curiosity, faint tension"), the appraisal, the two top action preferences from $\pi$, and verified
memory facts. A rule-based reply monitor checks specific invariants (false memories, denying feelings it has, missed safety checks, promises it
can't know, confusing who said what…). It regenerates or repairs a draft that fails.

## Limits
The appraisal specification and training targets are hand-designed. The text→appraisal heads are tiny and read two small frozen encoders
(135M and 22M parameters). The language model only *describes* the state; it isn't trained on it. In the last red-team where every reply
was read, 5% of replies to new people were real failures (`docs/v33-full-redteam.md`; v35's results are in `docs/v35-feelings.md`).
This is an engineering model of appraisal and emotional dynamics, not evidence of feeling or consciousness.
