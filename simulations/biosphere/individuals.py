"""Recorded plants: the individuals a stand is made of.

A stand of a species kept as individuals is no longer an area with a density:
it is the plants in it, each with a place, an age and the kept individual it
looks like.  The stand's disc is where they may stand; its cover is how many
of them there are.

A record usually is one plant.  When a species has spread so far that its
plants no longer fit the register, a record comes to stand for two, four or
more neighbours of one age (``count``), and the display puts them back
around it where a view is close enough to tell.
"""

from __future__ import annotations

import numpy as np


class Members:
    """The plants of one stand, as parallel arrays."""

    FIELDS = (
        ("x", np.float64), ("y", np.float64),
        # How far behind the stand's founding cohort the plant is, in days of
        # growth: its own growth is the stand's ``development_days`` less this.
        ("lag_days", np.float64),
        ("born", np.int32),      # the season it took root
        ("variant", np.int16),   # which of the planet's kept individuals it looks like
        ("count", np.float32),   # how many plants the record stands for
        ("uid", np.int64),
    )

    def __init__(self):
        for name, kind in self.FIELDS:
            setattr(self, name, np.empty(0, dtype=kind))

    def __len__(self):
        return len(self.x)

    def append(self, **columns):
        for name, kind in self.FIELDS:
            setattr(self, name, np.concatenate([getattr(self, name), np.asarray(columns[name], dtype=kind)]))

    def keep(self, mask):
        for name, _kind in self.FIELDS:
            setattr(self, name, getattr(self, name)[mask])

    def plants(self):
        return float(self.count.sum())


class IndividualRegister:
    """Every recorded plant, stand by stand."""

    # Records a species may hold before each comes to stand for twice as many plants.
    RECORD_LIMIT = 20000

    def __init__(self):
        self.stands: dict[str, Members] = {}
        self.species_of: dict[str, str] = {}
        # Plants a new record of a species stands for.
        self.unit: dict[str, int] = {}
        # Plants followed in depth: their fate is their own, not the stand's dice.
        self.simulated: set[int] = set()
        self._next_uid = 1
        self.revision = 0

    def members(self, patch_id):
        return self.stands.get(patch_id)

    def unit_of(self, species_id):
        return self.unit.get(species_id, 1)

    def add(self, patch_id, species_id, x, y, lag_days, born, variant, count=None):
        """Record new plants in a stand; returns their ids."""
        x = np.atleast_1d(np.asarray(x, dtype=np.float64))
        number = len(x)
        members = self.stands.setdefault(patch_id, Members())
        self.species_of[patch_id] = species_id
        uid = np.arange(self._next_uid, self._next_uid + number, dtype=np.int64)
        self._next_uid += number
        members.append(
            x=x, y=np.atleast_1d(y), lag_days=np.broadcast_to(lag_days, (number,)),
            born=np.broadcast_to(born, (number,)), variant=np.broadcast_to(variant, (number,)),
            count=np.broadcast_to(self.unit_of(species_id) if count is None else count, (number,)), uid=uid,
        )
        self.revision += 1
        return uid

    def remove(self, patch_id, gone):
        """Take plants out of a stand (``gone`` marks them)."""
        members = self.stands.get(patch_id)
        if members is None or not np.any(gone):
            return
        self.simulated.difference_update(members.uid[gone].tolist())
        members.keep(~np.asarray(gone, dtype=bool))
        self.revision += 1

    def drop(self, patch_id):
        members = self.stands.pop(patch_id, None)
        self.species_of.pop(patch_id, None)
        if members is not None:
            self.simulated.difference_update(members.uid.tolist())
            self.revision += 1

    def merge(self, into_id, from_id, lag_shift_into=0.0, lag_shift_from=0.0):
        """Move a stand's plants into another; the shifts keep each plant's own growth as it was."""
        source = self.stands.pop(from_id, None)
        self.species_of.pop(from_id, None)
        target = self.stands.setdefault(into_id, Members())
        target.lag_days = target.lag_days + lag_shift_into
        if source is not None and len(source):
            columns = {name: getattr(source, name) for name, _kind in Members.FIELDS}
            columns["lag_days"] = columns["lag_days"] + lag_shift_from
            target.append(**columns)
        self.revision += 1

    def find(self, uid):
        """``(stand id, index)`` of a plant, or ``None`` once it is gone."""
        for patch_id, members in self.stands.items():
            index = np.flatnonzero(members.uid == uid)
            if len(index):
                return patch_id, int(index[0])
        return None

    def records(self, species_id):
        return sum(len(members) for patch_id, members in self.stands.items() if self.species_of[patch_id] == species_id)

    def coarsen(self, species_id, rng):
        """Halve a species' records; each survivor stands for the neighbour that went.

        Plants followed in depth are never the ones to go.
        """
        self.unit[species_id] = self.unit_of(species_id) * 2
        for patch_id, members in self.stands.items():
            if self.species_of[patch_id] != species_id or not len(members):
                continue
            followed = np.isin(members.uid, list(self.simulated)) if self.simulated else np.zeros(len(members), dtype=bool)
            stays = followed | (rng.random(len(members)) < 0.5)
            if not stays.any():
                stays[0] = True
            # What the survivors stand for grows by what went, so that the stand's plants are conserved.
            plants = members.plants()
            members.keep(stays)
            members.count = (members.count * (plants / max(1e-9, members.plants()))).astype(np.float32)
        self.revision += 1
