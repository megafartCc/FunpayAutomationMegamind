"""Legacy entrypoint shim for backwards compatibility."""

from backend.app import app

__all__ = ["app"]
