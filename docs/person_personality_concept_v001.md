# Personality: Big Five terms, people and decisions (proposal v001)

Status: proposal, 2026-10-28. Nothing here is built. It turns the owner's
direction into a design to agree on before slices start. It extends the
layer overview (v007, the personality paragraphs under persons and pops):
adjectives are readable handles on Big Five coordinates, and decision logic
asks how a person's field biases a choice.

## 1. Owner's direction (2026-10-28)

- Every person has a baseline Big Five distribution, which may change over
  their life.
- Personality words (cruel, generous, conscientious, ...) are defined once,
  each with its place in the Big Five space.
- Persons and decisions are both authored by assigning such words. The
  words are synthesised into a Big Five position, and a decision is
  compared with the person who weighs it (and people with each other).
- Example: torture is done by very cruel or sadistic people, or by people
  who follow orders blindly. Whether someone tortures depends on where the
  decision's traits fall, where the person's traits fall, and how they
  overlap.

## 2. What exists

| Piece | State |
|---|---|
| Big Five scores | `big_five_openness`, `_conscientiousness`, `_extraversion`, `_agreeableness`, `_neuroticism` on persons, 0-1; a missing score shows as a neutral 0.5 preview and is never invented (`get_personality_panel_model`). |
| Words | `personality_adjectives`, a free string list on persons ("curious", "dutiful", "reserved"). Shown on the Personality panel; nothing reads them. |
| Decisions | `_score_task` uses conscientiousness for work and duty compliance, agreeableness for compliance, neuroticism for coercion; the likely response to a conviction conflict reads agreeableness and conscientiousness. Tasks may carry `action_tags` ("kill"); convictions in a person's knowledge forbid tags. |
| Tags | Tag entities with a `tag_class`; need tags (`tag_class: need`) already carry structured meaning the way terms would. |

## 3. Why five axes are not enough on their own

Torture's "blind follower" profile is high agreeableness and high
conscientiousness. A kind person is high agreeableness too. With five
axes, a kind person (A 0.9) fits the follower profile (A 0.75, C 0.8,
O 0.25) at 0.52, better than a person with no traits at all (0.46): the
model would make kind people slightly *more* willing to torture under
orders. Obedience and kindness live in different facets of agreeableness
(cooperation and compliance versus sympathy and altruism). So words may
name facets where they need to; most words stay on the five axes.

The facets are the thirty of the public-domain IPIP-NEO, six per axis
(for agreeableness: trust, morality, altruism, cooperation, modesty,
sympathy; for conscientiousness: self-efficacy, orderliness, dutifulness,
achievement-striving, self-discipline, cautiousness; and so on).

## 4. Proposal

### 4.1 Terms are tag entities with a position

A personality term is a tag entity with `tag_class: personality` and a
position that names only the axes or facets the word speaks to, 0-1:

```
tag_trait_cruel      Cruel      sympathy 0.05, altruism 0.1
tag_trait_obedient   Obedient   cooperation 0.85, dutifulness 0.85, liberalism 0.25
tag_trait_shy        Shy        extraversion 0.15, neuroticism 0.65
```

Same mechanism as need tags: loose words, structured meaning, card chips,
and one place to correct a word for everyone who carries it. Anything a
word leaves out means "this word says nothing about it", not 0.5.

### 4.2 A person's position is synthesised from their words

- Authoring surface: `personality_adjectives` resolve to term tags by
  name, as tag strings resolve now.
- For each axis or facet: the mean of the words that name it. How many
  words agree gives a confidence. An axis's value is the mean of its
  facets where words named facets. Anything no word names stays a neutral
  0.5 at low confidence and is shown as such.
- An authored `big_five_*` score overrides the words on that axis; facets
  without words then take the axis value. The Personality panel shows
  each word's dot, the synthesised value and any override.
- Change over life (later): the baseline stays authored; events nudge it,
  recorded as dated snapshots on the person, the way other entities keep
  sparse year records.

### 4.3 Decisions carry who does them, and who refuses

- An action tag (`tag_class: action`) holds trait profiles: **for**
  profiles (alternatives: any one fits) and **against** profiles. Tasks,
  steps, jobs and recipes carry action tags, as tasks already carry
  `action_tags`. "Torture": for {cruel, sadistic} or {obedient}; against
  {kind} or {merciful}.
- **Fit** of a person to a profile: compare only what the profile names,
  using the person's facet where the profile names a facet (the axis value
  if the person has no facet value): `d = sqrt(mean((person - profile)^2))`,
  `fit = max(0, 1 - d / 0.5)`.
- In `_score_task`: `character = 120 x (best for-fit - 0.5) - 120 x
  max(0, best against-fit - 0.5)`, shown in the breakdown as "Character:
  fits Obedient (+60)" or "Character: against Kind (-60)". Duty, coercion,
  need and convictions stay separate terms, so an order to torture still
  presses on a kind person; it just loses more often, and the likely
  response reads the fit.

Worked example, "torture" ordered with the same duty pressure:

| Person | Words | Best for-fit | Against-fit | Character term |
|---|---|---|---|---|
| No words | | Obedient 0.36 | Merciful 0.43 | -17 |
| Kind | kind | Obedient 0.36 | Kind 1.0 | -77 |
| Brute | cruel | Cruel 1.0 | 0 | +60 |
| Conscript | obedient | Obedient 1.0 | Merciful 0.46 | +60 |

(An against-fit below 0.5 costs nothing: someone who is merely not cruel
is not thereby merciful.)

The kind person and the conscript feel the same order very differently;
the brute needs no order at all.

### 4.4 The need loop and other people

- Loop actions get action tags too: asking a stranger ("ask") fits
  sociable people, taking without leave fits greedy or careless ones,
  foraging fits curious ones. An option's rate is multiplied by
  `0.5 + fit`, so a shy person tries the machine or the bushes before
  asking the fishmonger, and an outgoing one asks first.
- Company: closeness is weighted by how alike two people are where it
  matters for getting on (agreeableness, extraversion):
  `closeness x (0.75 + 0.5 x similarity)`.

### 4.5 First word list (estimates to correct)

Placements are mine for a first pass, informed by the lexical tradition
behind the Big Five (personality adjectives cluster on five factors), not
measured loadings. Cruelty and sadism sit largely outside the five factors
in research; here they are very low sympathy and altruism.

| Word | Position |
|---|---|
| Curious | openness 0.85 |
| Imaginative | imagination 0.9 |
| Conventional | openness 0.15 |
| Orderly | orderliness 0.85 |
| Dutiful | dutifulness 0.85 |
| Disciplined | self-discipline 0.85 |
| Careless | conscientiousness 0.15 |
| Impulsive | immoderation 0.8, cautiousness 0.2 |
| Ambitious | achievement-striving 0.85, assertiveness 0.65 |
| Sociable | gregariousness 0.85 |
| Talkative | extraversion 0.85 |
| Reserved | extraversion 0.2 |
| Shy | extraversion 0.15, self-consciousness 0.75 |
| Brave | neuroticism 0.2, excitement-seeking 0.65 |
| Cowardly | anxiety 0.8, vulnerability 0.75 |
| Kind | sympathy 0.85, altruism 0.85 |
| Merciful | sympathy 0.85, cooperation 0.7 |
| Generous | altruism 0.9 |
| Trusting | trust 0.85 |
| Loyal | dutifulness 0.75, cooperation 0.7 |
| Obedient | cooperation 0.85, dutifulness 0.85, liberalism 0.25 |
| Rebellious | cooperation 0.2, liberalism 0.8 |
| Greedy | altruism 0.2, morality 0.25 |
| Suspicious | trust 0.2, anxiety 0.6 |
| Vengeful | cooperation 0.15, anger 0.75 |
| Callous | sympathy 0.1 |
| Cruel | sympathy 0.05, altruism 0.1 |
| Sadistic | sympathy 0.02, morality 0.1 |
| Calm | neuroticism 0.15 |
| Anxious | anxiety 0.85 |
| Volatile | anger 0.85, immoderation 0.7 |

## 5. Open decisions

1. Terms as tag entities (`tag_class: personality`), or a dataset of their
   own?
2. Words on axes and, where needed, facets (section 3), or axes only and
   accept that kind and obedient blur?
3. Words as the main authoring surface with numbers as overrides, or the
   other way round?
4. Decisions as action tags with for and against profiles, carried by
   tasks, steps, jobs and recipes; or profiles written on each decision?

## 6. Slices (once agreed)

| # | Slice | Proves |
|---|---|---|
| P1 | Term tags and the word list; synthesis with confidence; Personality panel shows words, synthesis and overrides | A person authored only with words gets a position |
| P2 | Action tags with for and against profiles; character term in `_score_task` and in the likely response; a torture order weighed by the four people of the worked example | The same order lands differently on different people |
| P3 | Fit on the need loop's actions; similarity in closeness | A shy and an outgoing person eat differently |
| P4 | Personality change over life as dated nudges | A person can change |

## 7. Owner's answers and what was built (2026-10-28)

Answers: five axes for now; words exclude decisions outright where needed
(a pacifist never considers Violence); a person has a Big Five baseline from
birth that their words move; need tags join the general tag rows; how
decisions are represented is open and will be remodelled.

Built: `world/personality.py`, Person Sim reading it for every decision,
excluded decisions refused outright and logged in the goal tree, a
"Character" term in the breakdown. Store: 33 personality words, action
tags Violence, Kill, Torture (`tools/author_personality_terms_model.py`).
Tests: `tests/test_personality.py`.

**A person is a distribution (owner, same day).** On each axis a person
is a mean and a spread, not a point:

- Birth: the mean drawn from the person's `birth_seed` (else their id)
  around the population mean, the spread the population's (0.15). The
  Person Editor gives a new person a random seed and can redraw it. With
  parents, the draw is made around them: each known parent pulls the mean
  by HERITABILITY / 2 (0.2) of their distance from the population mean,
  and the spread narrows by what they explain (person concept doc,
  Cycle 10). An authored score is a birth mean
  known more precisely (spread 0.08).
- Each word is evidence about the axes it names: a distribution around the
  word's position (spread 0.12). Birth and words combine by precision, so
  the mean moves toward the words as far as they are surer than birth, and
  the spread narrows with every word. (One word on a birth baseline moves
  the mean about 61 % of the way; the earlier fixed "halfway" rule is gone.)
- A decision's profile is a distribution too (its words' positions and
  spread). Fit is the overlap of the two, `exp(-mean(d^2 / 2(s_person^2 +
  s_profile^2)))` over the profile's axes, and a profile counts by how much
  better the person fits it than an average person of the population
  would: `character = 120 x (best for-excess) - 120 x max(0, best
  against-excess)`. An average person gets 0.

Measured for a person born exactly average, ordered to torture: no words 0,
Kind -43, Kind and Merciful -63, Cruel +54, Obedient +21 (obedience shares
high agreeableness with kindness on five axes; an exclusion settles it
where it must be categorical). A person born with low agreeableness leans
toward it with no words at all (one test person, birth A 0.18: +87), which
is what a birth baseline means. The worked example in section 4.3 predates
all of this.

The Personality panel draws the distribution as a band (mean +- spread),
the birth estimate as an outline, and each word as a diamond at its
position on every axis it names; the bars show the same.

## 8. Where the word positions should come from

The 33 placements are still my estimates. A measured source that fits:
Goldberg's 100 unipolar Big Five markers (Goldberg 1992, *Psychological
Assessment*, "The development of markers for the Big-Five factor
structure"), whose ratings by 554 participants of the Personality,
Motivation and Cognition Lab (Northwestern) ship as the dataset
`big5.100.adjectives` in the R package psychTools (GPL >= 2). A
five-factor analysis of those ratings gives every one of the 100 adjectives
its loadings on all five axes, which convert to positions; words outside
the 100 (cruel, obedient, pacifist, ...) take the position of their nearest
markers (cruel from unkind, harsh, cold). For finer placements, the
Abridged Big Five Dimensional Circumplex (Hofstee, de Raad & Goldberg 1992,
*JPSP*) places 540 adjectives by their two largest loadings, but its tables
are only in the paper.

**Done (2026-10-28).** `tools/derive_personality_word_positions.py` reads
the three data files straight out of `psychTools_2.6.4.tar.gz` (CRAN, no
package code runs), computes pairwise correlations of the 554 x 100
ratings, extracts five factors by principal axis factoring, rotates them
by varimax, and names and orients each factor by the package's own keys.
A word names an axis where its loading is at least 0.30; its position
there is `0.5 + 0.5 x loading`. All 100 markers became personality words
with their position, all five loadings and their source. 24 game words
that are not markers take the mean loadings of named nearest markers
(`position_from`, e.g. Cruel from Unkind, Harsh, Cold; Obedient from
Cooperative, Prompt; Pacifist from Kind, Cooperative, plus its exclusion
of Violence). `tools/author_personality_terms_model.py` no longer writes
word positions.

Sample of what the data says: Kind A 0.82, Warm A 0.85, Unkind A 0.16,
Organized C 0.90, Shy E 0.10 (and nothing on neuroticism, unlike my
estimate), Imaginative O 0.88, Anxious N 0.80, Talkative E 0.86. Measured
words are less extreme than my estimates (Cruel A 0.20, not 0.05). The
Big Five cannot tell Sadistic from Cruel.

Torture order with the measured words, for a person born exactly average:
no words 0, Kind -42, Kind and Merciful -63, Warm and Sympathetic -66,
Cruel +55, Cruel and Callous +69, Obedient +13, Obedient and Dutiful +18,
Pacifist -39 (and refuses outright).

Also built: the cards' **Tags tab** (`world/tag_rows.py`, `ui/card.py`),
replacing the bar on General. Rows: General, one row per tag class among the
tags (Needs), schema rows (`tag_rows` on a schema: Personality on people,
Needs on items and categories), and every tag-like field (`*_tags`,
`personality_adjectives`, component roles), plus a read-only Serves row.
Tags in use today: worldgen status on locations, material classification
and process/role/property/planet tags, climate tags, job requirement tags,
collection rule tags, need tags, wish types, component roles, topic labels.
