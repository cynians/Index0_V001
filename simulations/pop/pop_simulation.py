"""Population composition view: a launchable simulation over one pop entity.

A pop is one of three types (see tools/author_pop_system_model.py):
- location: total residents of a place -- population_count is authored
  ground truth.
- cultural: a cultural subdivision of a location's population -- also
  authored ground truth.
- employment: a labeled recruitment cut of one or more source pops
  (source_allocations: [{source_pop, count}]). An employment pop never adds
  population; its own population_count is *derived* (summed from
  source_allocations) so a person recruited into it is never implied to
  exist twice -- they were already counted in their source pop.

This is deliberately a static composition resolver, not a time-evolving
simulation: population/composition dynamics (births, deaths, migration,
employment turnover) are a documented future layer -- see growth_rate_stub
on the pop schema and update() below, which is an inert placeholder for now,
the same pattern as PersonSimulation.habits.
"""

import math


class PopSimulation:
    render_mode = "pop"
    # A static composition view has no running clock -- opts out of
    # UIManager's generic time-strip rendering (see _rebuild_active_simulation_ui).
    show_time_ui = False

    def __init__(self, world_model, pop_entity_id, year=2400):
        self.world_model = world_model
        self.pop_entity_id = pop_entity_id
        self.year = int(year) if year is not None else 2400

    def get_pop(self, pop_entity_id=None):
        if self.world_model is None:
            return None
        return self.world_model.get_entity(pop_entity_id or self.pop_entity_id)

    def update(self, dt):
        """Placeholder for future pop dynamics (births/deaths/migration/
        employment turnover). Deliberately does nothing yet."""
        return

    @staticmethod
    def _display_label(entity, fallback):
        if not isinstance(entity, dict):
            return str(fallback)
        return str(entity.get("pretty_name") or entity.get("name") or fallback)

    def _all_pops(self):
        if self.world_model is None:
            return []
        return [
            entity for entity in (self.world_model.get_dataset("pops") or [])
            if isinstance(entity, dict)
        ]

    def derived_population_count(self, pop):
        """Sum of source_allocations when present (a recruitment-derived
        pop, regardless of pop_type label) -- otherwise the authored
        population_count. Never both: a pop with source_allocations is
        never also treated as adding its own independent headcount."""
        allocations = pop.get("source_allocations") or []
        if allocations:
            total = 0
            for allocation in allocations:
                if not isinstance(allocation, dict):
                    continue
                try:
                    total += max(0, int(allocation.get("count") or 0))
                except (TypeError, ValueError):
                    continue
            return total
        try:
            return max(0, int(pop.get("population_count") or 0))
        except (TypeError, ValueError):
            return 0

    def resolve_composition(self, pop=None):
        """One level of source_allocations, resolved to display labels and
        each source's fraction of this pop's total -- e.g. the "324 German
        factory workers, 100 interstellar workplain, 5 Shinto Buddhist
        monks" breakdown."""
        pop = pop if pop is not None else (self.get_pop() or {})
        allocations = pop.get("source_allocations") or []
        rows = []
        total = self.derived_population_count(pop)
        for allocation in allocations:
            if not isinstance(allocation, dict):
                continue
            source_id = str(allocation.get("source_pop") or "").strip()
            if not source_id:
                continue
            try:
                count = max(0, int(allocation.get("count") or 0))
            except (TypeError, ValueError):
                count = 0
            source_pop = self.get_pop(source_id) or {}
            rows.append({
                "source_pop_id": source_id,
                "label": self._display_label(source_pop, source_id),
                "count": count,
                "fraction": (count / total) if total else 0.0,
            })
        return rows

    def nested_children(self, pop_entity_id=None):
        """Pops whose parent_pop points at this one -- category nesting
        (e.g. Factory Workers -> Factory Workers at Factory X), independent
        of recruitment lineage."""
        target_id = pop_entity_id or self.pop_entity_id
        children = []
        for candidate in self._all_pops():
            if str(candidate.get("parent_pop") or "").strip() != target_id:
                continue
            children.append({
                "id": candidate.get("id"),
                "label": self._display_label(candidate, candidate.get("id")),
                "total_population": self.derived_population_count(candidate),
            })
        return children

    @staticmethod
    def _age_bucket_fractions(mean_age, stddev, min_age, max_age, buckets=8):
        """Normalized bell-curve bucket fractions across [min_age, max_age]
        for a simple bar-chart rendering of the age distribution."""
        if max_age <= min_age:
            return [1.0]
        if stddev <= 0:
            fractions = [0.0] * buckets
            span = max_age - min_age
            index = min(buckets - 1, max(0, int((mean_age - min_age) / span * buckets))) if span else 0
            fractions[index] = 1.0
            return fractions

        def cdf(x):
            return 0.5 * (1.0 + math.erf((x - mean_age) / (stddev * math.sqrt(2.0))))

        edges = [min_age + (max_age - min_age) * i / buckets for i in range(buckets + 1)]
        raw = [max(0.0, cdf(edges[i + 1]) - cdf(edges[i])) for i in range(buckets)]
        total = sum(raw)
        if total <= 0:
            return [1.0 / buckets] * buckets
        return [value / total for value in raw]

    def get_population_panel_model(self):
        pop = self.get_pop() or {}
        total = self.derived_population_count(pop)
        parent_pop_id = str(pop.get("parent_pop") or "").strip() or None
        parent_pop = self.get_pop(parent_pop_id) if parent_pop_id else None
        employer_id = str(pop.get("employer") or "").strip() or None
        employer = self.get_pop(employer_id) if employer_id else None
        # employer targets producers/institutions, not pops -- get_pop() is
        # just a generic get_entity() alias, safe to reuse here.

        age = pop.get("age_distribution") or {}
        try:
            mean_age = float(age.get("mean_age", 35))
            stddev = float(age.get("stddev", 15))
            min_age = float(age.get("min_age", 0))
            max_age = float(age.get("max_age", 90))
        except (TypeError, ValueError):
            mean_age, stddev, min_age, max_age = 35.0, 15.0, 0.0, 90.0
        bucket_fractions = self._age_bucket_fractions(mean_age, stddev, min_age, max_age)
        bucket_width = (max_age - min_age) / len(bucket_fractions) if max_age > min_age else 0.0
        age_buckets = [
            {
                "range_label": f"{int(min_age + bucket_width * i)}-{int(min_age + bucket_width * (i + 1))}",
                "count": round(total * fraction),
                "fraction": fraction,
            }
            for i, fraction in enumerate(bucket_fractions)
        ]

        return {
            "pop_name": self._display_label(pop, self.pop_entity_id),
            "pop_type": pop.get("pop_type") or "unspecified",
            "total_population": total,
            "is_derived_count": bool(pop.get("source_allocations")),
            "employer_label": self._display_label(employer, employer_id) if employer_id else None,
            "parent_pop": (
                {"id": parent_pop_id, "label": self._display_label(parent_pop, parent_pop_id)}
                if parent_pop_id else None
            ),
            "composition": self.resolve_composition(pop),
            "nested_children": self.nested_children(),
            "sex_ratio": pop.get("sex_ratio"),
            "age_distribution": {"mean_age": mean_age, "stddev": stddev, "min_age": min_age, "max_age": max_age},
            "age_buckets": age_buckets,
        }
