from __future__ import annotations


class GraphEngine:
    """Base graph engine orchestrator.

    v0 (structural skeleton only):
    - Defines the public contract for graph-related operations.
    - Does not execute SQL or depend on diff/snapshot engines.
    - Contains no functional implementation yet.
    """

    def __init__(self) -> None:
        """Instantiate a graph engine.

        No external resources are acquired at construction time.
        """

    def build_graph(self, snapshot_id: int) -> None:
        """Build an in-memory graph view for the given snapshot.

        This method is intentionally unimplemented in the structural
        skeleton and will be provided in later versions.
        """

        raise NotImplementedError("build_graph is not implemented yet")

    def compute_impact(self, change_id: int) -> None:
        """Compute impact for a given change identifier.

        This method is intentionally unimplemented in the structural
        skeleton and will be provided in later versions.
        """

        raise NotImplementedError("compute_impact is not implemented yet")

    def get_lineage(self, node_id: int) -> None:
        """Return lineage information for a given node identifier.

        This method is intentionally unimplemented in the structural
        skeleton and will be provided in later versions.
        """

        raise NotImplementedError("get_lineage is not implemented yet")
