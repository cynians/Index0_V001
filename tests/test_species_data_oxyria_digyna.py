"""Live identity, field transport, unknowns and exact native module reopening."""
import json
from pathlib import Path
import pygame
from world.world_model import WorldModel
from world.species_inheritance import is_authored_field
from simulations.species.plant_assets import PlantBlueprint

SID='spec_oxyria_digyna'
def test_live_species_fields_and_uncertainties_are_saved():
    w=WorldModel();raw=w.loader.get(SID);e=w.resolved_species_entity(SID)
    assert w.plant_catalogue.is_leaf_species(SID)
    assert raw['parents']==['cladis_oxyria']
    assert raw['binomial_name']=='Oxyria digyna'
    updates=json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text(encoding='utf-8'))['updates']
    for k,v in updates.items():
        assert raw[k]==e[k]==v
        if k!='wiki_entry':assert is_authored_field(raw,k)
    for k in ['max_root_depth','maturity_age','longevity','temperature_range','frost_tolerance','soil_ph_range']:
        assert not raw.get(k)
    bp=PlantBlueprint.from_species_entity(e,SID)
    assert bp.growth['paniculate_rosette_version']==1
    assert bp.growth['root_profile']['depth_source']=='stature_scaled_runtime_default'
    assert bp.growth['root_profile']['target_depth_m']==.375

def test_all_saved_pixel_documents_reopen_exact_reviewed_pixels():
    from tools.author_plant_assets import PixelEditorHost,load_manifest,render_module
    from ui.pixel_art_editor_ui import PixelArtEditorUI
    w=WorldModel();raw=w.loader.get(SID);host=PixelEditorHost(w.loader)
    manifest=load_manifest(Path(f'assets/plant_asset_specs/{SID}.json'))
    pygame.init()
    try:
        for m in manifest['modules']:
            illustration=w.loader.get(m['illustration_id'])
            assert illustration['parents']==[SID]
            assert raw[f"plant_{m['role']}_module_ref"]==illustration['media_path']
            saved=pygame.image.load(illustration['media_path'])
            assert saved.get_size()==(75,75)
            assert pygame.image.tobytes(saved,'RGBA')==pygame.image.tobytes(render_module(m),'RGBA')
            assert PixelArtEditorUI(host).open(illustration['id'])
    finally:pygame.quit()
