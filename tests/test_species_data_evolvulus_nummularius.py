"""Saved two-row groundcover, native modules and seasonal handoff."""
import json
import math
from pathlib import Path

import pygame

from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_assets import load_manifest,render_module,PixelEditorHost
from ui.pixel_art_editor_ui import PixelArtEditorUI
from world.world_model import WorldModel

SID='spec_evolvulus_nummularius'

def test_saved_packet_ancestry_modules_and_native_documents():
    world=WorldModel();raw=world.loader.get(SID);resolved=world.resolved_species_entity(SID)
    assert world.plant_catalogue.is_leaf_species(SID)
    assert raw['parents']==['cladis_dwarf_morning_glories_evolvulus']
    packet=json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())
    assert all(raw[k]==v==resolved[k] for k,v in packet['updates'].items())
    pygame.init();pygame.display.set_mode((1,1))
    try:
        for module in load_manifest(Path(f'assets/plant_asset_specs/{SID}.json'))['modules']:
            row=world.loader.get(module['illustration_id'])
            assert row['parents']==[SID]
            editor=PixelArtEditorUI(PixelEditorHost(world.loader))
            assert editor.open(row['id'])
            saved=pygame.image.load(row['media_path'])
            assert saved.get_size()==(75,75)
            assert pygame.image.tobytes(saved,'RGBA')==pygame.image.tobytes(render_module(module),'RGBA')
    finally:
        pygame.quit()

def test_mature_mat_is_bounded_rooting_reproductive_and_portable():
    world=WorldModel();e=world.resolved_species_entity(SID)
    def grown(age=178,lod=2):
        sim=SpeciesSimulation(species_entity=e,seed=303)
        sim.set_lod(lod);sim.set_age(age);return sim
    sim=grown();snap=sim.render_snapshot
    assert snap.stats['creeping_axis_count']==6
    assert snap.stats['creeping_rooting_contact_count']>0
    assert snap.stats['creeping_flower_count']>0
    assert grown(285).render_snapshot.stats['creeping_fruit_count']>0
    assert grown(11).render_snapshot.stats['estimated_leaf_count']<snap.stats['estimated_leaf_count']
    assert snap.bounds_m[5]<.1 and len(snap.placements)<1500
    assert all(-1<=p[1]<i and all(math.isfinite(x) for x in p[2:]) for i,p in enumerate(snap.placements))
    assert grown().render_snapshot.to_dict()==snap.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint()==sim.blueprint.fingerprint()
    assert all(grown(lod=lod).get_ecological_outcome()==sim.get_ecological_outcome() for lod in (0,1))
