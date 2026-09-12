"""Demo reset.

A hosted walkthrough has no shell, so `make reset-db` is unreachable there. This package is the
HTTP equivalent: wipe everything the demo produced, then re-run the seed so the pack's inbox is
back in its starting state and the flow can be shown again from the top.

Off unless `DEMO_RESET_ENABLED=true`. It deletes claims.
"""
