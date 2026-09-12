"""The append-only guard on claim_event, as SQL.

The trigger is created by the baseline migration, which deliberately spells it out again rather
than importing this: a migration has to keep working against the schema as it was on the day it
ran, so it freezes its own copy. This module is for runtime code that has to lift the guard and
put it back - today, only the demo reset.

There is exactly one such caller, and there should stay that way. An audit trail that ordinary
application code can rewrite is not an audit trail.
"""

DROP_AUDIT_TRIGGERS = (
    "DROP TRIGGER IF EXISTS claim_event_no_update",
    "DROP TRIGGER IF EXISTS claim_event_no_delete",
)

CREATE_AUDIT_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS claim_event_no_update
    BEFORE UPDATE ON claim_event
    BEGIN
        SELECT RAISE(ABORT, 'claim_event is append-only: UPDATE is not permitted');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS claim_event_no_delete
    BEFORE DELETE ON claim_event
    BEGIN
        SELECT RAISE(ABORT, 'claim_event is append-only: DELETE is not permitted');
    END
    """,
)
