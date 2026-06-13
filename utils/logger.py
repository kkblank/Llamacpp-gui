import logging
import sys
from datetime import datetime

logger = logging.getLogger("llamacpp_gui")
logger.setLevel(logging.DEBUG)

_handler = logging.StreamHandler(sys.stdout)
_handler.setLevel(logging.DEBUG)
_formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%H:%M:%S")
_handler.setFormatter(_formatter)
logger.addHandler(_handler)


def info(msg):
    logger.info(msg)


def warn(msg):
    logger.warning(msg)


def error(msg):
    logger.error(msg)
