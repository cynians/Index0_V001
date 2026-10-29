"""World-generation package exports.

Keep this package lightweight so reference-data builders can use the pure
terrain and climate modules without loading the interactive pygame simulation.
"""

__all__ = ["WorldGenSimulation"]


def __getattr__(name):
    if name == "WorldGenSimulation":
        from simulations.world_gen.world_gen_sim import WorldGenSimulation

        return WorldGenSimulation
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
