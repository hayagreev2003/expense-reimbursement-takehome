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


def warm_cache(receipts_dir: Path) -> tuple[int, float]:
    """Read every receipt image once, so no HTTP request is the first to pay for it.

    A draft claim is evaluated live on every read, and evaluating it OCRs the images behind the
    two bills. `ocr_image` is cached per process, so only the *first* request pays - but it pays
    synchronously, on the event loop, and on a small shared-CPU instance that is long enough to
    starve the health check, which restarts the process, which empties the cache. The service
    then never serves a single claim.

    Called at startup, where the cost is bounded, paid once, and visible in the boot log.
    Returns how many images were read and how long it took.
    """
    import time

    if not ocr_available():
        logger.warning("tesseract unavailable: receipt images will not be read")
        return 0, 0.0

    started = time.monotonic()
    read = 0
    for path in sorted(receipts_dir.glob("*")):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        try:
            ocr_image(path)
            read += 1
        except (OcrUnavailableError, OSError) as exc:
            # One unreadable image must not stop the application from starting. It will surface
            # as needs-input on the claim, which is visible, rather than as a failed boot.
            logger.warning("Could not pre-read %s: %s", path.name, exc)

    return read, time.monotonic() - started
