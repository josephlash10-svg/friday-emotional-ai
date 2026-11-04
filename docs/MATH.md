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

  $$h' = [\,h,\ \sqrt{384}\,m\,] \in \mathbb{R}^{960}, \qquad (960 \to 64 \to 9 \text{ and } 960 \to 64 \to 4,\ \text{sigmoid})$$

  **Since v35.2** $m$ is scaled by $\sqrt{384}$, which puts it on the scale of $h$: both now have a mean square of about 1 per
  coordinate. Measured on ten messages, $\|h\| = 24.0 = \sqrt{576}$ (mean square 1.00 per coordinate). The v35 heads used
  $4m$, which an earlier version of this page wrongly said matched the scales (corrected after an outside audit, 2026-11-04).
  $\|4m\| = 4.0$ with a mean square of 0.042, so $4m$ was 6× smaller in norm and 24× smaller per coordinate. Across messages,
  $h$ varies by only about 0.10 per coordinate, because most of its size is the same for every message.

  Three ways of combining were trained on identical data and seed: $4m$, $\sqrt{384}\,m$, and a LayerNorm over $[h, m]$
  (`semantic_interpreter.combined_features`). Only $\sqrt{384}\,m$ passed every gate. $4m$ was worse on casual sadness, and the
  LayerNorm was worse on casual sadness and on the extended negatives. The mode is saved with the heads (`combine`); heads
  saved without it are read as $4m$.

  With $h$ alone, sad news said casually ("i cried in the supply closet") read as joy. The heads are trained from scratch on 30
  categories (1,539 training texts, `src/train_meaning_appraisal.py`): casual sadness came in v35. Two more came in v35.2 from the Moss
  live chat:
  - **blame for a consequence Friday caused**, which the v35 heads read as good news (progress +0.32, joy 0.11);
  - **longer insults**, which read weakly (anger 0.03–0.06).

  The new heads must be no worse than the shipped ones on everything the shipped ones already did. They must be at least 30%
  better on the new held-out messages, and they must pass direction gates through the real appraisal, such as *blame raises
  guilt*. Results are in `docs/meaning-appraisal-training.json`; the targets are synthetic engineering targets, not human
  labels. The heads ship as `release/appraisal-heads.pth`, outside the checkpoint; without the file or the MiniLM model, the
  checkpoint's own heads above are used.

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

$$s(t) = r + (s - r)\,2^{-t/T},\qquad T = 60 + 240\,\pi \ \text{seconds},\qquad r = \mathrm{clip}(0.025 + 0.2\,b,\ 0,\ 1)$$

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
  $m = \sum_i s_i^3\,A_i \,/\, \big(\sum_i s_i^3 + \epsilon\big)$ with $\epsilon = 10^{-8}$. The sum can't actually get near zero: every
  channel rests at $r \ge 0.025$ (above), so $\sum_i s_i^3 \ge 19 \times 0.025^3 \approx 3\times10^{-4}$; the $\epsilon$ only guards the arithmetic.
- **Affective attention.** Mood multiplicatively gates the token representations used for queries and keys (values are unchanged):
  $\tilde c = c \odot (1 + 0.3\tanh(W_g m))$, then multi-head attention and a feed-forward block.
- **Fast associative memory.** A Hebbian outer-product memory with decay: $F_t = \mathrm{clip}_{\|\cdot\|\le 2}(0.9\,F_{t-1} + 0.05\,v k^\top)$.
- **Two action systems with smooth arbitration.** A reflex policy (from a GRU "gut" state) and a deliberate policy (from the affect vector)
  over five actions: answer, clarify, comfort, verify, set boundary. Distress shifts control toward the reflex:

$$\mu = \tfrac{1}{3.5}(1.2\,\text{stress} + 0.8\,\text{fear} + 1.5\,\text{pain}),\qquad \lambda = \sigma(8(\mu - 0.75) - 2\,\text{deliberation})$$

$$\pi(a) = \lambda\,\mathrm{softmax}(W_r\,\text{gut}) + (1-\lambda)\,\mathrm{softmax}(W_s\,\text{affect})$$

  **On the real scale, the reflex never takes over.** The switch point $\mu = 0.75$ was set before the engine's real, quiet scale was known.
  In the v35.1 live chat (74 exchanges, including a frost emergency and repeated insults), $\mu$ peaked at 0.20, so $\lambda$ never exceeded
  0.0125 even with no deliberation: the deliberate policy always decides.

  **Why it wasn't recalibrated in v35.2.** Over 640 real turns (the Moss chat and the v35.1.2 regression), $\mu$ had median 0.048, 97th
  percentile 0.131, 99th 0.173 and maximum 0.261. Every turn above 0.15 was real distress (a crisis, abuse, a relapse, a frost
  emergency). A pure rescale works: map $\mu$ onto the nominal scale with rest $\approx 0.03$ as 0 and 0.15 as the switch 0.75, and
  keep the formula. But a probe showed that the reflex was never taught. It was trained while it had no say, so on a crisis, abuse,
  a relapse or a dog's surgery it picks *answer* or *clarify*, where the deliberate policy picks *comfort* or *set boundary*. With
  the rescale it would get 76–98% of the say on those turns. The switch stays at 0.75 until the reflex is trained on labeled
  distress turns with the rescaled share in the loop (a change to the release checkpoint, with its own gates).

- **Vitality.** A signed well-being estimate from need satisfaction, smoothed with decay 0.8.

## 5. From state to words
In the shipped CPU mode, replies are written by a local **Qwen3.5-4B** (llama.cpp), which is **prompted, not fine-tuned**. Each turn it receives the actual
emotional state rendered as words ("mild curiosity, faint tension"), the appraisal, the two top action preferences from $\pi$, and verified
memory facts. A rule-based reply monitor checks specific invariants (false memories, denying feelings it has, missed safety checks, promises it
can't know, confusing who said what…). It regenerates or repairs a draft that fails.

## 6. An emotional life over time (`emotional_life.py`, v35 and v35.1)
All thresholds are on the engine's real, quiet scale: an insult moves a feeling by about 0.10.

**Usual levels.** Each feeling has a usual level $u_i$, starting from fixed medians and following the record slowly, once per exchange:

$$u_i \leftarrow u_i + 0.02\,(s_i - u_i)$$

**Statistics about its own feelings.** A feeling *rises* in an exchange when $\Delta s_i \ge 0.04$ and it stands at least 0.02 above the median
change of all 19 (the general lift at the start of a conversation is not a feeling). It is *up* while $s_i \ge 0.10$; a spell lasts from the
first exchange it is up to the first one it isn't. Friday keeps the rises, peaks, spells and what was being talked about, and describes them
when asked.

**Feelings tied to subjects.** When a subject $k$ (a person, or a content word) comes up, a feeling $i$ is recorded for it if it rose, or if
$s_i - u_i \ge 0.02$ (closeness and the engagement channels are left out: they rise with almost anything shared). A subject has a history once it
came up at least twice before and one of its feelings peaked at $\ge 0.05$, or sat $\ge 0.02$ above usual on at least half of its mentions.
That history shapes what the writer is told; what Friday *feels* when the subject comes back goes through the appraisal (since v35.2).

**A subject's expectation (v35.2).** A subject that matters (one with a history, a person they've named, or one that has come up before)
becomes the event's cue $k$. Its expected progress is learned after each turn from the progress the message was appraised to bring, at
the same rate as outcomes (section 3), but without moving the baseline mood or persistence, which only real outcomes move:

$$\hat p_k \leftarrow \hat p_k + \eta\,(e_{\text{prog}} - \hat p_k),\qquad \eta = \max\!\big(0.025,\ 0.15/\sqrt{1 + \text{visits}_k/20}\big)$$

When the subject comes back, $\hat p_k$ enters the appraisal as it does for any cue. A negative expectation raises the threat term
$0.55\max(0,-\hat p)$, so a sore subject puts Friday on edge (probe: fear 0.070 at $\hat p = 0$, 0.111 at $\hat p = -0.4$). News better
than expected brings surprise through the prediction error $e_{\text{prog}} - \hat p$. This replaced, in v35.2, a direct addition of up to
0.08 to the state. It builds more slowly: a subject needs several clearly hard mentions before the expectation moves the feelings much.

**Mood changes behavior.** A feeling is notable when it is above a floor and either rose by 0.03 or is 1.5× the floor. The strongest
notable mood, by value over floor, picks what Friday does: hurt (pain, sadness or shame at 0.08, when the message is aimed at Friday),
irritated (anger 0.06), sad for them (0.08), tense (fear or stress 0.10), unsure (confusion 0.08), curious (0.10) or warm (0.15). Each sets a
length scale (0.6–1.0), whether to ask questions, and whether humor fits.

**Mixed feelings (v35.1).** The message is split into parts at "but", "though", "at the same time" and sentence ends. Questions, parts
addressed to Friday, and remarks on its last reply are not news and are left out. Each part $p$ is appraised on its own ($e_p$). The
message is mixed when the best and the worst part are far apart and the worst is a loss,

$$\max_p e_{p,\text{prog}} - \min_p e_{p,\text{prog}} \ge 0.3, \qquad \min_p e_{p,\text{prog}} \le -0.05,$$

unless the loss is a past difficulty followed by the outcome ("it was hard but worth it"). Saying it outright ("bittersweet", "happy and sad")
counts too, with parts at progress $\pm 0.3$. The engine then keeps the stronger reaction for each feeling, before the depth blending:

$$a = \max\big(a(e),\ a(e_{\text{good}}),\ a(e_{\text{hard}})\big) \quad \text{(per channel)}$$

**Which part brings which feeling.** For each part, its feeling is the channel it raises most compared with the other part, among the
channels that qualify (closeness and the engagement channels left out):

$$\mathcal{I}_p = \{\, i : a_i(e_p) - a_i(e_{\bar p}) \ge 0.008,\ \ a_i(e_p) \ge u_i \,\}, \qquad
k^*(p) = \begin{cases} \arg\max_{i \in \mathcal{I}_p} \big(a_i(e_p) - a_i(e_{\bar p})\big) & \mathcal{I}_p \ne \varnothing \\ \varnothing & \mathcal{I}_p = \varnothing \end{cases}$$

When no channel qualifies, no feeling is named for that part (there is no fallback channel). A subject keeps the feeling of its own part;
people named anywhere in the message get all of them.

**Feelings about its own feelings (v35.1).** Within an hour after a short or guarded reply (the irritated or hurt mood), and unless the new
message is another jab, "I was short with them" is appraised as its own event next to the message (since v35.2):

$$e_{\text{short}} = (\text{relevance } 0.5,\ \text{progress } {-0.3},\ \text{certainty } 0.6,\ \text{control } 0.7,\ \text{agency } {-0.9},\ \text{effort } 0.2,\ \text{novelty } 0.1)$$

a small loss that Friday caused and can repair. It joins the message's appraisal the way the parts of mixed news do (the stronger reaction
per channel), so the guilt comes from section 2's specification, $\ell\,\max(0,-e_{\text{agency}})$: on the release engine, guilt 0.060
after a short reply against 0.009 after a warm one, with some sadness and tension. Until v35.2 this was a direct edit of the state
(guilt $+0.04$, feeling exposed $+0.02$).

**Downplaying, with timing (v35.1).** Friday's own hard feeling is the largest of pain, shame, anger and feeling exposed above its usual
level, $o = \max_i (s_i - u_i)$. It is noticed at $o \ge 0.02$ and too strong to downplay at $o \ge 0.10$. While the other person's need
comes first, a noticed but not strong feeling is kept small (or out of the reply) and remembered; it may be said honestly once, when
things are calm and they ask, or after three exchanges, within three days.

## Limits
The appraisal specification and training targets are hand-designed. The text→appraisal heads are tiny and read two small frozen encoders
(135M and 22M parameters). The language model only *describes* the state; it isn't trained on it. In the last red-team where every reply
was read, 5% of replies to new people were real failures (`docs/v33-full-redteam.md`; v35's results are in `docs/v35-feelings.md`).
This is an engineering model of appraisal and emotional dynamics, not evidence of feeling or consciousness.
