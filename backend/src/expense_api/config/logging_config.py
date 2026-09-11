"""Logging setup. Called once at the top of create_app(), before anything else runs."""

import logging
import sys

# One constant, shared by basicConfig and the stdout handler's formatter. These were two
# separate literals in the repo this convention came from, and they drifted.
# pid is in the format because the container runs uvicorn with multiple workers.
LOG_FORMAT = "%(asctime)s - %(levelname)s - pid=%(process)d - %(name)s - %(message)s"

# Libraries that are useful at DEBUG and noise at every other level.
_NOISY = ("sqlalchemy.engine", "httpx", "httpcore", "asyncio", "multipart")


def setup_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # force=True so a library that called basicConfig before us does not win.
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=[handler], force=True)

    if level > logging.DEBUG:
        for name in _NOISY:
            logging.getLogger(name).setLevel(logging.WARNING)
