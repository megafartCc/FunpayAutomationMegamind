from __future__ import annotations

"""
Compatibility module.

The FastAPI app imports `startFunpay()` and `get_account()` from here.
Implementation lives in `FunpayHandler.bot.FunpayBot`.
"""

from typing import Optional

from .bot import FunpayBot


_BOT: Optional[FunpayBot] = None


def _get_bot() -> FunpayBot:
    global _BOT
    if _BOT is None:
        _BOT = FunpayBot()
    return _BOT


def startFunpay() -> None:
    _get_bot().start()


def get_account():
    return _get_bot().account


def send_message_by_owner(owner: str, message: str) -> None:
    _get_bot().send_message_by_owner(owner, message)


__all__ = ["send_message_by_owner", "get_account", "startFunpay"]
