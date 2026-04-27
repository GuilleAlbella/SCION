from __future__ import annotations

from app.db.base import Base
from app.graph.graph_engine import GraphEngine
from app.graph.graph_models import GraphEdge, GraphNode


def test_graph_engine_class_exists_and_is_instantiable() -> None:
    """GraphEngine must exist and be instantiable without side effects."""

    engine = GraphEngine()
    assert isinstance(engine, GraphEngine)


def test_graph_models_exist_and_inherit_from_base() -> None:
    """GraphNode and GraphEdge must be ORM models based on the shared Base."""

    assert issubclass(GraphNode, Base)
    assert issubclass(GraphEdge, Base)


def test_importing_graph_modules_has_no_side_effects() -> None:
    """Importing graph modules should not require a database or perform IO.

    If we reach this point, the imports in the module-level scope executed
    without raising, which is the only contract enforced at this stage.
    """

    # Nothing else to assert; absence of exceptions is the contract.
    assert True
