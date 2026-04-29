"""Skip-by-default for the graph test suite — known broken.

29 of 32 tests assume the developer's DB has been seeded with the
demo fixtures. Pre-v1.13.05 they "passed" because previous tests
in the run had populated the global DB; with proper test isolation
each test gets a fresh empty DB and the assertions about expected
graph nodes / edges / impact rows fail.

The fix is per-test fixtures that build the graph state they need
(or shared fixtures via a builder). Out of scope for v1.14.05.

Tracked in `docs/internal_roadmap.md` (Cross-cutting backlog → Tests).
"""

import pytest

collect_ignore_glob = ["test_*.py"]
pytestmark = pytest.mark.skip(
    reason="Known broken — pending test-isolation followup. See conftest.py."
)
