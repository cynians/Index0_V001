"""Herbaceous crown shoots; no runners or invented woody basal tissue."""
from simulations.species.basal_subshrubs import basal_shoot_profile, grow_basal_shoots


def basal_herb_profile(value):
    # Wider complete compound leaves are permitted on herbaceous shoots.
    return basal_shoot_profile(value, 'basal_herb', .15)


def grow_basal_herb(sim, placements, maturity, lod, life, paths, clusters, attachments):
    return grow_basal_shoots(sim, sim.blueprint.growth['basal_herb_profile'], 'basal_herb',
        placements, maturity, lod, life, paths, clusters, attachments)
