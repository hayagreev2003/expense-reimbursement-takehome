"""Custom column types.

`Money` exists because of a specific SQLite hazard. SQLAlchemy's `Numeric` has no native
SQLite counterpart, so the dialect converts Decimal values through Python floats and warns that
"rounding errors and other issues may occur". In an expense settlement system that is not an
acceptable warning to live with: 0.1 + 0.2 arriving as 0.30000000000000004 in a tax
apportionment turns into a claim total that does not reconcile against the source bill.

So money is stored as an integer number of paise and only ever surfaces as a Decimal. No float
appears anywhere in the money path, and SUM() in SQL stays exact.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import Dialect, Integer
from sqlalchemy.types import TypeDecorator

# Two decimal places. INR has no sub-paise amounts in any bill in scope.
_SCALE = Decimal("0.01")
_FACTOR = 100


class Money(TypeDecorator[Decimal]):
    """A Decimal amount persisted as an integer count of paise."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Decimal | int | str | None, dialect: Dialect) -> int | None:
        if value is None:
            return None

        amount = value if isinstance(value, Decimal) else Decimal(str(value))

        # Reject rather than round. A caller handing over more precision than paise has either
        # divided without quantising or is passing a float, and silently rounding here would
        # hide the arithmetic error rather than surface it.
        quantised = amount.quantize(_SCALE)
        if quantised != amount:
            raise ValueError(
                f"Money value {amount} has sub-paise precision; quantise to 0.01 before storing"
            )

        return int(quantised * _FACTOR)

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return (Decimal(value) / _FACTOR).quantize(_SCALE)
