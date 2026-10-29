# Workspace agent instructions

## Plant design requests

When the user says "design a plant", "plant design", "plant design process",
"design process" in a plant context, or uses similar wording to begin another
plant/species design pass, treat it as an invocation of the canonical workflow
in `docs/Plant_Design_Process.md`.

Before taking plant-design actions, open that document and follow its current
instructions. Respect its token-efficient reading guidance: read the heading
index and required startup sections first, then load later sections only when
the workflow reaches them. Do not create duplicate process documents for
alternate filenames or phrasings.

## World generation comes first: there are no live worlds

Owner's rule (2026-10-05). World generation is being finished before any
world is generated to keep. Every planet, region and site in the store today
is a test fixture.

- Do not write migrations, compatibility shims, fallbacks for old records or
  version switches for generated worlds. When generation changes, regenerate.
- Do not hold a better mechanism back because stored worlds would look
  different or stop loading.
- Tests and documents describe what the generator produces now, not what an
  older one stored.

This is about generated worlds. The ontology's authored content (materials,
species, technologies and the like) is unchanged by it: it stays the durable
source and is written with the usual care.

## A map's level is its scale

Owner's decision (2026-10-06). A level (Macroregion, Region, Local, Site,
Parcel, Plot) is a scale of ground read off a map's footprint, not a count
of refinements. Every refinement goes exactly one level down, with cells at
least three times finer; `generate_refined_region` refuses a footprint too
large for that and builds the maps in between for one that is levels finer.
The table is in `docs/LOD_Worldgen_Procedure.md` section 2. Do not add a
path that makes a map of a level its footprint does not have.
