"""Legacy logger shim; use backend.logger instead."""

from backend.logger import logger

__all__ = ["logger"]
