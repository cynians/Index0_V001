"""Horse chestnut color calibration preserves its existing leaf geometry."""

from copy import deepcopy

import pytest

from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates
from world.species_inheritance import is_inheritable_species_field
from world.world_model import WorldModel


SPECIES_ID = "spec_aesculus_hippocastanum"


def test_saved_palette_changes_color_without_changing_growth_or_ecology():
    entity = WorldModel().resolved_species_entity(SPECIES_ID)
    palette = entity["plant_leaf_palette"]
    assert not is_inheritable_species_field("plant_leaf_palette")

    control = deepcopy(entity)
    control.pop("plant_leaf_palette")
    old = SpeciesSimulation(species_entity=control, species_id=SPECIES_ID, seed=303)
    new = SpeciesSimulation(species_entity=entity, species_id=SPECIES_ID, seed=303)
    for sim in (old, new):
        sim.set_lod(2)
        sim.set_age(365)

    assert old.blueprint.module("leaf").asset_ref is None
    assert old.blueprint.fingerprint() != new.blueprint.fingerprint()
    assert old.render_snapshot.placements == new.render_snapshot.placements
    assert old.render_snapshot.placement_paths == new.render_snapshot.placement_paths
    assert old.render_snapshot.bounds_m == new.render_snapshot.bounds_m
    assert old.render_snapshot.stats == new.render_snapshot.stats
    assert old.get_ecological_outcome() == new.get_ecological_outcome()

    renderer = SpeciesRenderer(None)
    assert renderer._color("leaf", new) == tuple(palette["mature_rgb"])
    visible_colors = {renderer._color("leaf", new, index) for index in range(39)}
    assert visible_colors == {tuple(palette[key]) for key in ("mature_rgb", "shade_rgb", "pale_rgb")}
    assert renderer._color("leaf", old) != renderer._color("leaf", new)


@pytest.mark.parametrize("bad", [
    {"mature_rgb": [55, 111, 55], "shade_rgb": [39, 87, 45]},
    {"mature_rgb": [55, 111, 55], "shade_rgb": [39, 87, 45], "pale_rgb": [256, 126, 76]},
    {"mature_rgb": [55, 111, 55], "shade_rgb": [39, 87, 45], "pale_rgb": [86, True, 76]},
])
def test_invalid_palette_is_rejected(bad):
    with pytest.raises(AuthoringError):
        validate_updates({"plant_leaf_palette": bad})
