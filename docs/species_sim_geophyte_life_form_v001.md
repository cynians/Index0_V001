# Species Sim geophyte life form

## Selected ontology contrast

The live ontology contains `spec_codonorhiza_elandsmontana` (Elandsberg
paintpetal) with `plant_life_form = geophyte`. The existing three-tree
comparison—silver birch, English oak, and horse chestnut—uses
`plant_life_form = phanerophyte`.

This is a useful intrinsic comparison because Raunkiaer life form describes
the position of a plant's renewal buds. It does not require day/night,
seasonal, precipitation, or disturbance state from the environment sims.

## Field contract

- `plant_life_form = geophyte` creates one renewal bud below the soil marker.
- The aerial growth grammar begins at that bud.
- The root graph begins at its supporting renewal organ rather than at the
  soil marker.
- `belowground_storage` independently names that organ. Life form alone does
  not imply bulb, corm, rhizome, tuber, or a storage function.
- Until a measured bud depth field exists, depth is a bounded runtime default:
  8% of resolved mature height, clamped to 0.025–0.12 m and labelled
  `runtime_default` in snapshot statistics.
- Non-geophyte snapshots retain the prior surface-origin grammar.

The SANBI revision describes *Codonorhiza* as deciduous geophytes with
flat-based, broadly obconic corms, roots from the corm base, foliage inserted
at ground level, and aerial stems. Its *C. elandsmontana* description gives an
obconic corm 10–15 mm in diameter. That evidence supports authoring
`belowground_storage = ["corm"]` for this species and selecting the corm
renderer without inferring corms for all geophytes.

The general geophyte literature defines the habit by below-ground renewal-bud
placement and cautions against inferring storage physiology or organ type from
life form alone. The implementation follows that distinction.

Sources:

- [SANBI, Systematics of Codonorhiza](https://www.sanbi.org/wp-content/uploads/2024/05/2015_Strelitzia35.pdf)
- [Tribble et al., The evolution of the underground storage organ in geophytes](https://bsapubs.onlinelibrary.wiley.com/doi/10.1002/ajb2.1623)

## Reproducible comparison

Run:

```powershell
py -3.14 -m tools.render_codonorhiza_geophyte_comparison
```

The paired render uses one species, seed 303, mature age, LOD 2, and shared
physical scales. The control overrides only `plant_life_form` and
`belowground_storage`.

- Control: no renewal bud; root growth origin `z = 0.000 m`.
- Live geophyte: one renewal bud at `0.0372 m` below soil; corm/root growth
  origin `z = -0.0600 m`.
- Legacy live snapshot before implementation: 339 placements and no life-form
  state in the blueprint.
- Implemented live snapshot: 341 placements—the same shoot/root grammar plus
  one renewal organ and one renewal bud.

Artifacts:

- `artifacts/codonorhiza_geophyte_v001/life_form_comparison.png`
- `artifacts/codonorhiza_geophyte_v001/life_form_comparison_metrics.json`
- `artifacts/codonorhiza_geophyte_v001/ontology_fields_before.json`
- `artifacts/codonorhiza_geophyte_v001/authored_fields.json`

## Scope boundary

This pass does not model dormancy, fire response, seasonal emergence, stored
resource budgets, or environmental triggers. It also leaves the existing
`mature_height_class = low` value untouched; the renderer therefore still
resolves the generic 0.75 m class ceiling even though the SANBI description
reports plants 0.15–0.21 m high. That is a separate height-data correction,
not part of the life-form treatment.

