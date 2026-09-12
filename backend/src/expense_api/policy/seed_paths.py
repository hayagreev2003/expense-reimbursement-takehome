"""Where the authored policy files live.

A small module of its own so tests and the seed agree on one path, and neither has to
reconstruct it from __file__ arithmetic.
"""

from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parent / "versions"
POLICY_YAML = VERSIONS_DIR / "ntx-hr-pol-11-rev4.yaml"
