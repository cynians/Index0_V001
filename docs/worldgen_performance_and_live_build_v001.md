# World generation performance and live-build view v001

## Why the old screen appeared stuck at 96%

The previous loading percentage was calculated from elapsed time and an estimate, then capped at 96% until the worker returned. It did not measure generator progress. Long climate, hydrology, geomorphology, raster, or persistence work therefore looked like one unexplained final stall.

World generation now reports named checkpoints with real elapsed timestamps. The loading screen shows the latest safely published grid, reveals it in tiles, and rotates between every currently available map mode: relief, tectonics, materials, and climate. Draft references live only in the simulation's preview state and are not persisted as partially generated ontology data.

## Numeric-library decision

- NumPy is already used in the coupled water-cycle and several geomorphology paths. It is the right library for dense numeric grids.
- pandas is designed for labelled/tabular data. It would add conversion and memory overhead to these regular 2D map arrays, so it is not part of the compute path.
- Pygame draws and presents the results. `Surface`, `PixelArray`, and `surfarray` can make display conversion efficient, but Pygame is not a general-purpose GPU compute framework.

## GPU path

Do not introduce an unconditional GPU dependency. A useful GPU backend requires a sufficiently large, vectorized kernel and should keep arrays on the device across several operations; copying a grid to and from the GPU for each small phase can be slower than NumPy.

The recommended experiment is an optional array backend for the coupled climate/moisture solve:

1. Capture checkpoint timings from a representative generation run.
2. Profile the slowest checkpoint and separate compute time from ontology persistence and raster I/O.
3. Convert the slow kernel to array operations with a small `numpy`-compatible backend boundary.
4. Add deterministic CPU/GPU parity tests with numeric tolerances.
5. Enable CuPy only when a supported CUDA device and package are detected; otherwise retain NumPy.
6. Benchmark end-to-end time, including transfers, before making the backend selectable in the UI.

Current host inspection did not expose `nvidia-smi`, so no CUDA-only dependency was installed or enabled.

## LOD0 ownership and measured result

Profiling showed that the slow relief loop was not merely sampling 513 rows.
Every global sample was rebuilding regional-scale continental provinces,
sutures, rifts, basin geometry, hotspot tracks, and high-octave noise. A
representative 1025-sample tectonic row took 3.87 seconds and about 8.6 million
Python calls; the continental signal alone accounted for roughly 3.0 seconds.

LOD0 now retains a 513 x 257 consumer grid but evaluates expensive global
causes on 257 x 129 anchors, then interpolates them with NumPy. The global path
keeps continentality, major relief, broad basins, plate-boundary influence,
sea level, shelves, climate inputs, and child boundary conditions. It does not
materialize province geometry, exact rifts, hotspot tracks, small craters, or
high-frequency terrain. Those mechanisms remain enabled in regional
regeneration, where they are evaluated only for the requested footprint.

On the same development machine, a complete tectonic LOD0 heightmap now took
25.15 seconds. The isolated global relief row fell to roughly 0.25–0.32
seconds at 513 samples. These measurements cover the heightmap stage, not the
entire climate, materials, hydrology, and persistence pipeline.

## Reading the next run

The checkpoint list shows an `MM:SS` timestamp for each completed phase. A long pause on a climate pass points to a numeric kernel. A long pause on material compositing points to raster work. A long pause on the final save points to ontology serialization/storage. This evidence determines whether the next optimization should be vectorization, reduced copying, raster batching, or a more compact persistence format.

## Primary references

- Pygame `surfarray`: <https://www.pygame.org/docs/ref/surfarray.html>
- Pygame `Surface`: <https://www.pygame.org/docs/ref/surface.html>
- CuPy overview: <https://docs.cupy.dev/en/stable/>
- CuPy installation and platform requirements: <https://docs.cupy.dev/en/stable/install.html>
