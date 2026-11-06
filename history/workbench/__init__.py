"""Factory Workbench — executes Factory project operations.

Workbench manages a project's ``ops/`` records and invokes AI work through a
configured execution adapter. It deliberately holds **no** backend credential,
no model registry and no tool implementation; that boundary is ADR-035 §2 and it
is what keeps Factory's declarations separable from a backend's enforcement.

Layering, per ADR-036:

    surfaces (CLI, local server)  ->  engine  ->  records  ->  ops/ + git

Every write goes through :mod:`workbench.engine`. Surfaces never touch ``ops/``
directly, so adding or removing a surface cannot change write semantics.
"""

__version__ = "0.1.0"
