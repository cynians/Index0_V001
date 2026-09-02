"""Person-scale road-corridor windowing: load slices ahead, drop slices behind.

This is the skeleton for the road-strip/corridor logistics mode described in
docs/conceptual_layer_overview_v006.txt section 14 -- a rolling ribbon of
map content generated from parent context as a traveler advances, rather
than materializing the whole corridor at once.

Because simulations/world_gen/local_placeholder_heightmap.py samples a
continuous noise field in absolute meter coordinates (not bounds-normalized
ones), any two windows using the same seed are automatically consistent
slices of one field -- there is no separate stored raster to crop from, so
"regenerating a slice" is just resampling that field over a new window.

Render hookup: rather than modifying MapSimulation (a large, unrelated file)
to understand a "current slice" concept, RoadCorridorWindow can optionally
write the active slice's heightmap_model directly onto a target location
entity (e.g. location_lumber_east_road). Opening the ordinary Map view on
that entity then picks up the current slice through the existing, untouched
heightmap-layer rendering path -- no new UI screen, no MapSimulation edits.
"""

import math

from simulations.world_gen.local_placeholder_heightmap import (
    LUMBER_AREA_SEED,
    build_placeholder_heightmap,
)


class RoadCorridorWindow:
    def __init__(
        self,
        route_waypoints,
        *,
        seed=LUMBER_AREA_SEED,
        slice_spacing_m=40.0,
        slice_size_m=50.0,
        slices_ahead=2,
        slices_behind=1,
        resolution=17,
        target_entity=None,
    ):
        waypoints = [tuple(point) for point in route_waypoints]
        if len(waypoints) < 2:
            raise ValueError("RoadCorridorWindow requires at least two route waypoints")
        self.route_waypoints = waypoints
        self.seed = seed
        self.slice_spacing_m = float(slice_spacing_m)
        self.slice_size_m = float(slice_size_m)
        self.slices_ahead = int(slices_ahead)
        self.slices_behind = int(slices_behind)
        self.resolution = int(resolution)
        # An in-memory location entity dict (e.g. the authored East Road
        # location) whose heightmap_model is kept pointed at the currently
        # centered slice, so the ordinary Map view renders it unmodified.
        self.target_entity = target_entity

        self._segments = []
        total_length = 0.0
        for start, end in zip(waypoints, waypoints[1:]):
            length = math.hypot(end[0] - start[0], end[1] - start[1])
            self._segments.append((start, end, length))
            total_length += length
        self.total_length_m = total_length

        self.loaded_slices = {}
        self.current_distance_m = 0.0

    def slice_count(self):
        return max(1, int(math.floor(self.total_length_m / self.slice_spacing_m)) + 1)

    def _point_at_distance(self, distance):
        distance = max(0.0, min(self.total_length_m, distance))
        traveled = 0.0
        for start, end, length in self._segments:
            if length <= 1e-9:
                traveled += length
                continue
            if distance <= traveled + length:
                local = (distance - traveled) / length
                return (start[0] + (end[0] - start[0]) * local, start[1] + (end[1] - start[1]) * local)
            traveled += length
        return self._segments[-1][1]

    def _build_slice(self, index):
        center = self._point_at_distance(index * self.slice_spacing_m)
        half = self.slice_size_m / 2.0
        bounds = {
            "type": "bbox",
            "min_x": center[0] - half, "max_x": center[0] + half,
            "min_y": center[1] - half, "max_y": center[1] + half,
        }
        heightmap = build_placeholder_heightmap(bounds, self.seed, resolution=self.resolution)
        return {"index": index, "center": center, "bounds": bounds, "heightmap_model": heightmap}

    def advance(self, distance_along_route):
        """Move the window to a new position along the route.

        Loads slices within [slices_behind, slices_ahead] of the nearest
        slice index and drops everything else. Returns what changed so
        callers/tests can observe load-ahead/unload-behind behavior without
        reaching into internal state.
        """
        self.current_distance_m = max(0.0, min(self.total_length_m, float(distance_along_route)))
        center_index = int(round(self.current_distance_m / self.slice_spacing_m))
        last_index = self.slice_count() - 1
        needed_indices = {
            index for index in range(center_index - self.slices_behind, center_index + self.slices_ahead + 1)
            if 0 <= index <= last_index
        }

        unloaded = [index for index in self.loaded_slices if index not in needed_indices]
        for index in unloaded:
            del self.loaded_slices[index]

        newly_loaded = [index for index in needed_indices if index not in self.loaded_slices]
        for index in sorted(newly_loaded):
            self.loaded_slices[index] = self._build_slice(index)

        if self.target_entity is not None:
            active_slice = self.loaded_slices.get(center_index)
            if active_slice is not None:
                self.target_entity["heightmap_model"] = active_slice["heightmap_model"]
                self.target_entity["bounds"] = dict(active_slice["bounds"])

        return {
            "center_index": center_index,
            "loaded_indices": sorted(self.loaded_slices),
            "newly_loaded": sorted(newly_loaded),
            "unloaded": sorted(unloaded),
        }
