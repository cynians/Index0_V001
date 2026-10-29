# Person genetic DNA v001

Person Editor now has a deliberately small genotype-to-appearance skeleton.
The durable `genetic_dna` field is one opaque, versioned string beginning with
`I0DNA1_`. Its binary payload contains a format version, one skin-tone locus,
24 genome bytes, and a CRC32 corruption check.

The shared human visual baseline follows the project's reference sketch:
a small vertical oval head, very narrow torso, long close-hanging arms, and
legs that occupy more than half the total height. This remains the center of
the human variation envelope, while six DNA loci now vary stature, leg length,
arm length, torso width, shoulder width, and head size. The bounded ranges keep
every generated body recognizably within the long, spindly art direction.

## Current authored traits

The first locus has three simulation-palette values: `light`, `medium`, and
`deep`. Each decodes to a fixed RGB swatch used by the editor mannequin and by
the Person Simulation tokens. Changing the tone rewrites only that locus and
preserves all reserved bytes. Missing DNA creates a deterministic, unsaved
medium-tone preview; invalid or future strings remain visibly invalid rather
than being silently persisted.

The first six genome bytes decode to normalized body-shape values. Editor
minus/plus controls rewrite only the selected byte and checksum; skin tone and
all other morphology loci remain stable. The same decoded proportions drive
the editor mannequin and Person Simulation map glyphs.

These three broad display swatches are a visual prototype, not a calibrated
model of melanin, ancestry, ethnicity, health, behavior, or social identity.
No such property is inferred from the locus. Future work should replace or
extend the palette only alongside a better phenotype model.

## Clothing item sub-category

Clothing is not a separate entity type. `cat_clothing` is an ordinary child of
`cat_manufactured_good`, and both representative garments are regular `items`:
`item_test_toga` and `item_test_suit`. Each item carries wearable slots and a
small appearance profile. A person's `equipped_clothing` relation selects the
item layered over the naked DNA-derived body. Selecting, removing, or changing
clothing never rewrites the DNA string.

Any item categorized directly under `cat_clothing`, or under a descendant
category whose parent chain reaches it, receives a **Clothing Editor** launch
affordance. The resolver walks that chain with cycle protection, so future
categories such as formalwear or footwear do not need hardcoded item IDs.

The Clothing Editor reuses Pixel Studio. Its Reference fit contains an
editable garment layer over a translucent, locked `Human DNA guide` layer.
The Small and Large tabs are read-only previews derived from that one garment
drawing. Their landmark warp responds independently to stature, leg length,
arm length, torso width, shoulder width, and head size. Saving stores the
compact pixel document under `assets/clothing/designs/` and leaves only its
project-relative reference plus sizing metadata on the ordinary item entity.

## Reproduction and checks

- Codec and trait mapping: `simulations/person/person_genetics.py`
- Editor state and mutation: `simulations/person/person_editor.py`
- Live renderer: `simulations/person/person_renderer.py`
- Clothing fitting and category ancestry: `simulations/clothing/clothing_design.py`
- Clothing Pixel Studio host: `simulations/clothing/clothing_simulation.py`
- Ontology schema authoring: `tools/author_person_genetics_model.py`
- Automated invariants: `tests/test_person_genetics.py`
- Clothing editor invariants: `tests/test_clothing_editor.py`
- Body variation comparison: `artifacts/person_editor_v001/person_editor_body_variation.png`
- Clothing item comparison: `artifacts/person_editor_v001/person_editor_clothing_items.png`

Acceptance criteria for v001 are deterministic generation, checksum failure
visibility, round-trip support for all three tones, preservation of reserved
loci, directional and bounded morphology controls, a repository launch
affordance, an in-simulation Person Editor entry, ordinary categorized garment
items, descendant-category clothing editor launching, locked human tracing,
derived size previews, and visible use of the decoded body in both editor and
runtime paths.

Remaining limits: inheritance, recombination, parent/child relationships,
polygenic continuous pigmentation, facial features, garment condition,
thermal or social clothing effects, direct DNA text editing, and clipboard
import/export are intentionally not modeled yet.
