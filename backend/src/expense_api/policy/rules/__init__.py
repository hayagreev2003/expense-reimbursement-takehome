"""Policy rules, one module per clause group.

Importing this package registers every rule. `engine.py` imports it for that side effect, so a
new module added here is live as soon as it is listed below.
"""

from expense_api.policy.rules import (  # noqa: F401
    conveyance,
    entertainment,
    lodging,
    meals,
    non_reimbursable,
    proof,
)

__all__ = [
    "conveyance",
    "entertainment",
    "lodging",
    "meals",
    "non_reimbursable",
    "proof",
]
