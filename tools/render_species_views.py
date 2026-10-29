"""Render saved species in isometric, top, side and developmental views."""
import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import (SpeciesRenderer, DiagnosticCamera,
    IsometricDiagnosticCamera, TopDownDiagnosticCamera, SurfaceElevationCamera,
    diagnostic_cell_bounds, top_down_diagnostic_bounds, canopy_visible_indices)
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


def fitted_bounds(snapshots, aquatic=False, min_margin=.03):
    """Use one metric envelope across views/stages, including actual organs."""
    bounds = []
    for axis in range(3):
        lo = min(s.bounds_m[axis*2] for s in snapshots)
        hi = max(s.bounds_m[axis*2+1] for s in snapshots)
        if axis == 2: lo = min(lo, 0.)
        margin = max(min_margin, (hi-lo)*.1)
        bounds.extend((lo-margin, hi+margin))
    if aquatic:
        floor = [-.8,.8,-.8,.8,-.65,.3]
        bounds = [min(b,floor[i]) if i%2==0 else max(b,floor[i]) for i,b in enumerate(bounds)]
    return bounds


def stage_ages(sim):
    if sim.blueprint.growth.get('reproductive_structure') == 'cone' and sim.blueprint.growth.get('reproductive_profile'):
        p=sim.blueprint.growth['reproductive_profile'];cycle=p['cycle_days']
        young=cycle*(p['flowering_start']+.35*(p['flowering_end']-p['flowering_start']))
        year=max(0,math.ceil((sim.mature_age_days-young)/cycle))*cycle
        return [('Young tree',sim.mature_age_days*.3),('Developed crown',sim.mature_age_days),
                ('Young cones',year+young),('Mature cones',year+cycle*(p['fruit_ripe']+.08))]
    if sim.blueprint.growth.get('rhizome_raceme_version'):
        p = sim.blueprint.growth['reproductive_profile']; cycle = p['cycle_days']
        return [('Young shoots',cycle*.22),('Lower flowers',cycle*(p['flowering_start']+.04)),
                ('Mixed raceme',cycle*(p['flowering_start']+.63*(p['flowering_end']-p['flowering_start']))),
                ('Capsules',cycle*.62),('Dormant rhizomes',cycle*.94)]
    if sim.blueprint.growth.get('offset_rosette_version'):
        p=sim.blueprint.growth['offset_rosette_profile']
        c=p.get('monocarpic_cycle')
        if c:
            return [('Vegetative',sim.mature_age_days*2.),
                    ('Rising stalk',sim.mature_age_days*(c['stalk_start_units']+c['bloom_start_units'])/2),
                    ('Flowering',sim.mature_age_days*(c['bloom_start_units']+c['bloom_end_units'])/2),
                    ('Spent mother',sim.mature_age_days*(c['mother_dead_units']+.5)),
                    ('Daughters',sim.mature_age_days*(c['mother_dead_units']+c['successor_maturation_units']))]
        return [('Young mother',sim.mature_age_days*.35),
                ('First offsets',sim.mature_age_days*(p['offset_onset_units']+.12)),
                ('Mixed-size colony',sim.mature_age_days*2.)]
    if sim.blueprint.growth.get('flower_fork_version'):
        start=sim.life_history_profile['reproductive_start_days']
        end=sim.life_history_profile['age_limit_days']
        return [('Young leafy axis',sim.mature_age_days*.25),
                ('Developed forks',sim.mature_age_days),
                ('Flowers',start+(end-start)*.04),('Berries',start+(end-start)*.98)]
    if sim.blueprint.growth.get('planar_spray_version'):
        return [('Young tree',sim.mature_age_days*.25),('Developed crown',sim.mature_age_days),
                ('Later evergreen crown',sim.mature_age_days*1.48)]
    if sim.blueprint.growth.get('renewing_cane_version'):
        p = sim.blueprint.growth.get('reproductive_profile') or {}
        cycle = p.get('cycle_days', 365.)
        flower = cycle*(p.get('flowering_start', .34)+p.get('fruit_start', .48))*.5
        flower += max(0, math.ceil((sim.mature_age_days-flower)/cycle))*cycle
        year = math.floor(flower/cycle)*cycle
        return [('Young canes', max(0., flower-50)), ('Flowering', flower),
                ('Hips', year+cycle*p.get('fruit_ripe', .68)),
                ('Winter framework', year+cycle*.94), ('Next flowering', flower+cycle)]
    if sim.blueprint.growth.get('seasonal_rhizome_version'):
        p = sim.blueprint.growth.get('reproductive_profile') or {}
        cycle = p.get('cycle_days', 365.)
        spring = cycle*(p.get('flowering_start', .22)+p.get('fruit_start', .32))*.5
        spring += max(0, math.ceil((sim.mature_age_days-spring)/cycle))*cycle
        year = math.floor(spring/cycle)*cycle
        return [('Spring emergence', year+cycle*(p.get('leaf_out_start', .12)+p.get('leaf_out_full', .22))*.5),
                ('Flowering', spring), ('Fruiting', year+cycle*(p.get('fruit_ripe', .43)+p.get('fruit_retention_end', .52))*.5),
                ('Summer dormancy | cutaway', year+cycle*.75), ('Next spring', spring+cycle)]
    if sim.blueprint.growth.get('creeping_upright_version'):
        return [('Young axes', sim.mature_age_days*.25),
                ('Expanding shoots', sim.mature_age_days*.65),
                ('Mature spore shoots', sim.mature_age_days*1.4)]
    if sim.blueprint.growth.get('moss_turf_version'):
        adult = sim.mature_age_days * 1.4
        return [('Young mat', sim.mature_age_days*.25), ('Expanding mat', sim.mature_age_days*.65),
                ('Wet mat', adult), ('Dry mat', adult), ('Rewetted mat', adult)]
    if sim.blueprint.growth.get("fungal_grammar_version"):
        recipe = sim.blueprint.growth["fungal_growth_profile"]["resolved"]
        first, cycle = recipe["first_flush_model_days"], recipe["flush_cycle_model_days"]
        flush = first + max(0, math.ceil((sim.mature_age_days-first-cycle*.45)/cycle))*cycle
        if sim.blueprint.growth.get('ground_fungal_version'):
            return [('Colonising soil', first*.55), ('Emerging bodies', flush+cycle*.04),
                    ('Expanding caps', flush+cycle*.235), ('Mature ascocarps', flush+cycle*.45),
                    ('Between flushes', flush+cycle*.84)]
        return [("Colonising wood", first*.55), ("Emerging shelves", flush+cycle*.04),
                ("Expanding shelves", flush+cycle*.235), ("Mature shelves", flush+cycle*.45),
                ("Between flushes", flush+cycle*.84)]
    stages = [("Young growth",sim.mature_age_days*.25), ("Full size",sim.mature_age_days),
              ("Flowering",sim.life_history_profile["reproductive_start_days"]+50)]
    if sim.blueprint.growth.get('growth_form')=='fern':
        stages[2]=('Later foliage',stages[2][1])
    profile = sim.blueprint.growth.get("reproductive_profile")
    if profile:
        # A nominal developmental age may be outside an authored bloom season.
        # Show a real flowering stage once the individual is mature.
        if ("flowering_start" in profile and "flowering_end" in profile
                and not any(p[0] == "flower" for p in sim.generate_snapshot(stages[2][1], 2).placements)):
            # Some body plans replace blooms with fruit on the same stalk.
            # Choose the flowering interval before fruit set for this panel.
            flower_age = profile["cycle_days"] * (profile["flowering_start"] + min(
                profile["flowering_end"], profile.get("fruit_start", profile["flowering_end"]))) / 2
            flower_age += max(0, math.ceil((sim.mature_age_days - flower_age) / profile["cycle_days"])) * profile["cycle_days"]
            stages[2] = ("Flowering", flower_age)
        fruit_age = profile["cycle_days"] * profile["fruit_ripe"]
        fruit_age += max(0, math.ceil((sim.mature_age_days - fruit_age) / profile["cycle_days"])) * profile["cycle_days"]
        if sim.life_state(fruit_age).get("fruiting_factor",0)>0:
            stages.append(("Fruiting",fruit_age))
        if "leaf_fall_end" in profile and sim.blueprint.growth.get("leaf_phenology") in {"deciduous", "drought_deciduous"}:
            dry_age = profile["cycle_days"] * (profile["leaf_fall_end"] + 1) / 2
            dry_age += max(0, math.ceil((sim.mature_age_days - dry_age) / profile["cycle_days"])) * profile["cycle_days"]
            stages.append(("Leafless season", dry_age))
    elif sim.blueprint.growth.get("lateral_rosette_scapes_version"):
        # This rosette has no authored seasonal calendar. Find a real model
        # fruiting state instead of displaying a guessed age with no capsules.
        flower_age = stages[2][1]
        for offset in (20., 40., 60., 80., 100.):
            fruit_age = flower_age + offset
            if any(p[0] == "fruit" for p in sim.generate_snapshot(fruit_age, 2).placements):
                stages.append(("Fruiting", fruit_age))
                break
    if sim.blueprint.growth.get("persistent_calyx_version"):
        unripe_age = profile["cycle_days"] * (profile["fruit_start"]+.6*(profile["fruit_ripe"]-profile["fruit_start"]))
        unripe_age += max(0, math.ceil((sim.mature_age_days-unripe_age)/profile["cycle_days"]))*profile["cycle_days"]
        stages.insert(3,("Green fruits",unripe_age))
    if sim.blueprint.growth.get('columnar_version'):
        basal_clump = (sim.blueprint.growth.get('columnar_profile') or {}).get('axis_layout') == 'basal_clump'
        stages = [('Young stem' if basal_clump else 'Young column',sim.mature_age_days*.24),
                  ('Clump growth' if basal_clump else 'First arms',sim.mature_age_days*.60),
                  *[s for s in stages if s[0] in {'Flowering','Fruiting'}]]
    return stages


def configure_stage(sim, label, age):
    """Explicit qualitative moss wetting treatments, separate from model age."""
    if sim.blueprint.growth.get('moss_turf_version'):
        sim.environment['moss_hydration'] = 0. if label == 'Dry mat' else 1.
    sim.set_age(age)


def canopy_envelope(sim, snapshots, aquatic=False):
    """Fit only organs drawn in the canopy views; roots belong in the side view."""
    envelopes = []
    for snapshot in snapshots:
        if sim.blueprint.growth.get('seasonal_rhizome_version') or sim.blueprint.growth.get('creeping_upright_version') or sim.blueprint.growth.get('terminal_rosette_version') or sim.blueprint.growth.get('paniculate_rosette_version') or sim.blueprint.growth.get('tufted_sedge_version') or sim.blueprint.growth.get('cyme_herb_version') or sim.blueprint.growth.get('cushion_version'):
            # Centimetre blades on long petioles need their own metric
            # envelope. The generic crown margin dwarfs a small basal herb.
            points=[]
            for i,p in enumerate(snapshot.placements):
                if p[0] in {'root','root_section','root_support','renewal_organ','renewal_bud'}:
                    continue
                points.append(p[2:5])
                points.extend(snapshot.placement_paths.get(str(i),[]))
                if p[0] in {'leaf','flower','fruit','strobilus'}:
                    module=sim.blueprint.module(p[0]);extent=module.length_m*p[6]
                    if p[0]=='leaf' and snapshot.placement_paths.get(str(i)):
                        continue  # Connected blade paths already include their actual tips.
                    direction=snapshot.placement_orientations.get(str(i),{}).get('forward',[0,0,1])
                    tip=[p[2+a]+direction[a]*extent for a in range(3)]
                    radius=module.radius_m*p[6] if p[0]=='leaf' else extent*.5
                    points.extend((tip[0]+dx*radius,tip[1]+dy*radius,tip[2])
                                  for dx in (-1,1) for dy in (-1,1))
            if not points:
                points=[(0.,0.,0.)]
            envelopes.append(SimpleNamespace(bounds_m=[min(p[a] for p in points) if side==0 else max(p[a] for p in points)
                for a in range(3) for side in (0,1)]))
            continue
        footprint = top_down_diagnostic_bounds(sim, snapshot)
        z = [p[4] for p in snapshot.placements
             if p[0] not in {"root","root_section","root_support","renewal_organ","renewal_bud"}]
        envelopes.append(SimpleNamespace(bounds_m=[*footprint, 0., max(z+[snapshot.bounds_m[5],.05])]))
    return fitted_bounds(envelopes, aquatic)


def render(species_id, output_dir):
    pygame.init(); pygame.display.set_mode((1, 1))
    world = WorldModel()
    sim = SpeciesSimulation(world_model=world, species_id=species_id, seed=303)
    if sim.blueprint.growth.get('growth_form') == 'lichen' and sim.blueprint.growth.get('surface_growth_profile'):
        render_surface_views(sim, output_dir)
        pygame.quit()
        return
    if sim.blueprint.growth.get('moss_turf_version'):
        render_moss_views(sim, output_dir)
        pygame.quit()
        return
    if sim.blueprint.growth.get('branched_vine_version'):
        render_vine_views(sim, output_dir)
        pygame.quit()
        return
    if sim.blueprint.growth.get("fungal_grammar_version"):
        render_fungal_views(sim, output_dir)
        pygame.quit()
        return
    floating = bool(sim.blueprint.growth.get("aquatic_rosette_version"))
    emergent = bool(sim.blueprint.growth.get("emergent_rosette_version"))
    aquatic = floating or emergent
    sim.set_lod(2)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sheet = pygame.Surface((1540, 1030)); sheet.fill((13, 20, 17))
    title = pygame.font.SysFont("consolas", 24)
    font = pygame.font.SysFont("consolas", 17)
    small = pygame.font.SysFont("consolas", 15)
    sheet.blit(title.render(sim.blueprint.display_name, True, (228, 236, 216)), (20, 16))
    description = ("Planar peripheral foliage sprays | compact axial shoots | evergreen crown" if sim.blueprint.growth.get('planar_spray_version') else
                   "Arched supporting limbs | fine pendant branchlets | physical leaf size" if sim.blueprint.growth.get('pendant_branchlet_version') else
                   "Renewing canes | young basal shoots, older branches and lateral flower clusters" if sim.blueprint.growth.get('renewing_cane_version') else
                   "Persistent rhizomes | seasonal shoots disappear and return" if sim.blueprint.growth.get('seasonal_rhizome_version') else
                   "Surface stems | distinct upright microphyll shoots and spore cones" if sim.blueprint.growth.get('creeping_upright_version') else
                   "Terminal rosettes | persistent axes, retained skirts, elevated panicles" if sim.blueprint.growth.get("terminal_rosette_version") else
                   "Emergent blades | separate petioles and reproductive stalks" if emergent else
                   "Ribbed photosynthetic stems | basal offshoot clump" if (sim.blueprint.growth.get('columnar_profile') or {}).get('axis_layout') == 'basal_clump' else
                   "Ribbed photosynthetic columns | delayed ascending arms" if sim.blueprint.growth.get('columnar_version') else
                   "Floating pixel blades | actual surface sockets" if floating else
                   "Rounded tubular flower heads | separate petioles" if sim.blueprint.growth.get('umbellate_head_version') else
                   "Layered conical crown | individual needle cohorts | seed cones" if sim.blueprint.growth.get('branching_subpattern')=='tiered_conifer' else
                   "Woody cushion | compound leaves, persistent rachises and pea flowers" if sim.blueprint.growth.get('cushion_version') else
                   "Saved traits and module artwork | ground plant")
    sheet.blit(font.render(f"{description} | renderer preview | seed 303", True, (168, 190, 163)), (20, 51))
    stages = stage_ages(sim)
    snapshots = [sim.generate_snapshot(age, 2) for _,age in stages]
    anatomy_bounds = fitted_bounds(snapshots, floating)
    bounds = canopy_envelope(sim, snapshots, floating)
    side_bounds = diagnostic_cell_bounds(SimpleNamespace(bounds_m=anatomy_bounds))
    records = []

    def panel(size, age, view):
        sim.set_age(age)
        canvas = pygame.Surface(size); canvas.fill((17, 27, 25))
        if view == "side":
            camera = (SurfaceElevationCamera(*size, anatomy_bounds)
                      if sim.blueprint.growth.get('columnar_version') else DiagnosticCamera(*size, side_bounds))
            visible = None
            a, b = camera.world_to_screen((side_bounds[0], 0)), camera.world_to_screen((side_bounds[1], 0))
            pygame.draw.line(canvas, (63,111,124) if aquatic else (104,96,70), a, b, 2)
        else:
            camera = (TopDownDiagnosticCamera(*size, bounds[:4]) if view == "top" else
                      IsometricDiagnosticCamera(*size, bounds))
            corners = [camera.world_to_screen_3d((x,y,0)) for x,y in
                       ((bounds[0],bounds[2]),(bounds[1],bounds[2]),(bounds[1],bounds[3]),(bounds[0],bounds[3]))]
            dormant_cutaway = (sim.blueprint.growth.get('seasonal_rhizome_version')
                               and sim.life_state(age).get('leaf_factor', 1.) == 0)
            if not dormant_cutaway:
                pygame.draw.polygon(canvas, (24,48,51) if aquatic else (39,43,31), corners)
            pygame.draw.polygon(canvas, (46,79,78) if aquatic else (71,81,55), corners, 1)
            if floating:
                visible = {i for i,p in enumerate(sim.render_snapshot.placements) if p[0] in {"leaf","flower"}}
            else:
                visible = canopy_visible_indices(sim,sim.render_snapshot)
            if dormant_cutaway:
                visible = {i for i,p in enumerate(sim.render_snapshot.placements)
                           if p[0] == 'renewal_bud' or sim.render_snapshot.placement_orientations[str(i)].get('seasonal_axis_role') == 'rhizome'}
        renderer._draw_individual(canvas, sim, camera=camera, clear=False, cache=False,
            visible_indices=visible, draw_ground_line=False, draw_environment=False,
            skeleton=(view=='side' and bool(sim.blueprint.growth.get('pendant_branchlet_version') or sim.blueprint.growth.get('planar_spray_version'))))
        return canvas

    flowering_age = (next(age for label,age in stages if label == "Fruiting")
                     if sim.blueprint.growth.get("persistent_calyx_version") else
                     next(age for label,age in stages if label == 'Flowering')
                     if sim.blueprint.growth.get('seasonal_rhizome_version') or sim.blueprint.growth.get('renewing_cane_version') else stages[2][1])
    sheet.blit(font.render("ISOMETRIC | mature fruiting shrub" if sim.blueprint.growth.get("persistent_calyx_version") else "ISOMETRIC | emergent clump" if emergent else "ISOMETRIC | floating canopy" if floating else "ISOMETRIC | above-ground plant", True, (221, 222, 193)), (20, 88))
    sheet.blit(panel((890, 500), flowering_age, "iso"), (10, 116))
    sheet.blit(font.render("TOP | water surface" if aquatic else "TOP | crown footprint", True, (221, 222, 193)), (935, 88))
    sheet.blit(panel((590, 305), flowering_age, "top"), (935, 116))
    root_status = sim.render_snapshot.stats.get("root_model_status")
    side_label = ("SKELETON | foliage hidden to expose branch structure" if sim.blueprint.growth.get('pendant_branchlet_version') or sim.blueprint.growth.get('planar_spray_version') else
                  "SIDE CUTAWAY | blades, stalks and roots" if emergent else "SIDE CUTAWAY | leaf rims and stalks" if floating else
                  "SIDE CUTAWAY | rhizomes, buds and roots; depth is provisional" if sim.blueprint.growth.get('seasonal_rhizome_version') else
                  "SIDE | roots at stem contacts; depth is a runtime proxy" if sim.blueprint.growth.get('creeping_upright_version') else
                  "SIDE | crown and stems; roots unresolved" if root_status=="unresolved" else "SIDE | crown and roots")
    sheet.blit(font.render(side_label, True, (221, 222, 193)), (935, 433))
    sheet.blit(panel((590, 175), flowering_age, "side"), (935, 465))
    context = (f"Water z=0; crown at {-100*sim.blueprint.growth['emergent_rosette_profile']['sediment_depth_m']:.0f} cm. One clump; root depth is a runtime proxy." if emergent else
               "Water z=0; sediment crown at -22 cm is a scene calibration." if floating else
               "Shared canopy envelope across stages; side view independently fits the roots. Ground z=0.")
    sheet.blit(small.render(context, True, (168, 190, 163)), (20, 626))
    step = 1520 // len(stages)
    for index, (label, age) in enumerate(stages):
        x = 10 + index * step
        stage_title = f"{label} | model day {age:.0f}"
        if sim.blueprint.growth.get('seasonal_rhizome_version') or sim.blueprint.growth.get('renewing_cane_version'):
            short_label = 'Dormant cutaway' if label == 'Summer dormancy | cutaway' else label
            if short_label == 'Winter framework':
                short_label = 'Winter canes'
            stage_title = f"{short_label} | day {age:.0f}"
        sheet.blit(font.render(stage_title, True, (221, 222, 193)), (x+10, 673))
        sheet.blit(panel((step-10, 270), age, "iso"), (x, 701))
        snap = sim.render_snapshot
        flowers = sum(p[0] == "flower" for p in snap.placements)
        fruits = sum(p[0] == "fruit" for p in snap.placements)
        basal_clump = (sim.blueprint.growth.get('columnar_profile') or {}).get('axis_layout') == 'basal_clump'
        counts=(f"Stems {snap.stats['columnar_axis_count']} | F {flowers} | R {fruits}"
                if basal_clump else
                f"Arms {snap.stats['columnar_arm_count']} | F {flowers} | R {fruits}"
                if sim.blueprint.growth.get('columnar_version') else
                f"Leaves {snap.stats['estimated_leaf_count']} | F {flowers} | R {fruits}")
        if sim.blueprint.growth.get('creeping_upright_version'):
            counts = f"Leaves {snap.stats['estimated_leaf_count']} | Uprights {snap.stats['upright_shoot_count']} | Spore cones {snap.stats['strobilus_count']}"
        if sim.blueprint.growth.get('seasonal_rhizome_version'):
            counts = f"Shoots {snap.stats['seasonal_shoot_count']} | F {snap.stats['seasonal_flower_count']} | Heads {snap.stats['seasonal_fruit_head_count']}"
        if sim.blueprint.growth.get('reproductive_structure')=='cone':
            counts=f"Young cones {flowers} | mature cones {fruits}"
        if sim.blueprint.growth.get('renewing_cane_version'):
            counts = f"Canes {snap.stats['shrub_cane_count']} | Young {snap.stats['young_cane_count']} | F {snap.stats['shrub_flower_count']} | H {snap.stats['shrub_fruit_count']}"
        if sim.blueprint.growth.get('planar_spray_version'):
            counts=f"Spray groups {snap.stats.get('planar_spray_count',0)} | Root suckers {snap.stats.get('tree_sucker_count',0)}"
        if sim.blueprint.growth.get('mixed_tiller_version'):
            counts=f"Tillers {snap.stats['tiller_count']} | Tall culms {snap.stats['reproductive_tiller_count']} | Spikes {snap.stats['spike_count']}"
        sheet.blit(small.render(counts, True, (168,190,163)), (x+10, 979))
        records.append({"label":label,"snapshot":snap.to_dict(),"ecology":sim.get_ecological_outcome()})
    footer = ("Model days. F = display flower heads, R = fruit groups; no seed-yield prediction. Fruit silhouettes provisional; roots unresolved."
              if sim.blueprint.growth.get('umbellate_head_version') else
              "Developmental model days. F/R count spikelets in flower/fruit, not individual florets or nutlets. Independently fitted views."
              if sim.blueprint.growth.get('tufted_sedge_version') else
              "Developmental model days; saved morphology and sprites. F = flowers, R = fruit. Independently fitted views are labelled above.")
    if sim.blueprint.growth.get("persistent_calyx_version"):
        footer="Model days. F = flowers; R = calyx groups. Root depth is an unmeasured runtime proxy. Views enlarged independently."
    if sim.blueprint.growth.get('columnar_version'):
        footer=('Model days, not real days. Offshoot timing and root envelope are provisional; F/R are display organs. No expanded leaves.'
                if (sim.blueprint.growth.get('columnar_profile') or {}).get('axis_layout') == 'basal_clump' else
                'Model days, not real days. Age/arm curves and root envelope are provisional; F/R are display organs. No expanded leaves.')
    if sim.blueprint.growth.get('cyme_herb_version'):
        footer='Model days. F = cyathia; R = capsules. Green bracts are separate leaves. Independently fitted views.'
    if sim.blueprint.growth.get('mixed_tiller_version'):
        footer='Model days. Spikes are whole multi-floret inflorescences, not individual flowers. Tiller mixture and onset are provisional.'
    if sim.blueprint.growth.get('creeping_upright_version'):
        footer='Model clock, not calendar age. Strobili bear spores; no flowers, fruit or seed cones. Root depth and gametophyte stage unresolved.'
    if sim.blueprint.growth.get('seasonal_rhizome_version'):
        footer='Qualitative January-origin model year. Dormancy panel exposes persistent rhizomes/buds; fruit heads are aggregate displays, not seed yield.'
    if sim.blueprint.growth.get('renewing_cane_version'):
        footer='Model days, not cane years. Young canes replace retired canes; crown persists. F = individual flowers; H = hips. Root architecture unresolved.'
    if sim.blueprint.growth.get('pendant_branchlet_version'):
        footer='Model days. Fine-shoot groups use normal-sized leaves. F = catkin displays. Fruit morphology/seasonal timing unresolved; roots are runtime proxies.'
    if sim.blueprint.growth.get('planar_spray_version'):
        footer='Model days. Sprays represent bounded groups of normal-sized shoots/needles. Cone morphology and shoot turnover unresolved; roots are runtime proxies.'
    if sim.blueprint.growth.get('basal_subshrub_version'):
        footer='Model days. F/R = display clusters of yellow/pappus heads, not seed yield. Root depth is a runtime proxy. Views fitted independently.'
    if sim.blueprint.growth.get('basal_herb_version'):
        footer='Model days. F/R = flower/retained fruiting heads, not individual flowers or seeds. One leaf includes its leaflets. Root depth is a proxy.'
    if sim.blueprint.growth.get('reproductive_structure')=='cone':
        footer='Illustrative model time. Young and mature seed cones are distinct from flowers/fruits. Root status is labelled above.'
    sheet.blit(small.render(footer,True,(168,190,163)),(20,1006))
    if sim.blueprint.growth.get('scape_rosette_version') or sim.blueprint.growth.get('pendant_branchlet_version') or sim.blueprint.growth.get('planar_spray_version'):
        # The two actual BioSim reduction paths need inspection at their
        # ordinary map sizes, not merely in the large SpeciesSim camera.
        from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
        from simulations.biosphere.plant_pictures import top_view, map_sprite_at
        sim.set_age(flowering_age)
        scene = SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),
                                world_units_to_meters=1.,
                                get_representative_species_simulation=lambda _rid: sim)
        instance = {'species_id': species_id, 'representative_id': 'design_preview',
                    'abundance': 1., 'visual_scale': 1., 'variant': 0}
        bio = BiosphereBuilderRenderer(SimpleNamespace(), species_renderer=renderer)
        billboard, anchor = bio._render_sprite_surface(
            scene, instance, SimpleNamespace(zoom=400., sprite_height_cap=84))
        map_picture = top_view(sim)
        map_small = map_sprite_at(map_picture, 40) if map_picture else None
        inset = pygame.Rect(675, 445, 205, 155)
        pygame.draw.rect(sheet, (15, 28, 25), inset)
        pygame.draw.rect(sheet, (67, 87, 70), inset, 1)
        sheet.blit(small.render('BIOSIM | 84 px / 40 px', True, (190, 210, 176)), (684, 450))
        sheet.blit(billboard, (706 - billboard.get_width() // 2, 566 - billboard.get_height()))
        if map_small:
            sheet.blit(map_small, (799 - map_small.get_width() // 2,
                                   536 - map_small.get_height() // 2))
        sheet.blit(small.render('grounded', True, (155, 179, 154)), (684, 575))
        sheet.blit(small.render('map', True, (155, 179, 154)), (781, 575))
    output_dir.mkdir(parents=True,exist_ok=True)
    pygame.image.save(sheet,output_dir/"after.png")
    (output_dir/"after.json").write_text(json.dumps({"species_id":species_id,"seed":303,
        "blueprint":sim.blueprint.to_dict(),"bounds_m":bounds,"stages":records,
        "aquatic_context":aquatic,"side_bounds_m":side_bounds,"anatomy_bounds_m":anatomy_bounds,
        "source":"live resolved species; production renderer"},indent=2),encoding="utf-8")
    if sim.blueprint.growth.get('rhizome_raceme_version'):
        render_rhizome_raceme_detail(sim, renderer, output_dir)
    if sim.blueprint.growth.get('branching_subpattern')=='tiered_conifer' and sim.blueprint.growth.get('reproductive_profile'):
        render_conifer_detail(sim,renderer,output_dir)
    if sim.blueprint.growth.get("persistent_calyx_version"):
        render_spur_detail(sim, renderer, output_dir, stages)
    if sim.blueprint.growth.get('columnar_version'):
        render_columnar_detail(sim, renderer, output_dir, stages)
    if sim.blueprint.growth.get('cushion_version'):
        render_cushion_detail(sim, renderer, output_dir)
    pygame.quit()



def render_cushion_detail(sim, renderer, output_dir):
    """Metric cushion and persistent winter axes, with landscape reductions."""
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view, map_sprite_at
    ages = dict(stage_ages(sim)); sim.set_age(ages['Flowering'])
    living = sim.render_snapshot
    winter = sim.generate_snapshot(ages['Leafless season'], 2)
    bounds = canopy_envelope(sim, [living, winter])
    sheet = pygame.Surface((1540, 1080)); sheet.fill((13, 20, 17))
    font = pygame.font.SysFont('consolas', 18)
    def label(s, x, y): sheet.blit(font.render(s, True, (224, 233, 214)), (x, y))
    label('Woody cushion | production renderer | seed 303 | same scale in both upper panels', 20, 18)
    for x, snap, title in ((10, living, 'Living leaflets and flowers'), (780, winter, 'Leafless: woody axes and leaf rachises remain')):
        label(title, x+12, 55)
        panel = pygame.Surface((750, 420)); panel.fill((17, 27, 25))
        camera = SurfaceElevationCamera(750, 420, bounds)
        renderer._draw_individual(panel, sim, snapshot=snap, camera=camera,
            visible_indices=canopy_visible_indices(sim, snap), clear=False, cache=False,
            draw_environment=False, draw_ground_line=False)
        pygame.draw.line(panel, (221, 203, 135), (25, 389), (25+round(.05*camera.scale), 389), 3)
        panel.blit(font.render('5 cm', True, (221, 203, 135)), (25, 358))
        sheet.blit(panel, (x, 85))
    label('Organ artwork | separate enlargements; sizes refer to biological organs', 20, 530)
    for role, x in (('leaf', 90), ('flower', 350), ('fruit', 610)):
        size = sim.blueprint.module(role).length_m * 1000
        source = renderer._module_asset(sim, role)
        if source is not None:
            art = source.subsurface(source.get_bounding_rect())
            width = round(180*art.get_width()/max(1, art.get_height()))
            sheet.blit(pygame.transform.scale(art, (width, 180)), (x, 575))
        label(f'{role} | {size:g} mm', x-25, 780)
    label('BioSim | native pixel sizes', 895, 530)
    scene = SimpleNamespace(world_model=SimpleNamespace(repository_revision=0), world_units_to_meters=1.,
                            get_representative_species_simulation=lambda _: sim)
    item = {'species_id':sim.species_id, 'representative_id':'inspection', 'abundance':1., 'visual_scale':1., 'variant':0}
    bio = BiosphereBuilderRenderer(SimpleNamespace(), species_renderer=renderer)
    for cap, x in ((220, 1050), (84, 1370)):
        art, _ = bio._render_sprite_surface(scene, item, SimpleNamespace(zoom=400., sprite_height_cap=cap))
        sheet.blit(art, (x-art.get_width()//2, 800-art.get_height()))
        label(f'{cap} px cap', x-60, 825)
    picture = top_view(sim)
    if picture is not None: sheet.blit(map_sprite_at(picture, 40), (1140, 890))
    label('40 px map', 1090, 945)
    label('Rachises are persistent support, not green leaf area. Counts and seasonal timing are qualitative.', 20, 1000)
    label('Root architecture: taproot; maximum depth unmeasured. Root envelope remains a runtime estimate.', 20, 1034)
    pygame.image.save(sheet, output_dir/'detail.png')


def render_conifer_detail(sim,renderer,output_dir):
    """A reproductive shoot at metric scale and actual landscape reductions."""
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view,map_sprite_at
    ages=stage_ages(sim);age=next(t for name,t in ages if name=='Mature cones')
    sim.set_age(age);snap=sim.render_snapshot
    fruits=[(i,x) for i,x in enumerate(snap.placements) if x[0]=='fruit']
    if not fruits:return
    index,fruit=max(fruits,key=lambda item:math.hypot(*item[1][2:4]))
    point=fruit[2:5];visible={index,fruit[1]};near=[]
    for c in snap.leaf_clusters:
        host=c.get('host_placement_index',-1)
        if host>=0:
            p=snap.placements[host][2:5]
            if math.dist(p,point)<.35:visible.add(host);near.append(p)
    points=[point,*near];bounds=[fn(p[a] for p in points)+(-.14 if fn is min else .14) for a in range(3) for fn in (min,max)]
    sheet=pygame.Surface((1280,790));sheet.fill((13,20,17));font=pygame.font.SysFont('consolas',18)
    def text(s,x,y):sheet.blit(font.render(s,True,(222,232,211)),(x,y))
    text('Conifer organ detail | actual metre dimensions | whole shoots are collective needle artwork',20,16)
    canvas=pygame.Surface((820,590));canvas.fill((17,27,25));camera=SurfaceElevationCamera(820,590,bounds)
    renderer._draw_individual(canvas,sim,camera=camera,visible_indices=visible,cache=False,clear=False,draw_environment=False,draw_ground_line=False)
    pygame.draw.line(canvas,(221,203,135),(25,555),(25+round(.1*camera.scale),555),3)
    canvas.blit(font.render('10 cm',True,(221,203,135)),(25,525));sheet.blit(canvas,(10,65))
    text('Hanging mature seed cone',25,48)
    # The collective needle unit is usually subpixel on the whole tree.
    # Show its editable art separately, explicitly labelled rather than
    # enlarging botanical needles inside the production scene.
    source=renderer._module_asset(sim,'leaf')
    if source is not None:
        box=source.get_bounding_rect()
        if box.width and box.height:
            art=source.subsurface(box);height=220
            width=max(1,round(height*box.width/box.height))
            sheet.blit(pygame.transform.scale(art,(width,height)),(630-width//2,130))
            text('Shoot artwork',520,390)
            text('separate enlargement',520,420)
    scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,get_representative_species_simulation=lambda _:sim)
    item={'species_id':sim.species_id,'representative_id':'inspection','abundance':1.,'visual_scale':1.,'variant':0}
    bio=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)
    text('BIOSIM | native reduction',850,90)
    for cap,x in ((220,940),(84,1130)):
        art,_=bio._render_sprite_surface(scene,item,SimpleNamespace(zoom=400.,sprite_height_cap=cap))
        sheet.blit(art,(x-art.get_width()//2,410-art.get_height()));text(f'{cap} px cap',x-55,430)
    picture=top_view(sim)
    if picture is not None:sheet.blit(map_sprite_at(picture,40),(1020,515))
    text('40 px map',970,580)
    text(f"Collective shoot art; biological needle length {sim.blueprint.module('leaf').length_m*1000:g} mm representative.",20,700)
    text('Seed-cone stages and abundance are qualitative. Pollen cones and dehiscence remain unmodelled.',20,740)
    pygame.image.save(sheet,output_dir/'detail.png')


def render_rhizome_raceme_detail(sim, renderer, output_dir):
    """One terminal raceme at shared physical scale, plus production BioSim art."""
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view, map_sprite_at
    p = sim.blueprint.growth['reproductive_profile']; cycle=p['cycle_days']
    ages=[cycle*(p['flowering_start']+.04),cycle*(p['flowering_start']+.63*(p['flowering_end']-p['flowering_start']))]
    snapshots=[sim.generate_snapshot(age,2) for age in ages]
    selected=[]; points=[]
    for snap in snapshots:
        base=next(x[2:5] for x in snap.placements if x[0]=='branch_section')
        indices={i for i,x in enumerate(snap.placements) if x[0] in {'stem_section','flower','fruit'}
                 and math.hypot(x[2]-base[0],x[3]-base[1])<.10
                 and (x[0] in {'flower','fruit'} or snap.placement_orientations.get(str(i),{}).get('axis_role') in {'raceme_axis','pedicel'})}
        selected.append(indices)
        for i in indices:
            x=snap.placements[i];points.append(x[2:5]);points.extend(snap.placement_paths.get(str(i),[]))
            if x[0] in {'flower','fruit'}: points.append((x[2]+.04,x[3]+.04,x[4]+.08))
    bounds=[fn(x[a] for x in points)+(-.04 if fn is min else .04) for a in range(3) for fn in (min,max)]
    sheet=pygame.Surface((1280,770));sheet.fill((13,20,17))
    font=pygame.font.SysFont('consolas',18);small=pygame.font.SysFont('consolas',15)
    def text(value,x,y):sheet.blit(font.render(value,True,(222,232,211)),(x,y))
    text('Fireweed | terminal raceme detail | shared scale | seed 303 | LOD 2',20,15)
    for i,(age,snap,indices) in enumerate(zip(ages,snapshots,selected)):
        sim.set_age(age);canvas=pygame.Surface((620,555));canvas.fill((17,27,25))
        camera=SurfaceElevationCamera(620,555,bounds)
        renderer._draw_individual(canvas,sim,camera=camera,snapshot=snap,visible_indices=indices,
                                  clear=False,cache=False,draw_environment=False,draw_ground_line=False)
        pygame.draw.line(canvas,(218,201,132),(20,530),(20+round(.1*camera.scale),530),3)
        canvas.blit(small.render('10 cm',True,(218,201,132)),(20,505))
        text('Lower flowers' if i==0 else 'Upper flowers; capsules below',20+i*640,52)
        sheet.blit(canvas,(10+i*640,80))
    sim.set_age(ages[1])
    scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,get_representative_species_simulation=lambda _:sim)
    item={'species_id':sim.species_id,'representative_id':'inspection','abundance':1.,'visual_scale':1.,'variant':0}
    art,_=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)._render_sprite_surface(scene,item,SimpleNamespace(zoom=400.,sprite_height_cap=84))
    text('BIOSIM | actual 84 px sprite and 40 px map',20,650)
    sheet.blit(art,(510,650))
    picture=top_view(sim)
    if picture is not None:sheet.blit(map_sprite_at(picture,40),(1010,675))
    text('Closed capsules are represented; opening valves and silky seed plumes remain unmodelled.',20,740)
    pygame.image.save(sheet,output_dir/'detail.png')


def render_moss_views(sim, output_dir):
    """Production leafy-moss geometry with shared metric views and wet/dry poses."""
    sim.set_lod(2)
    stages = stage_ages(sim)
    snapshots = []
    for label, age in stages:
        configure_stage(sim, label, age)
        snapshots.append(sim.render_snapshot)
    bounds = fitted_bounds(snapshots, min_margin=.003)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sheet = pygame.Surface((1540, 1060)); sheet.fill((13, 20, 17))
    title = pygame.font.SysFont('consolas', 24)
    font = pygame.font.SysFont('consolas', 17)
    small = pygame.font.SysFont('consolas', 15)
    def text(value, x, y, big=False):
        sheet.blit((title if big else font).render(value, True, (218,230,204)), (x,y))
    text(sim.blueprint.display_name, 20, 16, True)
    text('Saved leafy-moss turf | production renderer preview | seed 303 | metre geometry', 20, 51)
    def panel(size, label, age, view):
        configure_stage(sim, label, age)
        canvas = pygame.Surface(size); canvas.fill((17,27,25))
        camera = (TopDownDiagnosticCamera(*size,bounds[:4]) if view == 'top' else
                  SurfaceElevationCamera(*size,bounds) if view == 'side' else
                  IsometricDiagnosticCamera(*size,bounds))
        renderer._draw_individual(canvas,sim,camera=camera,clear=False,cache=False,
            draw_ground_line=False,draw_environment=False)
        return canvas
    adult = stages[2][1]
    text('ISOMETRIC | irregular vegetative turf',20,88)
    sheet.blit(panel((900,480),'Wet mat',adult,'iso'),(10,115))
    diameter=sim.blueprint.growth['moss_turf_profile']['patch_diameter_m']*100
    text(f'TOP | representative {diameter:g} cm patch',935,88)
    sheet.blit(panel((590,275),'Wet mat',adult,'top'),(935,115))
    text('SIDE | leafy axes; rhizoids unresolved',935,405)
    sheet.blit(panel((590,180),'Wet mat',adult,'side'),(935,435))
    text('No vascular roots, flowers, fruits or seeds. Rare spore capsules are not yet represented.',20,630)
    records=[]
    for index,(label,age) in enumerate(stages):
        x=10+index*304
        text(f'{label} | model day {age:.0f}',x+8,676)
        sheet.blit(panel((294,260),label,age,'iso'),(x,705))
        snap=sim.render_snapshot
        sheet.blit(small.render(f"Shoots {snap.stats['moss_shoot_count']} | leaves {snap.stats['estimated_leaf_count']}",True,(169,189,161)),(x+8,974))
        records.append({'label':label,'snapshot':snap.to_dict(),'ecology':sim.get_ecological_outcome()})
    text('Wet/dry/rewet share age and axes. Wetting is qualitative; model days are not measured recovery times.',20,1019)
    output_dir.mkdir(parents=True,exist_ok=True)
    pygame.image.save(sheet,output_dir/'after.png')
    (output_dir/'after.json').write_text(json.dumps({'species_id':sim.species_id,'seed':303,'lod':2,
        'source':'Production SpeciesRenderer; saved quadstore traits and assets',
        'blueprint_fingerprint':sim.blueprint.fingerprint(),'bounds_m':bounds,'stages':records},indent=2),encoding='utf-8')


def render_surface_views(sim, output_dir):
    """Shared surface-lichen sheet; the neutral substrate is display context."""
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer

    sim.set_lod(2)
    adult = sim.mature_age_days
    stages = [('Young thallus', adult*.25), ('Expanding', adult*.60),
              ('Mature', adult), ('Dry dormant', adult)]
    snapshots = []
    for label, age in stages:
        sim.environment['thallus_hydration'] = 0. if label == 'Dry dormant' else .45
        sim.set_age(age)
        snapshots.append(sim.render_snapshot)
    bounds = fitted_bounds(snapshots, min_margin=.004)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sheet = pygame.Surface((1540, 1030)); sheet.fill((13, 20, 17))
    title = pygame.font.SysFont('consolas', 24)
    font = pygame.font.SysFont('consolas', 17)
    small = pygame.font.SysFont('consolas', 15)
    def label(value, x, y, heading=False):
        sheet.blit((title if heading else font).render(value, True, (218,230,204)), (x,y))
    def panel(size, stage, view):
        name, age = stage
        sim.environment['thallus_hydration'] = 0. if name == 'Dry dormant' else .45
        sim.set_age(age)
        canvas = pygame.Surface(size); canvas.fill((17,27,25))
        camera = (TopDownDiagnosticCamera(*size,bounds[:4]) if view == 'top' else
                  SurfaceElevationCamera(*size,bounds) if view == 'side' else
                  IsometricDiagnosticCamera(*size,bounds))
        if view == 'top':
            camera.scale = min((size[0]-48)/max(.001,bounds[1]-bounds[0]),
                               (size[1]-48)/max(.001,bounds[3]-bounds[2]))
        elif view == 'side':
            camera.scale = min((size[0]-48)/max(.001,camera.max_u-camera.min_u),
                               (size[1]-48)/max(.001,bounds[5]-bounds[4]))
            camera.offset_x = size[0]*.5-(camera.min_u+camera.max_u)*.5*camera.scale
            camera.bottom = size[1]*.5+(bounds[4]+bounds[5])*.5*camera.scale
        else:
            corners=[(x-y,(x+y)*.5-z) for x in bounds[:2] for y in bounds[2:4] for z in bounds[4:]]
            xs=[p[0] for p in corners];ys=[p[1] for p in corners]
            camera.scale=min((size[0]-48)/max(.001,max(xs)-min(xs)),
                             (size[1]-48)/max(.001,max(ys)-min(ys)))
            camera.offset_x=size[0]*.5-(min(xs)+max(xs))*.5*camera.scale
            camera.offset_y=size[1]*.5-(min(ys)+max(ys))*.5*camera.scale
        renderer._draw_individual(canvas,sim,camera=camera,clear=False,cache=False,
                                  draw_ground_line=False)
        return canvas
    mature = stages[2]
    label(sim.blueprint.display_name, 20, 16, True)
    label('Saved surface lichen | production renderer | seed 303 | neutral specimen substrate', 20, 51)
    label('ISOMETRIC | mature thallus and attachment footprint', 20, 89)
    sheet.blit(panel((900,480),mature,'iso'),(10,116))
    label('TOP | same thallus', 935, 89)
    sheet.blit(panel((590,265),mature,'top'),(935,116))
    label('SIDE | centimetre-scale relief', 935, 403)
    sheet.blit(panel((590,180),mature,'side'),(935,431))
    label('BioSim | population symbol, 45 pixels/metre', 935, 625)
    symbol=pygame.Surface((590,34));symbol.fill((40,43,37))
    instance={'species_id':sim.species_id,'growth_form':'lichen','x':0.,'y':0.,'display_maturity':1.}
    BiosphereBuilderRenderer._draw_groundcover(symbol,instance,(85,19),45,(205,211,195),
                                                sim.blueprint.growth['surface_growth_profile'])
    sheet.blit(symbol,(935,655))
    label('Fungal body: no vascular roots, leaves, flowers or fruit.', 20, 632)
    label('Fixed metric envelope across stages; model days do not establish calendar age.',20,659)
    records=[]
    for index,stage in enumerate(stages):
        x=10+index*383
        label(f'{stage[0]} | day {stage[1]:.0f}',x+8,694)
        sheet.blit(panel((373,250),stage,'iso'),(x,723))
        snap=sim.render_snapshot
        sheet.blit(small.render(f"Cover {snap.stats['surface_coverage_m2']*10000:.1f} cm2 | activity {snap.stats['surface_activity']:.2f}",
                                True,(169,189,161)),(x+8,983))
        records.append({'label':stage[0], 'age_days':stage[1], 'snapshot':snap.to_dict(),
                        'ecology':sim.get_ecological_outcome()})
    label('Drying pauses activity while the attached thallus remains; recovery timing is unresolved.',20,1007)
    output_dir.mkdir(parents=True,exist_ok=True)
    pygame.image.save(sheet,output_dir/'after.png')
    (output_dir/'after.json').write_text(json.dumps({'species_id':sim.species_id,'seed':303,'lod':2,
        'source':'Production SpeciesRenderer and BioSim population symbol; neutral specimen substrate',
        'blueprint_fingerprint':sim.blueprint.fingerprint(),'bounds_m':bounds,'stages':records},indent=2),encoding='utf-8')


def render_spur_detail(sim, renderer, output_dir, stages):
    """Inspect one connected woody twig through its real flower/fruit stages."""
    chosen = [(label,age) for label,age in stages if label in {"Flowering","Green fruits","Fruiting"}]
    snapshots = [sim.generate_snapshot(age,2) for _,age in chosen]
    ripe = snapshots[-1]
    # Resolve the twig from an actual fruit-bearing spur, not a world crop
    # that also includes every overlapping cane.
    def body_host(snapshot, organ):
        stalk = snapshot.placements[organ][1]
        spur = snapshot.placements[stalk][1]
        return snapshot.placements[spur][1]
    organ = next(i for i,p in enumerate(ripe.placements)
                 if p[0] == "fruit" and ripe.placements[body_host(ripe,i)][7] == 2)
    root = ripe.placements[ripe.placements[organ][1]][1]
    host = ripe.placements[root][1]
    while ripe.placements[host][7] > 2:
        host = ripe.placements[host][1]
    while ripe.placements[host][7] == 2 and ripe.placements[ripe.placements[host][1]][7] == 2:
        host = ripe.placements[host][1]
    socket = ripe.placements[host][2:5]
    selected_sets = []
    points = []
    for snap in snapshots:
        start = next(i for i,p in enumerate(snap.placements)
                     if p[0] == "branch_section" and p[7] == 2 and p[2:5] == socket)
        selected = {start}
        for i,p in enumerate(snap.placements):
            if p[1] in selected: selected.add(i)
        selected_sets.append(selected)
        for i in selected:
            p = snap.placements[i]
            points.append((p[2]+p[3]*1.8,p[4]))
            points.extend((q[0]+q[1]*1.8,q[2]) for q in snap.placement_paths.get(str(i),[]))
    focus = ripe.placements[body_host(ripe,organ)][2:5]
    focus_x = focus[0]+focus[1]*1.8
    bounds = (focus_x-.09,focus_x+.09,focus[2]-.09,focus[2]+.09)
    sheet = pygame.Surface((1540,565));sheet.fill((13,20,17))
    font = pygame.font.SysFont('consolas',20);small = pygame.font.SysFont('consolas',15)
    sheet.blit(font.render('Same connected short shoot | yellow flower, red calyx, green-to-black drupes',True,(225,233,214)),(20,15))
    records=[]
    for col,((label,age),snap,selected) in enumerate(zip(chosen,snapshots,selected_sets)):
        sim.set_age(age)
        canvas=pygame.Surface((500,420));canvas.fill((17,27,25))
        camera=DiagnosticCamera(500,420,bounds)
        camera.bottom = 210+(bounds[3]-bounds[2])*camera.scale*.5
        renderer._draw_individual(canvas,sim,snapshot=snap,camera=camera,visible_indices=selected,
                                  clear=False,cache=False,draw_ground_line=False,draw_environment=False)
        bar=round(camera.scale*.01)
        pygame.draw.line(canvas,(220,230,211),(20,390),(20+bar,390),2)
        canvas.blit(small.render('10 mm',True,(220,230,211)),(20,365))
        sheet.blit(font.render(label,True,(225,233,214)),(20+510*col,55))
        sheet.blit(canvas,(10+510*col,90))
        records.append({'label':label,'age_days':age,'selected_indices':sorted(selected),
                        'flower_count':sum(snap.placements[i][0]=='flower' for i in selected),
                        'fruit_group_count':sum(snap.placements[i][0]=='fruit' for i in selected),
                        'life_state':sim.life_state()})
    sheet.blit(small.render('One flower / one calyx group at each fertile spur. Fruitlets about 7.5 mm; calyx about 28 mm. Display counts are representative.',True,(169,190,163)),(20,533))
    pygame.image.save(sheet,output_dir/'detail.png')
    (output_dir/'detail.json').write_text(json.dumps({'socket_m':socket,'bounds_m':bounds,'seed':sim.seed,'lod':2,
        'stages':records,'source':'production renderer; one twig; independent shared metric camera'},indent=2),encoding='utf-8')

def render_columnar_detail(sim, renderer, output_dir, stages):
    """Matched physical close-ups: reproductive organs remain their real size."""
    sheet=pygame.Surface((1220,740));sheet.fill((13,20,17))
    font=pygame.font.SysFont('consolas',20);small=pygame.font.SysFont('consolas',16)
    sheet.blit(font.render('Column tip | enlarged at the same metric scale | production renderer',True,(228,236,216)),(20,15))
    height=sim.blueprint.growth['max_height_m']
    bounds=(-.68,.68,height-.85,height+.35)
    records=[]
    for i,(label,age) in enumerate(s for s in stages if s[0] in {'Flowering','Fruiting'}):
        sim.set_age(age)
        canvas=pygame.Surface((590,590));canvas.fill((17,27,25))
        camera=SurfaceElevationCamera(590,590,[bounds[0],bounds[1],-.7,.7,bounds[2],bounds[3]])
        renderer._draw_individual(canvas,sim,camera=camera,clear=False,cache=False,
                                  visible_indices=canopy_visible_indices(sim,sim.render_snapshot),
                                  draw_ground_line=False,draw_environment=False)
        x=10+i*610
        sheet.blit(font.render(label,True,(228,236,216)),(x+10,55))
        sheet.blit(canvas,(x,90))
        a=camera.world_to_screen((-.55,height-.65));b=camera.world_to_screen((-.35,height-.65))
        pygame.draw.line(sheet,(228,236,216),(x+a[0],90+a[1]),(x+b[0],90+b[1]),2)
        sheet.blit(small.render('20 cm',True,(228,236,216)),(x+a[0],90+a[1]+6))
        records.append({'label':label,'snapshot':sim.render_snapshot.to_dict()})
    sheet.blit(small.render('8 cm flower / opened fruit; 5 cm spine-cluster display. Tube depth and unripe fruit shape remain simplified.',True,(168,190,163)),(20,705))
    pygame.image.save(sheet,output_dir/'detail.png')
    (output_dir/'detail.json').write_text(json.dumps({'bounds_m':bounds,'stages':records,
        'source':'saved resolved species; production renderer; matched metric close-ups'},indent=2),encoding='utf-8')


def render_vine_views(sim,output_dir):
    """Explicit diagnostic host plus honest unsupported and seasonal views."""
    environment={'climbing_supports':[{'id':'reference_tree','kind':'tree',
        'position_m':[.5,0,0],'height_m':4.,'radius_m':.06}]}
    supported=SpeciesSimulation(species_entity=sim.species_entity,seed=sim.seed,environment=environment)
    unsupported=SpeciesSimulation(species_entity=sim.species_entity,seed=sim.seed,environment={})
    profile=sim.blueprint.growth['reproductive_profile']
    ages=[profile['cycle_days']*(profile['flowering_start']+profile['fruit_start'])/2,
          profile['cycle_days']*profile['fruit_ripe'],
          profile['cycle_days']*(profile.get('leaf_fall_end',.9)+1)/2]
    snapshots=[supported.generate_snapshot(age,2) for age in ages]
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    font=pygame.font.SysFont('consolas',18);small=pygame.font.SysFont('consolas',15)
    sheet=pygame.Surface((1540,1030));sheet.fill((13,20,17))
    def label(s,x,y):sheet.blit(font.render(s,True,(225,233,214)),(x,y))
    def panel(model,age,size,camera,visible=None,draw_environment=True):
        model.set_lod(2);model.set_age(age)
        canvas=pygame.Surface(size);canvas.fill((17,27,25))
        renderer._draw_individual(canvas,model,camera=camera,visible_indices=visible,
            clear=False,cache=False,draw_ground_line=False,draw_environment=draw_environment)
        return canvas
    label(f'{sim.blueprint.display_name} | saved climbing-vine inspection',20,16)
    label('Seed 303 | LOD 2 | 4 m reference tree is an external diagnostic fixture; it is not part of the species.',20,47)
    label('SIDE | connected vine and lateral shoots',20,88)
    side_bounds=[-1.1,2.,-.15,4.35]
    sheet.blit(panel(supported,ages[0],(790,540),DiagnosticCamera(790,540,side_bounds)),(10,118))
    label('TOP | supported foliage footprint',820,88)
    sheet.blit(panel(supported,ages[0],(710,245),TopDownDiagnosticCamera(710,245,[-.8,1.8,-1.,1.])),(820,118))
    unsupported.set_age(ages[0]);ground=unsupported.render_snapshot
    ground_bounds=top_down_diagnostic_bounds(unsupported,ground)
    visible=canopy_visible_indices(unsupported,ground)
    label('TOP | no support: branched ground trail (independent scale)',820,389)
    sheet.blit(panel(unsupported,ages[0],(710,220),TopDownDiagnosticCamera(710,220,ground_bounds),visible), (820,423))
    stats=snapshots[0].stats
    label(f"{stats['vine_lateral_axis_count']} lateral shoots | {stats['estimated_leaf_count']} leaves | axis length {stats['vine_axis_length_m']:.2f} m",20,663)
    records=[]
    for col,(name,age) in enumerate(zip(['Flowering','Ripe capsules','Winter: retained fruit'],ages)):
        x=10+col*510;label(f'{name} | model day {age:.0f}',x+10,707)
        sheet.blit(panel(supported,age,(500,245),DiagnosticCamera(500,245,side_bounds)),(x,740))
        snap=supported.render_snapshot
        records.append({'label':name,'age_days':age,'snapshot':snap.to_dict(),'ecology':supported.get_ecological_outcome()})
    label('Bottom views share scale. Leaf loss is seasonal; sustained height requires supplied support.',20,1005)
    output_dir.mkdir(parents=True,exist_ok=True);pygame.image.save(sheet,output_dir/'after.png')
    (output_dir/'after.json').write_text(json.dumps({'species_id':sim.species_id,'seed':sim.seed,'lod':2,
        'blueprint':sim.blueprint.to_dict(),'blueprint_fingerprint':sim.blueprint.fingerprint(),
        'reference_environment':environment,'side_camera_bounds':side_bounds,'ground_top_camera_bounds':ground_bounds,
        'unsupported_snapshot':ground.to_dict(),'stages':records,
        'source':'saved traits; production renderer; explicit external reference tree'},indent=2),encoding='utf-8')
    # The same physical host coordinates are stable across seasonal indices.
    fertile=[p for p in snapshots[0].placements if p[0]=='flower' and 1.2<p[4]<3.2]
    focal=max(fertile,key=lambda p:p[2]+p[3]*1.8) if fertile else next(p for p in snapshots[0].placements if p[0]=='flower')
    socket=focal[2:5];cx=socket[0]+socket[1]*1.8
    crop=[cx-.12,cx+.12,socket[2]-.1,socket[2]+.14]
    detail=pygame.Surface((1540,555));detail.fill((13,20,17))
    detail.blit(font.render('Same lateral node | flowering, ripe capsules and winter | actual centimetre organs',True,(225,233,214)),(20,15))
    detail_records=[]
    for col,(name,age,snap) in enumerate(zip(['Flowering','Ripe capsules','Winter retention'],ages,snapshots)):
        host=next(i for i,p in enumerate(snap.placements) if p[0] in {'stem_section','branch_section'} and math.dist(p[2:5],socket)<1e-6)
        selected={host,int(snap.placements[host][1])}
        selected.update(i for i,p in enumerate(snap.placements) if p[1]==host and p[0] in {'leaf','flower','fruit'})
        view=DiagnosticCamera(500,420,crop,minimum_span_m=.001)
        canvas=panel(supported,age,(500,420),view,selected,False)
        pygame.draw.line(canvas,(225,205,133),(20,394),(20+round(.05*view.scale),394),3)
        canvas.blit(small.render('5 cm',True,(225,205,133)),(20,369))
        detail.blit(font.render(name,True,(225,233,214)),(20+col*510,52))
        detail.blit(canvas,(10+col*510,82))
        detail_records.append({'age_days':age,'host_index':host,'selected_indices':sorted(selected)})
    detail.blit(small.render('One flower glyph is a small cyme. Fruit glyphs are dehiscent capsules with red arils; counts are representative.',True,(169,190,163)),(20,523))
    pygame.image.save(detail,output_dir/'detail.png')
    (output_dir/'detail.json').write_text(json.dumps({'socket_m':socket,'crop_bounds':crop,'seed':sim.seed,
        'reference_environment':environment,'stages':detail_records},indent=2),encoding='utf-8')


def render_fungal_views(sim, output_dir):
    """Wood-associated fungi keep their support and metric envelope in all views."""
    from simulations.species.fungal_visuals import preview_wood_style
    ground = bool(sim.blueprint.growth.get('ground_fungal_version'))
    cup = sim.blueprint.growth['fungal_growth_profile'].get('body_form') == 'sessile_cup'
    stages = stage_ages(sim)
    sim.set_lod(2)
    snapshots = [sim.generate_snapshot(age, 2) for _, age in stages]
    bounds = fitted_bounds(snapshots)
    side_bounds = diagnostic_cell_bounds(SimpleNamespace(bounds_m=bounds))
    top_bounds = bounds[:4]
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sheet = pygame.Surface((1540, 1030)); sheet.fill((13, 20, 17))
    title = pygame.font.SysFont("consolas", 24)
    font = pygame.font.SysFont("consolas", 17)
    small = pygame.font.SysFont("consolas", 15)
    def label(text, x, y, heading=False):
        sheet.blit((title if heading else font).render(text, True, (217, 228, 207)), (x, y))
    def panel(size, age, view, cutaway=False):
        sim.set_age(age)
        sim.diagnostic_view = "mycelium" if cutaway else "individual"
        camera = (IsometricDiagnosticCamera(*size, bounds) if view == "iso" else
                  TopDownDiagnosticCamera(*size, top_bounds) if view == "top" else
                  DiagnosticCamera(*size, side_bounds))
        canvas = pygame.Surface(size)
        renderer._draw_individual(canvas, sim, camera=camera, cache=False,
                                 show_height_reference=False, draw_ground_line=False)
        ppm = renderer._projection_pixels_per_meter(camera)
        pygame.draw.line(canvas, (223, 205, 133), (18, size[1]-24),
                         (18+round(.2*ppm), size[1]-24), 3)
        canvas.blit(small.render("20 cm", True, (223, 205, 133)), (18, size[1]-47))
        return canvas
    mature_age = stages[3][1]
    label(sim.blueprint.display_name, 20, 16, True)
    label("Saved soil-fruiting recipe | renderer preview | seed 303" if ground else "Saved fungal recipe | standard oak bark reference | renderer preview | seed 303", 20, 51)
    label("ISOMETRIC | mature ascocarps on the soil" if ground else "ISOMETRIC | mature shelves on the wood support", 20, 89)
    sheet.blit(panel((890, 500), mature_age, "iso"), (10, 116))
    label("TOP | open cups" if cup else "TOP | pitted caps" if ground else "TOP | caps and wood section", 935, 89)
    sheet.blit(panel((590, 260), mature_age, "top"), (935, 116))
    label("CUTAWAY | diagnostic soil mycelium" if ground else "CUTAWAY | colony inside the wood", 935, 399)
    sheet.blit(panel((590, 200), mature_age, "side", True), (935, 425))
    label("Ground z=0; representative colony footprint/depth are calibration, not measured underground extent." if ground else "Preview trunk: 1.20 m long, 32 cm diameter. Reference artwork; host identity is unresolved.", 20, 637)
    label("One metric envelope across stages; main views fit independently. Organ sizes are unchanged.", 20, 661)
    records = []
    for index, (name, age) in enumerate(stages):
        x = 10+index*306
        label(name, x+8, 704)
        sheet.blit(small.render(f"Model day {age:g}", True, (174, 194, 166)), (x+8, 731))
        sheet.blit(panel((298, 216), age, "iso"), (x, 757))
        state = sim.render_snapshot.stats
        sheet.blit(small.render(f"{'Bodies' if ground else 'Shelves'} {state['estimated_fruiting_body_count']}", True, (174, 194, 166)), (x+8, 984))
        records.append({"label": name, "snapshot": sim.render_snapshot.to_dict(),
                        "ecology": sim.get_ecological_outcome()})
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view, map_sprite_at
    sim.set_age(mature_age)
    scene = SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),
                            world_units_to_meters=1.,
                            get_representative_species_simulation=lambda _rid: sim)
    instance = {'species_id': sim.species_id, 'representative_id': 'design_preview',
                'abundance': 1., 'visual_scale': 1., 'variant': 0}
    bio = BiosphereBuilderRenderer(SimpleNamespace(), species_renderer=renderer)
    billboard, _ = bio._render_sprite_surface(
        scene, instance, SimpleNamespace(zoom=400., sprite_height_cap=84))
    map_picture = top_view(sim)
    map_small = map_sprite_at(map_picture, 40) if map_picture else None
    inset = pygame.Rect(674, 429, 205, 169)
    pygame.draw.rect(sheet, (15, 28, 25), inset)
    pygame.draw.rect(sheet, (67, 87, 70), inset, 1)
    sheet.blit(small.render('BIOSIM | 84 px / 40 px', True, (190, 210, 176)), (683, 437))
    sheet.blit(billboard, (716 - billboard.get_width() // 2, 563 - billboard.get_height()))
    if map_small:
        sheet.blit(map_small, (813 - map_small.get_width() // 2,
                               522 - map_small.get_height() // 2))
    sheet.blit(small.render('grounded', True, (155, 179, 154)), (683, 574))
    sheet.blit(small.render('map', True, (155, 179, 154)), (795, 574))
    label("Illustrative fungal model clock; persistent colony and recurring fruiting bodies. Cutaway exposes diagnostic mycelium.", 20, 1007)
    output_dir.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, output_dir/"after.png")
    (output_dir/"after.json").write_text(json.dumps({"species_id": sim.species_id, "seed":303,
        "blueprint":sim.blueprint.to_dict(), "bounds_m":bounds, "stages":records,
        "preview_wood_style":None if ground else preview_wood_style(), "side_bounds_m":side_bounds,
        "source":"live resolved fungal species; representative substrate; production renderer"}, indent=2), encoding="utf-8")


def render_reproductive_inspection(species_id, output_dir):
    """Large matched elevations and a real crown crop at the same socket.

    The overview's little isometric stage tiles are insufficient to inspect
    slender fruits. This supplementary view keeps physical organ dimensions,
    foliage and complete canonical placements; only its cameras change.
    """
    pygame.init(); pygame.display.set_mode((1,1))
    sim = SpeciesSimulation(world_model=WorldModel(), species_id=species_id, seed=303)
    if sim.blueprint.growth.get('cyme_herb_version'):
        render_cyme_inspection(sim,output_dir)
        pygame.quit()
        return
    if sim.blueprint.growth.get('branched_vine_version'):
        render_vine_views(sim,output_dir)
        pygame.quit()
        return
    if sim.blueprint.growth.get('tufted_sedge_version'):
        render_sedge_inspection(sim, output_dir)
        pygame.quit()
        return
    if sim.blueprint.growth.get("fungal_grammar_version"):
        render_fungal_inspection(sim, output_dir)
        pygame.quit()
        return
    stages = stage_ages(sim)[1:]
    sim.set_lod(2)
    snapshots = [sim.generate_snapshot(age,2) for _,age in stages]
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    bounds = canopy_envelope(sim,snapshots)
    # Actual elevation, not the diagnostic oblique y exaggeration or a large
    # ground diamond. One union envelope holds scale constant between phases.
    rotation = 35.
    camera = fitted_inspection_elevation(sim,snapshots,500,760,rotation)
    fruit_sockets = [p for snap in snapshots for p in snap.placements if p[0]=='fruit']
    sockets = fruit_sockets or [p for snap in snapshots for p in snap.placements if p[0]=='flower']
    focal = max(sockets,key=lambda p:p[2]*camera.tangent_x+p[3]*camera.tangent_y) if sockets else None
    crop = list(bounds)
    crop_span = 1.6
    head_cluster = sim.blueprint.growth.get("inflorescence_profile", {}).get("form") in {"capitulum_cluster", "umbellate_head"}
    if focal:
        # Fit the inspected organs: a fixed tree-sized window hides centimetre
        # heads on herbs. Long pods retain the earlier 1.6 m crown window.
        organ_sizes = [sim.blueprint.module(k).length_m for k in ('leaf','flower','fruit')]
        crop_span = max(.12,min(1.6,max(organ_sizes)*3.))
        half = crop_span*.5
        crop = [focal[2]-half,focal[2]+half,focal[3]-half,focal[3]+half,
                max(0.,focal[4]-crop_span*.625),focal[4]+crop_span*.375]
        if head_cluster:
            cluster = sim.blueprint.growth["inflorescence_profile"]
            crop_span = max(crop_span, 3*max(cluster["width_m"], cluster["length_m"]))
            half = crop_span*.5
            crop = [focal[2]-half,focal[2]+half,focal[3]-half,focal[3]+half,
                    max(0.,focal[4]-crop_span*.6),focal[4]+crop_span*.8]
    cols=len(stages);step=510
    sheet=pygame.Surface((cols*step+10,1230));sheet.fill((13,20,17))
    font=pygame.font.SysFont('consolas',18)
    small=pygame.font.SysFont('consolas',15)
    def label(text,x,y,color=(223,231,212)):
        sheet.blit(font.render(text,True,color),(x,y))
    label(f'{sim.blueprint.display_name} | reproductive inspection | production renderer',18,12)
    label('Seed 303 | LOD 2 | identical whole-organism scale | unchanged physical organ sizes',18,40,(169,190,163))
    records=[]
    for col,((name,age),snapshot) in enumerate(zip(stages,snapshots)):
        sim.set_age(age)
        visible={i for i,p in enumerate(snapshot.placements) if p[0] not in
                 {'root','root_section','root_support','renewal_organ','renewal_bud'}}
        x=10+col*step
        label(f'{name} | developmental day {age:.0f}',x+10,76)
        for row,(size,window) in enumerate([((500,760),bounds),((500,275),crop)]):
            panel=pygame.Surface(size);panel.fill((17,27,25))
            view=fitted_inspection_elevation(sim,snapshots,*size,rotation) if row==0 else SurfaceElevationCamera(*size,window,rotation)
            detail_visible = visible
            if row == 1 and focal and head_cluster:
                # One complete outer cluster across phases. Other terminal
                # clusters entering the crop would appear cut by its border.
                detail_visible = {i for i in visible if snapshot.placements[i][0] not in {"flower","fruit"}
                                  or math.dist(snapshot.placements[i][2:5], focal[2:5]) < .001}
            renderer._draw_individual(panel,sim,snapshot=snapshot,camera=view,visible_indices=detail_visible,
                clear=False,cache=False,draw_environment=False,draw_ground_line=False)
            bar=1. if row==0 else .5 if crop_span >= 1. else .05
            pygame.draw.line(panel,(224,207,136),(20,size[1]-28),(20+round(bar*view.scale),size[1]-28),3)
            panel.blit(small.render(f'{bar:g} m',True,(224,207,136)),(20,size[1]-51))
            sheet.blit(panel,(x,108 if row==0 else 905))
        flowers=sum(p[0]=='flower' for p in snapshot.placements)
        fruits=sum(p[0]=='fruit' for p in snapshot.placements)
        from simulations.species.pendant_reproduction import pendant_display_units
        capsules=sum(len(pendant_display_units(sim.blueprint.growth,p,sim.blueprint.module('fruit'),sim.seed)) or 1
                     for p in snapshot.placements if p[0]=='fruit')
        flower_label = ('Flower heads' if sim.blueprint.growth.get('umbellate_head_version') else
                        'Panicles' if sim.blueprint.growth.get('reproductive_structure') == 'panicle' else 'Flowers')
        display_label = 'pods' if sim.blueprint.growth.get('reproductive_profile', {}).get('fruit_cluster_display') else 'fruit bodies'
        caption=f'{flower_label} {flowers} | fruit groups {fruits} | {display_label} {capsules}'
        sheet.blit(small.render(caption,True,(169,190,163)),(x+10,874))
        records.append({'stage':name,'age_days':age,'flowers':flowers,'fruits':fruits,'display_capsules':capsules,
                        'bounds_m':snapshot.bounds_m,'stats':snapshot.stats})
    label('Bottom: the same outer crown window in each phase; foliage is retained.',18,1194,(169,190,163))
    output_dir.mkdir(parents=True,exist_ok=True)
    pygame.image.save(sheet,output_dir/'after.png')
    branch_sheet=pygame.Surface((sheet.get_width(),350));branch_sheet.fill((13,20,17))
    stage_names = ', '.join(name.lower() for name,_ in stages)
    branch_title = 'Same outer terminal cluster' if head_cluster else 'Same fertile branch'
    branch_sheet.blit(font.render(f'{branch_title} | {stage_names} | production renderer',True,(223,231,212)),(18,12))
    branch_sheet.blit(sheet.subsurface((0,905,sheet.get_width(),275)),(0,52))
    pygame.image.save(branch_sheet,output_dir/'detail.png')
    (output_dir/'after.json').write_text(json.dumps({'species_id':species_id,'seed':303,'lod':2,
        'blueprint':sim.blueprint.to_dict(),
        'blueprint_fingerprint':sim.blueprint.fingerprint(),'overview_bounds_m':bounds,
        'crop_bounds_m':crop,'elevation_rotation_degrees':rotation,'stages':records,
        'projected_overview_bounds':camera.inspection_bounds,
        'source':'live resolved species; production renderer; camera-only inspection'},indent=2),encoding='utf-8')
    pygame.quit()


def render_cyme_inspection(sim,output_dir):
    """One actual forked crown and the same bracted reproductive node."""
    p=sim.blueprint.growth['reproductive_profile'];sim.set_lod(2)
    ages=[p['cycle_days']*(p['flowering_start']+p['fruit_start'])/2,p['cycle_days']*p['fruit_ripe']]
    snapshots=[sim.generate_snapshot(age,2) for age in ages]
    first=snapshots[0]
    ray=next(int(i) for i,v in first.placement_orientations.items() if v.get('leaf_role')=='primary_ray')
    crown=first.placements[first.placements[ray][1]][2:5]
    floral=next((i,v) for i,v in first.placement_orientations.items() if v.get('leaf_role')=='cyathium')
    stalk=int(first.placements[int(floral[0])][1]);socket=first.placements[first.placements[stalk][1]][2:5]
    cx=crown[0]+crown[1]*1.8;ux=socket[0]+socket[1]*1.8
    whole=[cx-.17,cx+.17,crown[2]-.06,crown[2]+.14]
    close=[ux-.045,ux+.045,socket[2]-.035,socket[2]+.035]
    renderer=SpeciesRenderer(SimpleNamespace(camera=None));font=pygame.font.SysFont('consolas',18);small=pygame.font.SysFont('consolas',15)
    sheet=pygame.Surface((1540,1000));sheet.fill((13,20,17));records=[]
    sheet.blit(font.render(f'{sim.blueprint.display_name} | crown and cyathium / capsule inspection',True,(225,233,214)),(20,15))
    sheet.blit(font.render('Same seed, shoot, sockets and physical scale. Bracts are separate photosynthetic leaves.',True,(169,190,163)),(20,47))
    for col,(name,age,snap) in enumerate(zip(['Flowering cyathia','Fruiting capsules'],ages,snapshots)):
        sim.set_age(age)
        host=next(i for i,v in enumerate(snap.placements) if v[0]=='stem_section' and math.dist(v[2:5],crown)<1e-6)
        branch_host=next(i for i,v in enumerate(snap.placements) if v[0]=='branch_section' and math.dist(v[2:5],socket)<1e-6)
        all_crown={host}
        for i,v in enumerate(snap.placements):
            if v[1] in all_crown:all_crown.add(i)
        unit={branch_host}
        unit.update(i for i,v in enumerate(snap.placements) if v[1]==branch_host and
                    (v[0]=='leaf' or snap.placement_orientations[str(i)].get('leaf_role')=='reproductive_stalk'))
        unit.update(i for i,v in enumerate(snap.placements) if v[1] in unit and v[0] in {'flower','fruit'})
        x=10+col*770;sheet.blit(font.render(name,True,(225,233,214)),(x+10,82))
        for row,(bounds,selected,size,bar) in enumerate([(whole,all_crown,(750,435),.05),(close,unit,(520,370),.01)]):
            camera=DiagnosticCamera(*size,bounds,minimum_span_m=.001);panel=pygame.Surface(size);panel.fill((17,27,25))
            renderer._draw_individual(panel,sim,snapshot=snap,camera=camera,visible_indices=selected,
                clear=False,cache=False,draw_environment=False,draw_ground_line=False)
            pygame.draw.line(panel,(225,205,133),(20,size[1]-25),(20+round(bar*camera.scale),size[1]-25),3)
            panel.blit(small.render('5 cm' if row==0 else '1 cm',True,(225,205,133)),(20,size[1]-49))
            sheet.blit(panel,(x,116 if row==0 else 588))
        kind='flower' if col==0 else 'fruit';source=renderer._module_asset(sim,kind)
        sheet.blit(small.render('Native 75 x 75',True,(169,190,163)),(x+545,605))
        sheet.blit(source,(x+560,639));sheet.blit(pygame.transform.scale(source,(150,150)),(x+540,753))
        records.append({'age_days':age,'crown_host':host,'reproductive_host':branch_host,'stats':snap.stats})
    sheet.blit(small.render('Top: five primary rays with paired forks. Bottom: one bract pair, one 2.1 mm cyathium or 3.2 mm capsule.',True,(169,190,163)),(20,973))
    output_dir.mkdir(parents=True,exist_ok=True);pygame.image.save(sheet,output_dir/'detail.png')
    (output_dir/'detail.json').write_text(json.dumps({'species_id':sim.species_id,'seed':sim.seed,'lod':2,
        'crown_bounds':whole,'close_bounds':close,'stages':records,'source':'saved traits; production renderer; separate bract leaves'},indent=2),encoding='utf-8')


def render_sedge_inspection(sim, output_dir):
    """Matched terminal crowns and spikelet artwork, without enlarging organs."""
    profile=sim.blueprint.growth['reproductive_profile']
    ages=[profile['cycle_days']*(profile['flowering_start']+profile['fruit_start'])/2,
          profile['cycle_days']*profile['fruit_ripe']]
    snapshots=[sim.generate_snapshot(age,2) for age in ages]
    head=snapshots[0].stats['sedge_heads'][0]
    x,y,z=head['socket_m'];cx=x+1.8*y
    bounds=(cx-.055,cx+.055,z-.025,z+.045)
    host=head['host_placement_index'];selected={host}
    for i,p in enumerate(snapshots[0].placements):
        if p[1] in selected:selected.add(i)
    focal=next(i for i,p in enumerate(snapshots[0].placements) if i in selected and p[0]=='flower')
    px,py,pz=snapshots[0].placements[focal][2:5];pc=px+1.8*py
    unit_bounds=(pc-.014,pc+.014,pz-.006,pz+.022)
    sheet=pygame.Surface((1540,930));sheet.fill((13,20,17))
    font=pygame.font.SysFont('consolas',18);title=pygame.font.SysFont('consolas',24)
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    def label(t,x,y):sheet.blit(font.render(t,True,(218,229,206)),(x,y))
    sheet.blit(title.render(sim.blueprint.display_name+' | reproductive inspection',True,(226,234,215)),(20,16))
    label('Same seed, culm socket, scale and dimensions. Crown crops cut the long bracts; lower panes enlarge one spikelet.',20,52)
    records=[]
    for column,(age,name) in enumerate(zip(ages,['GREEN-YELLOW | spikelets in flower','BROWN | fruiting spikelets'])):
        left=10+column*770;label(name,left+10,90)
        sim.set_lod(2);sim.set_age(age)
        for top,size,view_bounds,indices,bar in [(119,(750,400),bounds,selected,.02),(573,(520,320),unit_bounds,{focal},.01)]:
            panel=pygame.Surface(size);camera=DiagnosticCamera(*size,view_bounds,minimum_span_m=.001)
            renderer._draw_individual(panel,sim,camera=camera,visible_indices=indices,cache=False,
                                     show_height_reference=False,draw_ground_line=False,draw_environment=False)
            length=round(bar*renderer._projection_pixels_per_meter(camera))
            pygame.draw.line(panel,(223,205,133),(18,size[1]-20),(18+length,size[1]-20),3)
            panel.blit(font.render(f'{bar*100:g} cm',True,(223,205,133)),(18,size[1]-46))
            sheet.blit(panel,(left,top))
        label('ONE SPIKELET | not one flower or nutlet',left+10,545)
        role='flower' if column==0 else 'fruit';module=sim.blueprint.module(role)
        sprite=pygame.image.load(module.asset_ref)
        label('Native 75 x 75',left+535,590)
        sheet.blit(sprite,(left+580,625))
        sheet.blit(pygame.transform.scale(sprite,(150,150)),(left+547,720))
        records.append({'age_days':age,'snapshot':sim.render_snapshot.to_dict(),'ecology':sim.get_ecological_outcome()})
    label('12 mm representative spikelet; actual nutlets about 1 mm, not individually resolved. Model dates are qualitative.',20,905)
    output_dir.mkdir(parents=True,exist_ok=True)
    pygame.image.save(sheet,output_dir/'detail.png')
    (output_dir/'detail.json').write_text(json.dumps({'seed':303,'lod':2,'head_host_index':host,
        'matched_head_camera_m':bounds,'matched_spikelet_camera_m':unit_bounds,'records':records,
        'source':'saved live recipe, matched production renderer crops'},indent=2),encoding='utf-8')


def render_fungal_inspection(sim, output_dir):
    """Shared-scale early/mature supports and one enlarged attached shelf."""
    recipe = sim.blueprint.growth["fungal_growth_profile"]["resolved"]
    first, cycle = recipe["first_flush_model_days"], recipe["flush_cycle_model_days"]
    young_age = first+cycle*.04
    mature_age = stage_ages(sim)[3][1]
    sim.set_lod(2)
    snapshots = [sim.generate_snapshot(age, 2) for age in (young_age, mature_age)]
    bounds = diagnostic_cell_bounds(SimpleNamespace(bounds_m=fitted_bounds(snapshots)))
    body = snapshots[1].stats["fungal_bodies"][0]
    x,y,z = body["cap_socket_m"]
    from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION
    projected_x = x+y*SCREEN_DEPTH_PROJECTION
    close = (projected_x-.38, projected_x+.5, z-.24, z+.3)
    top_close = (x-.4, x+.4, y-.35, y+.45)
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sheet = pygame.Surface((1540, 950));sheet.fill((13,20,17))
    font = pygame.font.SysFont("consolas", 18)
    title = pygame.font.SysFont("consolas", 24)
    sheet.blit(title.render(f"{sim.blueprint.display_name} | shelf size and attachment", True, (226,234,215)), (20,16))
    sheet.blit(font.render("Upper views share camera scale and standard wood. Lower crops enlarge one attached shelf.",True,(174,195,167)),(20,51))
    records=[]
    def draw(size, age, camera, indices=None):
        sim.set_age(age);sim.diagnostic_view="individual"
        canvas=pygame.Surface(size)
        renderer._draw_individual(canvas,sim,camera=camera,cache=False,visible_indices=indices,
                                 show_height_reference=False,draw_ground_line=False)
        pixels=round(.2*renderer._projection_pixels_per_meter(camera))
        pygame.draw.line(canvas,(223,205,133),(18,size[1]-24),(18+pixels,size[1]-24),3)
        canvas.blit(font.render("20 cm",True,(223,205,133)),(18,size[1]-49))
        return canvas
    for index,(label,age) in enumerate((("Emerging shelves",young_age),("Mature shelves",mature_age))):
        left=10+index*765
        widths=[b["cap_width_m"]*100 for b in snapshots[index].stats["fungal_bodies"]]
        sheet.blit(font.render(f"{label} | caps {min(widths):.1f}-{max(widths):.1f} cm | model day {age:g}",True,(213,224,205)),(left+8,89))
        sheet.blit(draw((755,330),age,DiagnosticCamera(755,330,bounds)),(left,116))
        records.append({"label":label,"snapshot":sim.render_snapshot.to_dict(),"ecology":sim.get_ecological_outcome()})
    selected={body["placement_index"]}
    sheet.blit(font.render("ENLARGED | same mature shelf and partial wood support",True,(213,224,205)),(20,476))
    sheet.blit(font.render("TOP CROP | same shelf, overhead asset",True,(213,224,205)),(790,476))
    sheet.blit(draw((755,420),mature_age,DiagnosticCamera(755,420,close),selected),(10,505))
    sheet.blit(draw((755,420),mature_age,TopDownDiagnosticCamera(755,420,top_close),selected),(775,505))
    output_dir.mkdir(parents=True,exist_ok=True)
    pygame.image.save(sheet,output_dir/"detail.png")
    (output_dir/"detail.json").write_text(json.dumps({"seed":303,"shared_bounds_m":bounds,
        "selected_body_id":body["id"],"stages":records,"source":"saved fungal species; production renderer; unchanged dimensions"},indent=2),encoding="utf-8")


def fitted_inspection_elevation(sim,snapshots,width,height,rotation):
    """Fit projected organs, avoiding the empty corners of a rotated AABB."""
    from simulations.species.pendant_reproduction import pendant_display_units
    camera=SurfaceElevationCamera(width,height,[-1,1,-1,1,0,1],rotation)
    projected=[]
    def add(point,margin=0.):
        x,y,z=point
        u=x*camera.tangent_x+y*camera.tangent_y
        projected.extend(((u-margin,z-margin),(u+margin,z+margin)))
    root_kinds={'root','root_section','root_support','renewal_organ','renewal_bud'}
    leaf_length=sim.blueprint.module('leaf').length_m
    for snapshot in snapshots:
        for p in snapshot.placements:
            if p[0] in root_kinds:continue
            margin=leaf_length if p[0]=='leaf' else 0.
            add(p[2:5],margin)
            if p[0] in {'flower','fruit'}:
                units=pendant_display_units(sim.blueprint.growth,p,sim.blueprint.module(p[0]),sim.seed)
                for a,b in units:add(a,.03);add(b,.03)
                if p[0]=='flower':
                    profile=sim.blueprint.growth.get('inflorescence_profile') or {}
                    add(p[2:5],max(profile.get('length_m',0),profile.get('width_m',0)))
        for cluster in snapshot.leaf_clusters:
            if cluster.get('estimated_leaf_count',0)>0:
                add(cluster['position_m'],leaf_length*2+float(cluster.get('length',0))/2)
    min_u=min(p[0] for p in projected);max_u=max(p[0] for p in projected)
    min_z=min(0.,min(p[1] for p in projected));max_z=max(p[1] for p in projected)
    pad=max(.02,(max_u-min_u)*.03)
    min_u-=pad;max_u+=pad;max_z+=max(.02,(max_z-min_z)*.02)
    camera.min_u, camera.max_u = min_u,max_u
    camera.min_z,camera.max_z=min_z,max_z
    camera.scale=min((width-48)/max(.1,max_u-min_u),(height-48)/max(.1,max_z-min_z))
    camera.offset_x=width*.5-(min_u+max_u)*.5*camera.scale
    camera.bottom=height-24+min_z*camera.scale
    camera.inspection_bounds=[min_u,max_u,min_z,max_z]
    return camera


def render_fern_inspection(species_id,output_dir):
    """A rhizome patch and one independently fitted botanical frond."""
    pygame.init();pygame.display.set_mode((1,1))
    sim=SpeciesSimulation(world_model=WorldModel(),species_id=species_id,seed=303)
    if sim.blueprint.growth.get('growth_form')!='fern':
        raise ValueError('Fern inspection requires a fern blueprint')
    sim.set_lod(2);sim.set_age(sim.mature_age_days)
    mature=sim.render_snapshot
    young=sim.generate_snapshot(sim.mature_age_days*.25,2)
    bounds=canopy_envelope(sim,[young,mature])
    index,leaf=max(((i,p) for i,p in enumerate(mature.placements) if p[0]=='leaf'),key=lambda x:x[1][6])
    path=mature.placement_paths[str(index)]
    pad=max(.05,sim.blueprint.module('leaf').visual.get('frond_blade_width_m',.3)*.65)
    ux=[p[0]+p[1]*1.8 for p in path];z=[p[2] for p in path]
    one_side=(min(ux)-pad,max(ux)+pad,min(z)-pad,max(z)+pad)
    one_top=(min(p[0] for p in path)-pad,max(p[0] for p in path)+pad,
             min(p[1] for p in path)-pad,max(p[1] for p in path)+pad)
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    sheet=pygame.Surface((1600,1480));sheet.fill((13,20,17))
    font=pygame.font.SysFont('consolas',18);small=pygame.font.SysFont('consolas',15)
    def label(text,x,y):sheet.blit(font.render(text,True,(225,233,214)),(x,y))
    label(f'{sim.blueprint.display_name} | saved fern inspection | production renderer',18,14)
    label('Seed 303 | LOD 2 | one bounded rhizome representative | frond details enlarged separately',18,43)
    def draw(size,snapshot,camera,visible,bar):
        panel=pygame.Surface(size);panel.fill((17,27,25))
        renderer._draw_individual(panel,sim,snapshot=snapshot,camera=camera,visible_indices=visible,
            clear=False,cache=False,draw_environment=False,draw_ground_line=False)
        pygame.draw.line(panel,(223,205,133),(20,size[1]-23),(20+round(bar*camera.scale),size[1]-23),3)
        panel.blit(small.render(f'{bar:g} m',True,(223,205,133)),(20,size[1]-46))
        return panel
    size=(780,470)
    label('ISOMETRIC | canopy; concealed rhizomes omitted',20,82)
    sheet.blit(draw(size,mature,IsometricDiagnosticCamera(*size,bounds),canopy_visible_indices(sim,mature),1.),(10,110))
    label('ONE FROND | paired pinnae and divided lamina',820,82)
    sheet.blit(draw(size,mature,DiagnosticCamera(*size,one_side),{index},.5),(810,110))
    size=(780,290)
    label('TOP | spaced living fronds',20,592)
    sheet.blit(draw(size,mature,TopDownDiagnosticCamera(*size,bounds[:4]),canopy_visible_indices(sim,mature),1.),(10,620))
    label('TOP | the same individual frond',820,592)
    sheet.blit(draw(size,mature,TopDownDiagnosticCamera(*size,one_top),{index},.5),(810,620))
    size=(780,175)
    label('SOIL CUTAWAY | rhizome and distributed roots retained',20,927)
    sheet.blit(draw(size,mature,DiagnosticCamera(*size,diagnostic_cell_bounds(mature)),None,.5),(10,954))
    label('YOUNG PATCH | shared mature canopy scale',820,927)
    sim.set_age(sim.mature_age_days*.25)
    sheet.blit(draw(size,young,IsometricDiagnosticCamera(*size,bounds),canopy_visible_indices(sim,young),1.),(810,954))
    label('One frond is one botanical leaf. Segment glyphs and hierarchy do not add ecological organs.',18,1137)
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view, map_sprite_at
    sim.set_age(sim.mature_age_days)
    scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,
        get_representative_species_simulation=lambda _rid:sim)
    instance={'species_id':species_id,'representative_id':'inspection','abundance':1.,
              'visual_scale':1.,'variant':0}
    biosim_renderer=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)
    label('BIOSIM | production grounded sprite and map picture | native pixel sizes',20,1172)
    biosim_sizes={}
    for cap,root_x in ((220,250),(84,600)):
        art,anchor=biosim_renderer._render_sprite_surface(
            scene,instance,SimpleNamespace(zoom=400.,sprite_height_cap=cap))
        sheet.blit(art,(round(root_x-anchor[0]),round(1410-anchor[1])))
        pygame.draw.line(sheet,(105,97,70),(root_x-185 if cap==220 else root_x-60,1410),
                         (root_x+185 if cap==220 else root_x+60,1410))
        label(f'{cap}px cap | {art.get_width()}x{art.get_height()} px',root_x-170 if cap==220 else root_x-70,1204)
        biosim_sizes[str(cap)]=list(art.get_size())
    picture=top_view(sim)
    if picture is not None:
        sheet.blit(picture,(850,1240))
        sheet.blit(map_sprite_at(picture,40),(1195,1330))
        label(f'top picture | {picture.get_width()}x{picture.get_height()} px',850,1450)
        label('40px map',1175,1450)
        biosim_sizes['top']=list(picture.get_size())
    output_dir.mkdir(parents=True,exist_ok=True)
    pygame.image.save(sheet,output_dir/'after.png')
    (output_dir/'after.json').write_text(json.dumps({'species_id':species_id,'seed':303,'lod':2,
        'blueprint':sim.blueprint.to_dict(),'blueprint_fingerprint':sim.blueprint.fingerprint(),
        'canopy_bounds_m':bounds,'single_frond_side_bounds_m':one_side,'single_frond_top_bounds_m':one_top,
        'single_frond_index':index,'mature':mature.to_dict(),'young':young.to_dict(),
        'source':'live resolved species; production renderer; independent whole-frond detail',
        'biosim_sizes_px':biosim_sizes},indent=2),encoding='utf-8')
    pygame.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--species", required=True)
    parser.add_argument("--output-dir", type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--inspection", action="store_true", help="Large matched reproductive elevations (after.png) and crown crop (detail.png)")
    mode.add_argument('--fern-inspection',action='store_true',help='Large fern patch plus independent whole-frond detail')
    args = parser.parse_args()
    (render_fern_inspection if args.fern_inspection else render_reproductive_inspection if args.inspection else render)(args.species, args.output_dir or Path("artifacts")/args.species)


if __name__ == "__main__":
    main()
