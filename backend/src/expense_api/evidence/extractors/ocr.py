"""Read text out of a receipt photograph.

Used when a bill arrives as an image with no machine-readable body, and as a cross-check when
both exist. It is genuinely fallible on the pack's own images: both have a fold drawn across
them, and on the hotel folio the fold sits on a room charge, destroying the label and degrading
`5,750.00` to `5.750.00`.

That is why nothing here tries to be clever about recovery. The reconciliation guard in
reconcile.py is the safety net, and it is a better one than any amount of preprocessing,
because it catches failures this module cannot even detect.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# psm 6: "assume a single uniform block of text". Receipts are columnar, and the alternatives
# either merge the amount column into the description or split every line into fragments.
_PSM = "--psm 6"


class OcrUnavailableError(RuntimeError):
    """tesseract is not installed or not on PATH."""


@lru_cache(maxsize=64)
def ocr_image(path: Path) -> str:
    """Text from an image. Cached, because the same receipt is read more than once per run."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - both are hard dependencies
        raise OcrUnavailableError(f"OCR dependencies missing: {exc}") from exc

    if not path.exists():
        raise FileNotFoundError(f"No image at {path}")

    try:
        with Image.open(path) as image:
            return str(pytesseract.image_to_string(image, config=_PSM))
    except Exception as exc:  # noqa: BLE001 - pytesseract raises several unrelated types
        raise OcrUnavailableError(f"Could not OCR {path.name}: {exc}") from exc


def ocr_available() -> bool:
    """Whether the tesseract binary can actually be reached.

    Checked rather than assumed: the backend image installs it, but `make dev` runs on whatever
    the developer has, and an extractor silently returning nothing is the failure mode this
    whole module exists to avoid.
    """
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001
        return False
    return True
