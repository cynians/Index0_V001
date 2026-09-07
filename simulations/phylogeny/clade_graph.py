import re
from collections import deque


def relation_ids(value):
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    if isinstance(value, dict):
        entity_id = str(value.get("id") or "").strip()
        return [entity_id] if entity_id else []
    if isinstance(value, (list, tuple, set)):
        ids = []
        for item in value:
            ids.extend(relation_ids(item))
        deduped = []
        for entity_id in ids:
            if entity_id and entity_id not in deduped:
                deduped.append(entity_id)
        return deduped
    return []


def clade_label(entity, fallback=None):
    if not isinstance(entity, dict):
        return str(fallback or "Unknown")
    if is_species_entity(entity):
        common_name = str(entity.get("common_name") or "").strip()
        binomial_name = str(entity.get("binomial_name") or "").strip()
        if common_name and binomial_name:
            return f"{common_name} - {binomial_name}"
        if common_name or binomial_name:
            return common_name or binomial_name
    return str(
        entity.get("pretty_name")
        or entity.get("name")
        or entity.get("common_name")
        or entity.get("binomial_name")
        or fallback
        or entity.get("id")
        or "Unknown"
    )


def is_clade_entity(entity):
    if not isinstance(entity, dict):
        return False
    return entity.get("_dataset") == "cladistics" or entity.get("type") == "cladistics"


def is_species_entity(entity):
    if not isinstance(entity, dict):
        return False
    return entity.get("_dataset") == "species" or entity.get("type") == "species"


def is_phylogeny_entity(entity):
    return is_clade_entity(entity) or is_species_entity(entity)


def get_clade_entities(world_model):
    loader = getattr(world_model, "loader", None) if world_model is not None else None
    entities = getattr(loader, "entities", {}) if loader is not None else {}
    return {
        entity_id: entity
        for entity_id, entity in entities.items()
        if is_clade_entity(entity)
    }


def get_phylogeny_entities(world_model):
    loader = getattr(world_model, "loader", None) if world_model is not None else None
    entities = getattr(loader, "entities", {}) if loader is not None else {}
    return {
        entity_id: entity
        for entity_id, entity in entities.items()
        if is_phylogeny_entity(entity)
    }


def clade_parent_ids(entity):
    return relation_ids((entity or {}).get("parents"))


def clade_child_ids(entity):
    return relation_ids((entity or {}).get("offspring"))


def _entity_signature_piece(entity_id, entity):
    return (
        entity_id,
        entity.get("_dataset"),
        entity.get("type"),
        tuple(clade_parent_ids(entity)),
        tuple(clade_child_ids(entity)),
        entity.get("pretty_name"),
        entity.get("name"),
        entity.get("common_name"),
        entity.get("binomial_name"),
    )


def _phylogeny_cache_signature(world_model):
    loader = getattr(world_model, "loader", None) if world_model is not None else None
    entities = getattr(loader, "entities", {}) if loader is not None else {}
    return tuple(
        _entity_signature_piece(entity_id, entity)
        for entity_id, entity in sorted(entities.items())
        if is_phylogeny_entity(entity)
    )


class PhylogenyGraphContext:
    def __init__(self, world_model, signature=None):
        self.world_model = world_model
        self.signature = signature
        self.phylogeny_entities = get_phylogeny_entities(world_model)
        self.clades = {
            entity_id: entity
            for entity_id, entity in self.phylogeny_entities.items()
            if is_clade_entity(entity)
        }
        self.children_by_parent = self._build_children_map()
        self.parents_by_child = self._build_parent_map()
        self._descendant_species_cache = {}
        self._distance_cache = {}
        self._clade_search_rows = None
        self._clade_search_cache = {}

    def find_clade_matches(self, query, limit=6):
        query = str(query or "").strip().lower()
        if not query:
            return []
        cache_key = (query, int(limit))
        cached = self._clade_search_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        if self._clade_search_rows is None:
            rows = []
            for entity_id, entity in self.clades.items():
                haystack = " ".join(
                    str(value or "")
                    for value in (
                        entity_id,
                        entity.get("pretty_name"),
                        entity.get("name"),
                        entity.get("common_name"),
                        entity.get("binomial_name"),
                    )
                ).lower()
                rows.append((clade_label(entity, entity_id).lower(), haystack, entity))
            rows.sort(key=lambda row: row[0])
            self._clade_search_rows = rows

        query_terms = tuple(term for term in query.split() if term)
        matches = [
            entity
            for _label, haystack, entity in self._clade_search_rows
            if all(term in haystack for term in query_terms)
        ][:limit]
        self._clade_search_cache[cache_key] = tuple(matches)
        return list(matches)

    def _build_children_map(self):
        children_by_parent = {entity_id: [] for entity_id in self.clades}
        for parent_id, entity in self.clades.items():
            for child_id in clade_child_ids(entity):
                if child_id in self.phylogeny_entities and child_id not in children_by_parent.setdefault(parent_id, []):
                    children_by_parent[parent_id].append(child_id)
        for entity_id, entity in self.phylogeny_entities.items():
            for parent_id in clade_parent_ids(entity):
                if parent_id in self.clades and entity_id not in children_by_parent.setdefault(parent_id, []):
                    children_by_parent[parent_id].append(entity_id)
        for children in children_by_parent.values():
            children.sort(key=lambda child_id: clade_label(self.phylogeny_entities.get(child_id), child_id).lower())
        return children_by_parent

    def _build_parent_map(self):
        parents_by_child = {entity_id: [] for entity_id in self.phylogeny_entities}
        for entity_id, entity in self.phylogeny_entities.items():
            for parent_id in clade_parent_ids(entity):
                if parent_id in self.phylogeny_entities and parent_id not in parents_by_child.setdefault(entity_id, []):
                    parents_by_child[entity_id].append(parent_id)
        for parent_id, child_ids in self.children_by_parent.items():
            for child_id in child_ids:
                if child_id in self.phylogeny_entities and parent_id not in parents_by_child.setdefault(child_id, []):
                    parents_by_child[child_id].append(parent_id)
        return parents_by_child

    def ancestor_chain(self, entity_id, limit=24):
        chain = []
        current_id = entity_id
        seen = set()
        while current_id and current_id not in seen and len(chain) < limit:
            seen.add(current_id)
            entity = self.phylogeny_entities.get(current_id)
            if not entity:
                break
            chain.append(current_id)
            parents = [parent_id for parent_id in self.parents_by_child.get(current_id, []) if parent_id in self.clades]
            current_id = parents[0] if parents else None
        chain.reverse()
        return chain

    def context_tree(self, entity_id, child_limit=8):
        chain = self.ancestor_chain(entity_id)
        if not chain and entity_id in self.phylogeny_entities:
            chain = [entity_id]

        root = None
        current_node = None
        for chain_id in chain:
            entity = self.phylogeny_entities.get(chain_id)
            node = {
                "id": chain_id,
                "label": clade_label(entity, chain_id),
                "highlight": chain_id == entity_id,
                "species": is_species_entity(entity),
                "children": [],
            }
            if root is None:
                root = node
            if current_node is not None:
                current_node["children"].append(node)
            current_node = node

        if current_node is not None:
            for child_id in self.children_by_parent.get(entity_id, [])[:child_limit]:
                child = self.phylogeny_entities.get(child_id)
                current_node["children"].append(
                    {
                        "id": child_id,
                        "label": clade_label(child, child_id),
                        "highlight": False,
                        "species": is_species_entity(child),
                        "children": [],
                    }
                )
        return root

    def species_descendant_ids(self, entity_id):
        if entity_id in self._descendant_species_cache:
            return list(self._descendant_species_cache[entity_id])

        descendants = []
        seen = set()

        def walk(current_id):
            for child_id in self.children_by_parent.get(current_id, []):
                if child_id in seen:
                    continue
                seen.add(child_id)
                child = self.phylogeny_entities.get(child_id)
                if is_species_entity(child):
                    descendants.append(child_id)
                    continue
                walk(child_id)

        walk(entity_id)
        self._descendant_species_cache[entity_id] = tuple(descendants)
        return descendants

    def graph_distance(self, start_id, target_id, max_depth=8):
        cache_key = (start_id, target_id, max_depth)
        if cache_key in self._distance_cache:
            return self._distance_cache[cache_key]

        if start_id == target_id:
            self._distance_cache[cache_key] = 0
            return 0

        queue = deque([(start_id, 0)])
        seen = {start_id}
        while queue:
            current_id, distance = queue.popleft()
            if distance >= max_depth:
                continue
            neighbors = list(self.parents_by_child.get(current_id, [])) + list(self.children_by_parent.get(current_id, []))
            for neighbor_id in neighbors:
                if neighbor_id not in self.phylogeny_entities or neighbor_id in seen:
                    continue
                if neighbor_id == target_id:
                    self._distance_cache[cache_key] = distance + 1
                    return distance + 1
                seen.add(neighbor_id)
                queue.append((neighbor_id, distance + 1))

        self._distance_cache[cache_key] = None
        return None

    def distant_species_members(self, clade_id, limit=3):
        candidates = []
        for species_id in self.species_descendant_ids(clade_id):
            distance = self.graph_distance(clade_id, species_id, max_depth=64)
            candidates.append(
                (
                    distance if distance is not None else 0,
                    clade_label(self.phylogeny_entities.get(species_id), species_id).lower(),
                    species_id,
                )
            )
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [species_id for _distance, _label, species_id in candidates[:limit]]

    def closest_species_relatives(self, species_id, limit=4):
        species = self.phylogeny_entities.get(species_id)
        if not is_species_entity(species):
            return []

        relatives = []
        seen = {species_id}
        parent_ids = [parent_id for parent_id in self.parents_by_child.get(species_id, []) if parent_id in self.phylogeny_entities]
        ancestor_id = parent_ids[0] if parent_ids else None

        level = 0
        while ancestor_id and len(relatives) < limit:
            level += 1
            candidates = []
            for candidate_id in self.species_descendant_ids(ancestor_id):
                if candidate_id in seen:
                    continue
                distance = self.graph_distance(species_id, candidate_id, max_depth=64)
                candidates.append(
                    (
                        distance if distance is not None else 9999,
                        level,
                        clade_label(self.phylogeny_entities.get(candidate_id), candidate_id).lower(),
                        candidate_id,
                    )
                )
            candidates.sort()
            for _distance, _level, _label, candidate_id in candidates:
                if candidate_id in seen:
                    continue
                seen.add(candidate_id)
                relatives.append(candidate_id)
                if len(relatives) >= limit:
                    break

            parent_ids = [parent_id for parent_id in self.parents_by_child.get(ancestor_id, []) if parent_id in self.phylogeny_entities]
            ancestor_id = parent_ids[0] if parent_ids else None

        return relatives[:limit]


def phylogeny_graph_context(world_model):
    signature = _phylogeny_cache_signature(world_model)
    cached = getattr(world_model, "_phylogeny_graph_context_cache", None) if world_model is not None else None
    if cached is not None and getattr(cached, "signature", None) == signature:
        return cached
    context = PhylogenyGraphContext(world_model, signature=signature)
    if world_model is not None:
        setattr(world_model, "_phylogeny_graph_context_cache", context)
    return context


def build_clade_children_map(world_model):
    return phylogeny_graph_context(world_model).children_by_parent


def build_phylogeny_parent_map(world_model):
    return phylogeny_graph_context(world_model).parents_by_child


def species_descendant_ids(world_model, entity_id):
    return phylogeny_graph_context(world_model).species_descendant_ids(entity_id)


def distant_species_members(world_model, clade_id, limit=3):
    return phylogeny_graph_context(world_model).distant_species_members(clade_id, limit=limit)


def closest_species_relatives(world_model, species_id, limit=4):
    return phylogeny_graph_context(world_model).closest_species_relatives(species_id, limit=limit)


def all_clade_tree_roots(world_model):
    phylogeny_entities = get_phylogeny_entities(world_model)
    parents_by_child = build_phylogeny_parent_map(world_model)
    roots = []
    for entity_id, entity in phylogeny_entities.items():
        if not any(parent_id in phylogeny_entities for parent_id in parents_by_child.get(entity_id, [])):
            roots.append(entity_id)
    roots.sort(
        key=lambda entity_id: (
            1 if is_species_entity(phylogeny_entities.get(entity_id)) else 0,
            clade_label(phylogeny_entities.get(entity_id), entity_id).lower(),
        )
    )
    return roots


def find_clade_matches(world_model, query, limit=6):
    if world_model is None:
        return []
    return phylogeny_graph_context(world_model).find_clade_matches(query, limit=limit)


def clade_id_from_name(name):
    slug = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")
    return f"cladis_{slug}" if slug else ""


def graph_distance(world_model, start_id, target_id, max_depth=8):
    return phylogeny_graph_context(world_model).graph_distance(start_id, target_id, max_depth=max_depth)
