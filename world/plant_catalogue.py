"""Disposable Plantae ancestry index built from ontology phylogeny edges."""
from collections import defaultdict, deque
from dataclasses import dataclass


PLANTAE_ID = "cladis_plants_plantae"


@dataclass(frozen=True)
class PlantCatalogue:
    entity_ids: frozenset
    species_ids: frozenset
    root_id: str = PLANTAE_ID

    def contains(self, entity_id):
        return entity_id in self.entity_ids

    def is_species(self, entity_id):
        return entity_id in self.species_ids

    @classmethod
    def build(cls, entities, root_id=PLANTAE_ID):
        # Only taxonomic nodes participate. An illustration attached to a
        # plant card is not a descendant taxon.
        taxa = {eid: e for eid,e in entities.items() if isinstance(e,dict)
                and (e.get("type") in {"species","cladistics"} or e.get("_dataset") in {"species","cladistics"})}
        children = defaultdict(list)
        for eid,entity in taxa.items():
            parents = entity.get("parents") or []
            if isinstance(parents,str):
                parents = [parents]
            for parent in parents:
                parent_id = parent.get("id") if isinstance(parent,dict) else parent
                if isinstance(parent_id,str) and parent_id in taxa:
                    children[parent_id].append(eid)
        seen = set()
        pending = deque([root_id] if root_id in taxa else [])
        while pending:
            eid = pending.popleft()
            if eid in seen:
                continue
            seen.add(eid)
            pending.extend(children[eid])
        species = {eid for eid in seen if taxa[eid].get("type") == "species" or taxa[eid].get("_dataset") == "species"}
        return cls(frozenset(seen),frozenset(species),root_id)
