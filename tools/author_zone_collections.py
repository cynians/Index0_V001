"""A plant collection for every Koppen zone, from the plants in the catalogue.

A collection is a list of species with a rarity each
(``simulations/biosphere/flora.py``); a biome's flora set by one has those
species present at those rarities.  The collections here are one to a climate
zone, so that ground of any zone on any planet can be given a flora to test
with: ``assign`` sets the floras of the biomes a region shows, each by the
collection of its own zone.

How they were put together (2026-10-11, from 57 plants):

* a plant is in a zone's collection when the zone lies within the climates it
  grows wild in (``thermal_range_coldest`` to ``thermal_range_warmest``) and
  the Biosphere's own limits let it live over most of the zone's range of
  winters and summers (``check`` prints both);
* one collection holds the zone's plants of dry, ordinary and wet ground and
  of open water together: the ground sorts them (each plant holds only the
  wetness, the depth of soil and the salt it bears), so the same collection
  serves a zone's wetland, riverside and open-water biomes too;
* a rarity is how much of the ground that suits a plant it is met on
  (dominant all of it, common six tenths, occasional two tenths, rare a
  twentieth), so it says how common a plant is in its own place, not how much
  of the zone that place is.  Trees are "common" at most: woods with open
  ground between them, which is where the herbs of the catalogue grow.  The
  zone's plant of soaked ground is as common there as its main plants are on
  theirs: it is often the only one the catalogue has for such ground, and at
  less a wetland stands half bare;
* the catalogue is small and from every continent, so a collection mixes
  floras that never met (an English oak beside a coast redwood), and some
  zones are thin: no tropical grass, no tree of the coldest winters, nothing
  that grows on an ice cap.

    py -m tools.author_zone_collections                  # what would be written
    py -m tools.author_zone_collections check            # every plant against its zones, and plants left out
    py -m tools.author_zone_collections --apply          # write the collections (nothing else may run)
    py -m tools.author_zone_collections assign --region refined_lod4_29a30fb2ae [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

COLLECTION_PREFIX = "biosphere_collection_koppen_"

# The winters and summers a zone spans, as (coldest month, warmest month) in degrees C at a few places of it,
# and the climates of the plant scale (``ecology.THERMAL_ZONES``) it lies in.
ZONE_CLIMATES = {
    "Af": ([(24, 27), (21, 26), (25, 29)], ("hot",)),
    "Am": ([(22, 28), (20, 29), (25, 30)], ("hot",)),
    "Aw": ([(20, 28), (19, 31), (24, 33)], ("hot",)),
    "As": ([(20, 28), (19, 31), (24, 33)], ("hot",)),
    "BWh": ([(12, 34), (18, 38), (10, 30), (22, 36)], ("very_hot", "hot")),
    "BWk": ([(-8, 24), (-15, 20), (2, 17), (-3, 27)], ("cool", "cold")),
    "BSh": ([(12, 30), (16, 33), (19, 29), (10, 27)], ("hot", "warm")),
    "BSk": ([(-6, 22), (-12, 20), (3, 18), (0, 25)], ("cool", "cold")),
    "Csa": ([(8, 26), (5, 24), (11, 28)], ("mild", "warm")),
    "Csb": ([(6, 19), (9, 17), (3, 21)], ("mild", "cool")),
    "Csc": ([(2, 12), (4, 11), (1, 13)], ("cool", "cold", "frigid")),
    "Cwa": ([(10, 27), (13, 28), (6, 25)], ("warm", "mild")),
    "Cwb": ([(10, 18), (12, 20), (7, 16)], ("mild", "cool")),
    "Cwc": ([(3, 12), (6, 11), (2, 13)], ("cool", "cold", "frigid")),
    "Cfa": ([(4, 26), (10, 28), (2, 24), (15, 23)], ("warm", "mild")),
    "Cfb": ([(2, 17), (6, 19), (10, 16), (14, 21)], ("cool", "mild", "cold")),
    "Cfc": ([(1, 11), (3, 12), (5, 10.5)], ("cold", "frigid")),
    "Dsa": ([(-4, 25), (-8, 23), (-1, 27)], ("cool", "mild")),
    "Dsb": ([(-5, 19), (-9, 17), (-2, 21)], ("cool", "cold")),
    "Dsc": ([(-12, 14), (-18, 12), (-8, 15)], ("cold",)),
    "Dsd": ([(-40, 14), (-42, 12)], ("frigid", "cold")),
    "Dwa": ([(-8, 25), (-14, 24), (-4, 26)], ("cool", "mild")),
    "Dwb": ([(-14, 20), (-18, 18), (-8, 21)], ("cool", "cold")),
    "Dwc": ([(-22, 15), (-28, 13), (-16, 16)], ("cold",)),
    "Dwd": ([(-40, 15), (-44, 13)], ("frigid", "cold")),
    "Dfa": ([(-5, 24), (-9, 23), (-2, 26)], ("cool", "mild")),
    "Dfb": ([(-8, 19), (-12, 18), (-4, 21)], ("cool", "cold")),
    "Dfc": ([(-20, 15), (-26, 13), (-14, 16)], ("cold",)),
    "Dfd": ([(-42, 16), (-45, 13)], ("frigid", "cold")),
    "ET": ([(-25, 6), (-10, 8), (-2, 5.5), (-32, 4)], ("frigid",)),
    "EF": ([(-30, -2), (-45, -8)], ("frigid",)),
}

D, C, O, R = "dominant", "common", "occasional", "rare"

# zone: (what the vegetation is like, {species: rarity}).  Species ids without their ``spec_``.
ZONE_COLLECTIONS = {
    "Af": ("Evergreen forest with sausage tree and litchi, a herb layer of woodnettle and flatsedge, clubmoss on "
           "wet banks and nipa palm along tidal water.", {
        "kigelia_africana": C, "litchi_chinensis": O, "moringa_oleifera": R, "nypa_fruticans": C,
        "solanum_lycocarpum": R,
        "laportea_aestuans": D, "cyperus_polystachyos": C, "palhinhaea_cernua": D,
        "eupatorium_macrocephalum": O, "praxelis_clematidea": O,
    }),
    "Am": ("Monsoon forest: sausage tree, litchi and moringa, a baobab here and there, woodnettle and flatsedge "
           "beneath, nipa palm on tidal water.", {
        "kigelia_africana": C, "litchi_chinensis": O, "moringa_oleifera": O, "adansonia_digitata": R, "nypa_fruticans": C,
        "solanum_lycocarpum": O,
        "laportea_aestuans": D, "cyperus_polystachyos": C, "palhinhaea_cernua": C,
        "eupatorium_macrocephalum": O, "praxelis_clematidea": O,
    }),
    "Aw": ("Savanna: baobab, moringa and sausage tree standing apart, wolf apple and agave below, pompom weed and "
           "praxelis for a field layer (the catalogue has no tropical grass), flatsedge on wet ground.", {
        "adansonia_digitata": O, "moringa_oleifera": O, "kigelia_africana": O, "litchi_chinensis": R,
        "solanum_lycocarpum": C, "agave_americana": O,
        "eupatorium_macrocephalum": D, "praxelis_clematidea": C, "laportea_aestuans": O,
        "cyperus_polystachyos": C, "palhinhaea_cernua": O, "nypa_fruticans": R,
    }),
    "As": ("Savanna with a dry summer: as the dry-winter savanna.", {
        "adansonia_digitata": O, "moringa_oleifera": O, "kigelia_africana": O, "litchi_chinensis": R,
        "solanum_lycocarpum": C, "agave_americana": O,
        "eupatorium_macrocephalum": D, "praxelis_clematidea": C, "laportea_aestuans": O,
        "cyperus_polystachyos": C, "palhinhaea_cernua": O, "nypa_fruticans": R,
    }),
    "BWh": ("Hot desert: saguaro and agave far apart, sand verbena after rain, a baobab or a moringa along a "
            "wash, flatsedge at water.", {
        "carnegiea_gigantea": O, "agave_americana": O, "adansonia_digitata": R, "moringa_oleifera": R,
        "abronia_angustifolia": C, "cyperus_polystachyos": R,
    }),
    "BWk": ("Cold desert: nitre bush on salt and sand, thistle and plantain on disturbed ground, rock lichens, a "
            "pine or a rose where water gathers.", {
        "nitraria_sibirica": C, "pinus_sylvestris": R, "rosa_woodsii": R,
        "cirsium_arvense": O, "plantago_major": O, "symphyotrichum_novaeangliae": R, "scirpus_sylvaticus": O,
        "rusavskia_elegans": O, "stereocaulon_vesuvianum": O, "lecanora_muralis": O,
    }),
    "BSh": ("Hot steppe: agave and wolf apple, baobab and moringa standing apart, sand verbena, pompom weed and "
            "praxelis for a field layer, flatsedge at water.", {
        "agave_americana": C, "solanum_lycocarpum": O, "adansonia_digitata": O, "moringa_oleifera": O, "carnegiea_gigantea": R,
        "abronia_angustifolia": C, "eupatorium_macrocephalum": C, "praxelis_clematidea": C, "cichorium_intybus": R,
        "cyperus_polystachyos": O, "palhinhaea_cernua": R,
    }),
    "BSk": ("Cold steppe: nitre bush and wild rose, thistle, plantain and aster for a field layer (the catalogue "
            "has no steppe grass but ryegrass on moist ground), a pine at the forest's edge, club-rush at water.", {
        "nitraria_sibirica": C, "rosa_woodsii": O, "pinus_sylvestris": R,
        "cirsium_arvense": C, "plantago_major": C, "cichorium_intybus": O, "symphyotrichum_novaeangliae": O,
        "erigeron_annuus": O, "lysimachia_arvensis": O, "lolium_perenne": O, "torilis_arvensis": R,
        "scirpus_sylvaticus": C, "nymphaea_alba": R,
        "rusavskia_elegans": O, "stereocaulon_vesuvianum": O, "lecanora_muralis": O,
    }),
    "Csa": ("Mediterranean scrub and open wood: buchu, a corm lily, black mulberry and silver wattle, agave, "
            "chicory, pimpernel and hedge-parsley in the herb layer, green in winter.", {
        "morus_nigra": O, "acacia_dealbata": O, "quercus_petraea": R, "robinia_pseudoacacia": R,
        "agave_americana": O, "buddleja_davidii": R, "philadelphus_coronarius": R,
        "agathosma_mundii": C, "codonorhiza_elandsmontana": O, "cichorium_intybus": C, "lysimachia_arvensis": C,
        "torilis_arvensis": C, "plantago_major": O, "lolium_perenne": O, "nitraria_sibirica": R,
        "cyperus_polystachyos": O, "scirpus_sylvaticus": O, "nymphaea_alba": R,
        "lecanora_muralis": O, "rusavskia_elegans": R,
    }),
    "Csb": ("Cool-summer Mediterranean: redwood on the fog coast, oaks and silver wattle, bracken under them, "
            "ryegrass meadow with its herbs, buchu on dry slopes.", {
        "sequoia_sempervirens": C, "quercus_petraea": O, "quercus_robur": O, "acacia_dealbata": O,
        "pinus_sylvestris": R, "aesculus_hippocastanum": R,
        "pteridium_aquilinum": C, "buddleja_davidii": O, "philadelphus_coronarius": O,
        "lolium_perenne": D, "plantago_major": C, "cichorium_intybus": O, "lysimachia_arvensis": O,
        "torilis_arvensis": O, "cirsium_arvense": O, "agathosma_mundii": O, "codonorhiza_elandsmontana": R,
        "scirpus_sylvaticus": C, "nymphaea_alba": O, "celastrus_orbiculatus": R, "lecanora_muralis": O,
    }),
    "Csc": ("Cool, summer-dry coast: pine and birch, wild rose and bracken, crowberry heath, thistle and plantain, "
            "club-rush on wet ground.", {
        "pinus_sylvestris": O, "betula_pendula": O, "rosa_woodsii": O, "pteridium_aquilinum": O,
        "empetrum_nigrum": O, "cirsium_arvense": C, "plantago_major": C, "lolium_perenne": O,
        "symphyotrichum_novaeangliae": O, "erigeron_annuus": O, "oxyria_digyna": R,
        "scirpus_sylvaticus": C, "rusavskia_elegans": O, "stereocaulon_vesuvianum": O, "lecanora_muralis": O,
    }),
    "Cwa": ("Monsoon subtropics: litchi, ginkgo, mulberry and moringa, wolf apple and agave, pompom weed and "
            "praxelis grassland, flatsedge and clubmoss on wet ground.", {
        "litchi_chinensis": C, "ginko_biloba": O, "morus_nigra": O, "moringa_oleifera": O, "acer_rubrum": R,
        "solanum_lycocarpum": O, "agave_americana": O, "ptisana_howeana": R, "buddleja_davidii": R, "pteridium_aquilinum": O,
        "eupatorium_macrocephalum": C, "praxelis_clematidea": C, "cichorium_intybus": O, "lysimachia_arvensis": O,
        "torilis_arvensis": R, "nuttallanthus_canadensis": R,
        "cyperus_polystachyos": O, "palhinhaea_cernua": C, "peltandra_virginica": R,
        "celastrus_orbiculatus": O, "lecanora_muralis": R,
    }),
    "Cwb": ("Subtropical highland: mountain bamboo, silver wattle, butterfly bush and bracken, ryegrass and "
            "plantain, flatsedge at water.", {
        "oldeania_alpina": C, "acacia_dealbata": O, "quercus_robur": R, "ginko_biloba": R, "morus_nigra": R,
        "buddleja_davidii": C, "pteridium_aquilinum": C, "philadelphus_coronarius": R,
        "lolium_perenne": C, "plantago_major": C, "cichorium_intybus": O, "cirsium_arvense": O,
        "lysimachia_arvensis": O, "torilis_arvensis": R,
        "cyperus_polystachyos": O, "scirpus_sylvaticus": O, "nymphaea_alba": R,
        "celastrus_orbiculatus": R, "lecanora_muralis": O, "rusavskia_elegans": O,
    }),
    "Cwc": ("Cool highland with a dry winter: mountain bamboo thinning out, bracken, crowberry and mountain sorrel, "
            "plantain and thistle, rock lichens.", {
        "oldeania_alpina": O, "pinus_sylvestris": R, "betula_pendula": R, "rosa_woodsii": R, "pteridium_aquilinum": O,
        "empetrum_nigrum": O, "oxyria_digyna": O, "plantago_major": C, "cirsium_arvense": O,
        "symphyotrichum_novaeangliae": R, "scirpus_sylvaticus": C,
        "rusavskia_elegans": C, "stereocaulon_vesuvianum": C, "lecanora_muralis": O,
    }),
    "Cfa": ("Humid subtropical woodland: red maple with oak, ginkgo and mulberry, bittersweet in the crowns, "
            "bracken, toadflax, fleabane and ryegrass, arrow arum and club-rush in the swamps.", {
        "acer_rubrum": C, "quercus_robur": O, "ginko_biloba": O, "morus_nigra": O, "robinia_pseudoacacia": O,
        "litchi_chinensis": R, "aesculus_hippocastanum": R,
        "pteridium_aquilinum": C, "buddleja_davidii": O, "philadelphus_coronarius": O, "ptisana_howeana": R, "agave_americana": R,
        "lolium_perenne": C, "nuttallanthus_canadensis": C, "erigeron_annuus": C, "plantago_major": C,
        "symphyotrichum_novaeangliae": O, "cichorium_intybus": O, "lysimachia_arvensis": O, "torilis_arvensis": O,
        "cirsium_arvense": R, "eupatorium_macrocephalum": R, "praxelis_clematidea": R,
        "peltandra_virginica": C, "scirpus_sylvaticus": C, "nymphaea_alba": O, "cyperus_polystachyos": O,
        "palhinhaea_cernua": R, "celastrus_orbiculatus": O, "lecanora_muralis": R,
    }),
    "Cfb": ("Oak and birch woods with bracken under them, fir and a redwood here and there, ryegrass meadow with "
            "its herbs between the woods, club-rush on soaked ground and water lily on still water.", {
        "quercus_robur": C, "quercus_petraea": O, "betula_pendula": O, "abies_nordmanniana": O,
        "aesculus_hippocastanum": R, "sequoia_sempervirens": R, "acacia_dealbata": R, "pinus_sylvestris": R,
        "robinia_pseudoacacia": R, "ginko_biloba": R, "oldeania_alpina": R, "pinus_strobus": R,
        "pteridium_aquilinum": C, "philadelphus_coronarius": O, "buddleja_davidii": O, "rosa_woodsii": R,
        "lolium_perenne": D, "plantago_major": C, "euphorbia_dulcis": O, "cichorium_intybus": O,
        "cirsium_arvense": O, "lysimachia_arvensis": O, "erigeron_annuus": O, "torilis_arvensis": R,
        "nuttallanthus_canadensis": R, "symphyotrichum_novaeangliae": R, "empetrum_nigrum": R,
        "scirpus_sylvaticus": D, "nymphaea_alba": C, "peltandra_virginica": R,
        "celastrus_orbiculatus": R, "lecanora_muralis": O,
    }),
    "Cfc": ("Subpolar coast: birch and pine in shelter, crowberry heath, mountain sorrel, club-rush bog, rock "
            "lichens.", {
        "betula_pendula": C, "pinus_sylvestris": O, "pinus_strobus": R, "acer_rubrum": R,
        "rosa_woodsii": O, "pteridium_aquilinum": O,
        "empetrum_nigrum": C, "oxyria_digyna": O, "plantago_major": C, "cirsium_arvense": O,
        "symphyotrichum_novaeangliae": O, "erigeron_annuus": R, "scirpus_sylvaticus": D,
        "rusavskia_elegans": C, "stereocaulon_vesuvianum": C, "lecanora_muralis": O,
    }),
    "Dsa": ("Summer-dry continental with hot summers: open oak and mulberry, wild rose, nitre bush on salt, "
            "chicory, thistle and plantain, club-rush at water.", {
        "quercus_robur": O, "morus_nigra": O, "robinia_pseudoacacia": R, "pinus_sylvestris": R,
        "rosa_woodsii": O, "buddleja_davidii": R, "philadelphus_coronarius": R, "pteridium_aquilinum": R,
        "nitraria_sibirica": O, "cichorium_intybus": C, "cirsium_arvense": C, "plantago_major": C,
        "lysimachia_arvensis": O, "torilis_arvensis": O, "lolium_perenne": O,
        "scirpus_sylvaticus": C, "nymphaea_alba": R, "lecanora_muralis": O, "rusavskia_elegans": O,
    }),
    "Dsb": ("Summer-dry mountains: pine woods with oak and birch, wild rose and bracken, thistle, plantain and "
            "ryegrass, club-rush at water.", {
        "pinus_sylvestris": C, "quercus_robur": O, "betula_pendula": O, "pinus_strobus": R,
        "rosa_woodsii": C, "pteridium_aquilinum": O, "philadelphus_coronarius": R,
        "cirsium_arvense": C, "plantago_major": C, "cichorium_intybus": O, "lolium_perenne": O,
        "symphyotrichum_novaeangliae": R, "erigeron_annuus": R, "nitraria_sibirica": R, "empetrum_nigrum": R,
        "scirpus_sylvaticus": C, "nymphaea_alba": R, "lecanora_muralis": O, "rusavskia_elegans": O,
    }),
    "Dsc": ("Summer-dry subarctic: pine and birch, crowberry heath, rock lichens, club-rush on wet ground.", {
        "pinus_sylvestris": C, "betula_pendula": O, "rosa_woodsii": O, "pteridium_aquilinum": R,
        "empetrum_nigrum": C, "cirsium_arvense": O, "plantago_major": O, "symphyotrichum_novaeangliae": R,
        "scirpus_sylvaticus": C,
        "rusavskia_elegans": C, "stereocaulon_vesuvianum": C, "lecanora_muralis": O,
    }),
    "Dsd": ("The coldest winters: crowberry and rock lichens. The catalogue has no tree that bears "
            "them.", {
        "empetrum_nigrum": C, "rusavskia_elegans": C, "stereocaulon_vesuvianum": C,
    }),
    "Dwa": ("Monsoon continental with hot summers: oak and mulberry with bittersweet in the crowns, wild rose and "
            "bracken, thistle, plantain, fleabane and aster, club-rush at water.", {
        "quercus_robur": O, "morus_nigra": O, "ginko_biloba": R, "robinia_pseudoacacia": R, "pinus_sylvestris": R,
        "celastrus_orbiculatus": O, "rosa_woodsii": O, "buddleja_davidii": R, "pteridium_aquilinum": O,
        "cirsium_arvense": C, "plantago_major": C, "cichorium_intybus": O, "erigeron_annuus": O,
        "symphyotrichum_novaeangliae": O, "lysimachia_arvensis": R, "lolium_perenne": R, "nitraria_sibirica": R,
        "scirpus_sylvaticus": C, "nymphaea_alba": R, "peltandra_virginica": R, "lecanora_muralis": O, "rusavskia_elegans": O,
    }),
    "Dwb": ("Monsoon continental with warm summers: pine and birch woods, an oak here and there, bittersweet, wild "
            "rose and bracken, thistle, plantain and aster, club-rush on wet ground.", {
        "pinus_sylvestris": C, "betula_pendula": C, "quercus_robur": R,
        "celastrus_orbiculatus": O, "rosa_woodsii": O, "pteridium_aquilinum": O,
        "cirsium_arvense": C, "plantago_major": C, "symphyotrichum_novaeangliae": O, "erigeron_annuus": O,
        "empetrum_nigrum": R, "scirpus_sylvaticus": D, "nymphaea_alba": R,
        "lecanora_muralis": O, "rusavskia_elegans": O, "stereocaulon_vesuvianum": O,
    }),
    "Dwc": ("Winter-dry subarctic: pine and birch, crowberry heath, rock lichens, club-rush on wet ground.", {
        "pinus_sylvestris": C, "betula_pendula": C, "rosa_woodsii": O, "pteridium_aquilinum": R,
        "empetrum_nigrum": C, "cirsium_arvense": O, "plantago_major": O,
        "scirpus_sylvaticus": C, "rusavskia_elegans": C, "stereocaulon_vesuvianum": C, "lecanora_muralis": O,
    }),
    "Dwd": ("The coldest winters: crowberry and rock lichens. The catalogue has no tree that bears "
            "them.", {
        "empetrum_nigrum": C, "rusavskia_elegans": C, "stereocaulon_vesuvianum": C,
    }),
    "Dfa": ("Continental woodland with hot summers: oak with red maple, black locust and white pine, bittersweet, "
            "mock-orange and bracken, aster, fleabane and ryegrass meadow, arrow arum and water lily.", {
        "quercus_robur": C, "acer_rubrum": O, "robinia_pseudoacacia": O, "pinus_strobus": O,
        "ginko_biloba": R, "morus_nigra": R, "aesculus_hippocastanum": R,
        "celastrus_orbiculatus": O, "philadelphus_coronarius": O, "rosa_woodsii": O, "buddleja_davidii": R,
        "pteridium_aquilinum": C,
        "lolium_perenne": C, "symphyotrichum_novaeangliae": C, "erigeron_annuus": C, "plantago_major": C,
        "nuttallanthus_canadensis": O, "cichorium_intybus": O, "cirsium_arvense": O, "lysimachia_arvensis": R,
        "torilis_arvensis": R, "euphorbia_dulcis": R,
        "peltandra_virginica": O, "scirpus_sylvaticus": C, "nymphaea_alba": O, "lecanora_muralis": O,
    }),
    "Dfb": ("Mixed woodland of cold winters: white pine, red maple and birch with oak and Scots pine, bracken, aster "
            "and ryegrass meadow, club-rush and arrow arum on wet ground.", {
        "pinus_strobus": C, "acer_rubrum": C, "betula_pendula": C, "pinus_sylvestris": O, "quercus_robur": O,
        "abies_nordmanniana": R, "aesculus_hippocastanum": R,
        "celastrus_orbiculatus": R, "rosa_woodsii": O, "philadelphus_coronarius": R, "pteridium_aquilinum": C,
        "lolium_perenne": C, "symphyotrichum_novaeangliae": C, "cirsium_arvense": C, "plantago_major": C,
        "erigeron_annuus": O, "cichorium_intybus": O, "euphorbia_dulcis": R, "empetrum_nigrum": R,
        "scirpus_sylvaticus": D, "peltandra_virginica": O, "nymphaea_alba": O,
        "lecanora_muralis": O, "rusavskia_elegans": O, "stereocaulon_vesuvianum": O,
    }),
    "Dfc": ("Taiga: pine and birch over crowberry, wild rose, club-rush bog, rock lichens.", {
        "pinus_sylvestris": C, "betula_pendula": C, "pinus_strobus": R, "acer_rubrum": R,
        "rosa_woodsii": O, "pteridium_aquilinum": R,
        "empetrum_nigrum": D, "cirsium_arvense": O, "plantago_major": O, "symphyotrichum_novaeangliae": R,
        "erigeron_annuus": R, "scirpus_sylvaticus": D,
        "rusavskia_elegans": C, "stereocaulon_vesuvianum": C, "lecanora_muralis": O,
    }),
    "Dfd": ("The coldest winters: crowberry and rock lichens. The catalogue has no tree that bears "
            "them.", {
        "empetrum_nigrum": C, "rusavskia_elegans": C, "stereocaulon_vesuvianum": C,
    }),
    "ET": ("Tundra: crowberry heath and mountain sorrel, rock lichens.", {
        "empetrum_nigrum": D, "oxyria_digyna": C, "rusavskia_elegans": C, "stereocaulon_vesuvianum": C,
    }),
    "EF": ("Ice: rock lichens where rock shows, which the Biosphere's limits do not let grow either.", {
        "rusavskia_elegans": R, "stereocaulon_vesuvianum": R,
    }),
}

# Plants in no collection, and why.
LEFT_OUT = {
    "biomasser_13b": "engineered: brought in by play, part of no wild flora",
    "diospyros_whitei": "which wild range the name stands for is not settled on its card",
}


def collection_id(zone):
    return f"{COLLECTION_PREFIX}{zone.lower()}"


def zone_of(collection):
    return {collection_id(zone): zone for zone in ZONE_COLLECTIONS}.get(collection)


def rarities_of(zone):
    return {f"spec_{name}": rarity for name, rarity in ZONE_COLLECTIONS[zone][1].items()}


def build_collections(datasets):
    """Every zone's collection as an upsert on top of what the store holds of it."""
    from simulations.biosphere.flora import plant_collection
    from simulations.world_gen.water_cycle import KOPPEN_CLASSES
    from tools.author_biome_flora_model import _by_id, _plain

    species, stored = _by_id(datasets, "species"), _by_id(datasets, "biospheres")
    upserts = []
    for zone, (description, _plants) in ZONE_COLLECTIONS.items():
        rarities = rarities_of(zone)
        missing = sorted(set(rarities) - set(species))
        if missing:
            raise RuntimeError(f"{zone}: species not in the ontology: {missing}")
        label = KOPPEN_CLASSES[zone]["label"]
        entity = _plain(stored[collection_id(zone)]) if collection_id(zone) in stored else {}
        entity.update(plant_collection(
            collection_id(zone), f"{label} Flora ({zone})", rarities,
            f"A plant collection for the {label} climate ({zone}), from the plants in the catalogue: {description} "
            "Its plants of dry, ordinary and wet ground and of open water are in the one list; the ground sorts them. "
            "Assign it to a biome's flora to have its species present there at these rarities.",
        ))
        entity["koppen_zone"] = zone
        entity.setdefault("entry_status", "draft")
        upserts.append(entity)
    return upserts


def check(datasets):
    """Every plant of every collection against its zone, and the plants of the catalogue in none."""
    import numpy as np

    from simulations.biosphere.ecology import THERMAL_ZONES, profile_from_entity, thermal_response
    from tools.author_biome_flora_model import _by_id, _plain

    species = {key: _plain(value) for key, value in _by_id(datasets, "species").items() if value.get("plant_growth_form")}
    findings = 0
    used = set()
    for zone, (_description, _plants) in ZONE_COLLECTIONS.items():
        points, classes = ZONE_CLIMATES[zone]
        rarities = rarities_of(zone)
        used |= set(rarities)
        notes = []
        for species_id in rarities:
            entity = species.get(species_id)
            if entity is None:
                notes.append(f"{species_id}: not a plant in the ontology")
                continue
            profile = profile_from_entity(entity)
            scores = [thermal_response(profile, {"coldest_month_temperature_k": cold + 273.15,
                                                 "warmest_month_temperature_k": warm + 273.15})[0] for cold, warm in points]
            ends = [str(entity.get(key) or "") for key in ("thermal_range_coldest", "thermal_range_warmest")]
            if all(end in THERMAL_ZONES for end in ends):
                low, high = sorted(THERMAL_ZONES.index(end) for end in ends)
                if not any(low <= THERMAL_ZONES.index(name) <= high for name in classes):
                    notes.append(f"{species_id[5:]} ({ends[0]} to {ends[1]}) grows wild in none of the zone's climates {classes}")
            if zone != "EF" and float(np.mean(scores)) < 0.34:
                notes.append(f"{species_id[5:]}: the Biosphere's limits give it {np.mean(scores):.2f} over the zone's winters and summers")
        by_rarity = {rarity: sum(1 for value in rarities.values() if value == rarity) for rarity in (D, C, O, R)}
        print(f"{zone:4s} {len(rarities):2d} plants ({', '.join(f'{count} {name}' for name, count in by_rarity.items() if count)})"
              + ("" if not notes else "\n     " + "\n     ".join(notes)))
        findings += len(notes)
    unused = sorted(set(species) - used)
    print(f"plants of the catalogue in no collection: {[name[5:] for name in unused]}")
    for name in unused:
        if name[5:] not in LEFT_OUT:
            print(f"     {name[5:]} is left out without a reason given")
            findings += 1
    return findings


def build_assignment(datasets, region_id):
    """The floras of a region's biomes, each set by its own zone's collection, as upserts; and a report."""
    from simulations.biosphere.flora import COLLECTION_ROLE, BiomeFlora
    from tools.author_biome_flora_model import _by_id, _plain, region_biomes

    locations, stored = _by_id(datasets, "locations"), _by_id(datasets, "biospheres")
    if region_id not in locations:
        raise RuntimeError(f"no location {region_id}")
    region = _plain(locations[region_id])
    planet_id = region.get("refinement_root_planet_id") or region.get("terrain_root_planet_id")
    if not planet_id or planet_id not in locations:
        raise RuntimeError(f"{region_id} is not a refined region of a planet")
    planet = locations[planet_id]
    upserts, report = [], []
    for biome, share in region_biomes(region):
        chosen = stored.get(collection_id(biome.climate)) if biome.climate in ZONE_COLLECTIONS else None
        if chosen is None or chosen.get("collection_role") != COLLECTION_ROLE:
            report.append((biome, share, None, None))
            continue
        flora = BiomeFlora(str(planet_id), biome)
        existing = _plain(stored[flora.entity_id]) if flora.entity_id in stored else None
        if existing is not None:
            flora = BiomeFlora.from_entity(existing)
        flora.assign_collection(_plain(chosen))
        entity = flora.to_entity(existing, planet.get("pretty_name") or planet.get("name"))
        entity.setdefault("entry_status", "draft")
        upserts.append(entity)
        report.append((biome, share, chosen["id"], flora))
    return upserts, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write (default: show what would be written)")
    parser.add_argument("--export-checkpoint", action="store_true", help="also export ontology/index0.owl after writing")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("check", help="every plant against its zones, and the plants in no collection")
    assign = commands.add_parser("assign", help="set the floras of a region's biomes, each by its zone's collection")
    assign.add_argument("--region", required=True, help="id of a refined region; its ground shows which biomes there are")
    assign.add_argument("--apply", action="store_true", dest="assign_apply", help="write the floras")
    args = parser.parse_args(argv)
    apply = args.apply or getattr(args, "assign_apply", False)

    from tools.author_biome_flora_model import ONTOLOGY_PATH, _write
    from tools.ontology_backup import other_python_processes
    from world.persistent_ontology_store import PersistentOntologyStore

    if apply:
        others = other_python_processes()
        if others:
            raise SystemExit(f"not writing: other Python processes are running: {others}")
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    if args.command == "check":
        return 1 if check(datasets) else 0
    if args.command == "assign":
        upserts, report = build_assignment(datasets, args.region)
        for biome, share, chosen, flora in report:
            told = f"<- {chosen}  ({len(flora.records)} plants)" if chosen else "no collection for its zone in the store: left as it is"
            print(f"  {share:6.1%}  {biome.key:26s} {biome.label:42s} {told}")
    else:
        upserts = build_collections(datasets)
        for entity in upserts:
            records = entity["plant_records"]
            print(f"{entity['id']}: {entity['name']}, {len(records)} plants: "
                  + ", ".join(f"{record['species'][5:]} ({record['rarity'][0]})" for record in records))
    if not apply or not upserts:
        print("nothing written" + ("" if upserts else ": nothing to write"))
        return 0
    _write(store, upserts, args.export_checkpoint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
