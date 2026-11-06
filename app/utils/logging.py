import logging


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Never log HTTP client request details (headers may hold keys).
    logging.getLogger("httpx").setLevel(logging.WARNING)
