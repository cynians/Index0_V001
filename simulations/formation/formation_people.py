"""A formation's people: the ones saved, a few representatives and the crowd.

Owner, 2026-10-29: the people a fielded deck holds come from a cumulative
service pop (``fielding.py``) and stay a count until someone looks. The Deck
tab's People panel shows them by role: first the people saved as serving in
the formation, then up to ``REPRESENTATIVES`` runtime representatives, then
the rest as a crowd. A representative is drawn from a seed (formation, role,
place in the role), so the same name, sex, age and birth personality come
back each time. Nothing is stored until ``Save as person`` writes one person
(``serves_in``, ``service_role``, ``service_rank``, ``source_pop``,
``birth_seed``). A saved person is one of the formation's held people, not one
more.

What a pool could not give (the deck row's ``short`` people) is taken from
the roles that are not command first, in proportion to what each needs.
"""

import hashlib
import re

from simulations.person.person_editor import person_id_from_name
from simulations.person.person_genetics import SKIN_TONES, create_person_dna
from world.personality import AXES, personality


REPRESENTATIVES = 3
SERVICE_CLASS = "service member"
YOUNGEST, AGE_SPAN, COMMAND_YEARS = 19, 20, 8
# Placeholder names until pops or cultures carry their own; a pop's
# representative_names are used first.
GIVEN_NAMES = {
    "female": ("Ada", "Bea", "Cara", "Dana", "Elin", "Faye", "Greta", "Hana", "Ines", "Jana", "Kira", "Lena",
               "Mara", "Nadia", "Olga", "Petra", "Rosa", "Sara", "Tess", "Vera"),
    "male": ("Aron", "Boris", "Carl", "Dmitri", "Emil", "Felix", "Georg", "Hugo", "Ivan", "Jonas", "Karl", "Leon",
             "Marek", "Niko", "Oskar", "Pavel", "Rafael", "Stefan", "Tomas", "Viktor"),
}
FAMILY_NAMES = ("Adler", "Brandt", "Castell", "Dorn", "Engel", "Falk", "Graf", "Hale", "Iversen", "Jessup",
                "Kovac", "Lind", "Moreau", "Novak", "Okafor", "Petrov", "Quinn", "Reyes", "Sato", "Tanaka",
                "Ulrich", "Varga", "Weller", "Young", "Zeman")


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").casefold()).strip("_") or "role"


def _count(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 1


def _draw(seed, key):
    digest = hashlib.sha256(f"{seed}|{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2 ** 64)


def _share(total, needs):
    """``total`` split over ``needs`` in proportion, whole numbers, never more than a need."""
    total = min(total, sum(needs))
    whole = sum(needs)
    if not whole or not total:
        return [0] * len(needs)
    shares = [total * need // whole for need in needs]
    order = sorted(range(len(needs)), key=lambda index: -(total * needs[index] % whole))
    for index in order:
        if sum(shares) >= total:
            break
        if shares[index] < needs[index]:
            shares[index] += 1
    return shares


class FormationPeople:
    def __init__(self, deck):
        self.deck = deck
        self.sim = deck.sim

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------

    def _role_needs(self, formation_id):
        """People the deck needs by role: {key: {role, rank, is_command, need}} in first-seen order."""
        roles = {}

        def add(role, rank, is_command, count):
            role = str(role or "Personnel").strip() or "Personnel"
            row = roles.setdefault(role.casefold(), {"role": role, "rank": "", "is_command": False, "need": 0})
            row["rank"] = row["rank"] or str(rank or "").strip()
            row["is_command"] = row["is_command"] or bool(is_command)
            row["need"] += count

        short = 0
        for entry in self.deck.deck_entries(formation_id):
            card = self.deck.card(entry["card"])
            if card is None:
                continue
            copies = entry["count"]
            short += entry["short"].get("people", 0)
            for man in self.deck.manpower(card):
                add(man["role"], man.get("rank"), man.get("is_command"), copies * man["count"])
            for equipment in self.deck.equipment(card):
                for crew in self.deck.entry_crew(equipment):
                    if isinstance(crew, dict):
                        count = copies * equipment["count"] * _count(crew.get("count", 0))
                        add(crew.get("role") or "Crew", crew.get("rank"), crew.get("is_command"), count)
        return roles, short

    def saved_people(self, formation_id):
        return [
            person for person in self.deck._dataset("people")
            if formation_id in self.sim._relation_ids(person.get("serves_in"))
        ]

    def roster(self, formation_id):
        """By role, command first: [{role, rank, is_command, need, held, short, saved, representatives, crowd}]."""
        roles, short = self._role_needs(formation_id)
        rows = sorted(roles.values(), key=lambda row: (not row["is_command"], -row["need"], row["role"].casefold()))
        drawing = self.deck.fielding.draws(formation_id)
        if not drawing:
            short = sum(row["need"] for row in rows)
        others = [row for row in rows if not row["is_command"]]
        for row, cut in zip(others, _share(short, [row["need"] for row in others])):
            row["short"] = cut
        left = max(0, short - sum(row.get("short", 0) for row in others))
        commands = [row for row in rows if row["is_command"]]
        for row, cut in zip(commands, _share(left, [row["need"] for row in commands])):
            row["short"] = cut
        by_role = {}
        for person in self.saved_people(formation_id):
            role = str(person.get("service_role") or "Personnel")
            by_role.setdefault(role.casefold(), []).append(person)
        for key, people in by_role.items():
            if key not in roles:
                rows.append({"role": people[0].get("service_role") or "Personnel", "rank": "",
                             "is_command": False, "need": 0, "short": 0})
        pop_id = self.deck.fielding.manpower_pop_id(formation_id) if drawing else None
        for row in rows:
            row["held"] = max(0, row["need"] - row.get("short", 0))
            row["saved"] = by_role.get(row["role"].casefold(), [])
            unnamed = max(0, row["held"] - len(row["saved"]))
            row["representatives"] = self._representatives(formation_id, row, pop_id, min(REPRESENTATIVES, unnamed))
            row["crowd"] = unnamed - len(row["representatives"])
        return rows

    # ------------------------------------------------------------------
    # Representatives
    # ------------------------------------------------------------------

    def _names(self, pop_id):
        pop = self.deck._entity(pop_id)
        names = (pop or {}).get("representative_names") if isinstance(pop, dict) else None
        return [str(name) for name in names if str(name).strip()] if isinstance(names, (list, tuple)) else []

    def _representatives(self, formation_id, row, pop_id, count):
        used = {str(person.get("birth_seed") or "") for person in row["saved"]}
        names = self._names(pop_id)
        faction = self.deck.fielding.faction_id(formation_id)
        year = int(getattr(self.sim, "year", 2400) or 2400)
        people, place = [], 0
        while len(people) < count:
            place += 1
            seed = f"{formation_id}:{_slug(row['role'])}:{place}"
            if seed in used:
                continue
            sex = "female" if _draw(seed, "sex") < 0.5 else "male"
            if names:
                name = names[int(_draw(seed, "name") * len(names))]
            else:
                given = GIVEN_NAMES[sex]
                name = f"{given[int(_draw(seed, 'given') * len(given))]} " \
                       f"{FAMILY_NAMES[int(_draw(seed, 'family') * len(FAMILY_NAMES))]}"
            age = YOUNGEST + int(_draw(seed, "age") * AGE_SPAN) + (COMMAND_YEARS if row["is_command"] else 0)
            person = {
                "id": f"runtime_{formation_id}_{_slug(row['role'])}_{place}",
                "_dataset": "people", "type": "person",
                "name": name, "pretty_name": name, "sex": sex,
                "start_year": year - age, "birth_seed": seed,
                "person_class": SERVICE_CLASS,
                "serves_in": formation_id, "service_role": row["role"],
            }
            if row["rank"]:
                person["service_rank"] = row["rank"]
            if pop_id:
                person["source_pop"] = pop_id
            if faction:
                person["affiliated_factions"] = [faction]
            people.append(person)
        return people

    def find(self, formation_id, person_id):
        """A representative or a saved person of the formation by id."""
        for row in self.roster(formation_id):
            for person in row["representatives"] + row["saved"]:
                if person.get("id") == person_id:
                    return person, row
        return None, None

    @staticmethod
    def leanings(person):
        """The one or two Big Five axes the person's birth puts furthest from the middle."""
        values = personality(person, index={})
        ranked = sorted(AXES, key=lambda axis: -abs(values[axis].value - 0.5))
        return [(axis, values[axis].value) for axis in ranked[:2] if abs(values[axis].value - 0.5) >= 0.08]

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def _taken_ids(self):
        entities = getattr(getattr(self.sim.world_model, "loader", None), "entities", None)
        if isinstance(entities, dict):
            return set(entities)
        return {person["id"] for person in self.deck._dataset("people")}

    def save(self, formation_id, representative_id):
        """Write the representative as a person serving in the formation. Returns the new id, or None."""
        person, row = self.find(formation_id, representative_id)
        if person is None or not str(person.get("id", "")).startswith("runtime_"):
            return None
        person = dict(person)
        name = person["name"]
        person["id"] = person_id_from_name(name, self._taken_ids())
        tone = SKIN_TONES[int(_draw(person["birth_seed"], "skin") * len(SKIN_TONES))]["id"]
        person["genetic_dna"] = create_person_dna(person["birth_seed"], tone)
        person["entry_status"] = "draft"
        rank = f"{person['service_rank']} " if person.get("service_rank") else ""
        source = f", drawn from {self.deck.fielding.label(person['source_pop'])}" if person.get("source_pop") else ""
        person["wiki_entry"] = (f"{rank}{row['role']} in {self.deck.formation_label(formation_id)}{source}. "
                                "Saved from the formation's people.")
        loader = getattr(self.sim.world_model, "loader", None)
        if loader is None or not loader.persist_entity(person):
            return None
        if hasattr(self.sim.world_model, "mark_repository_changed"):
            self.sim.world_model.mark_repository_changed([person["id"]])
        return person["id"]
