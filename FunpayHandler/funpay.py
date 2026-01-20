from __future__ import annotations

"""
Compatibility module.

The FastAPI app imports `startFunpay()` and `get_account()` from here.
Implementation lives in `FunpayHandler.bot.FunpayBot`.
"""

from .bot import FunpayBot


_BOT = FunpayBot()


def startFunpay() -> None:
    _BOT.start()


def get_account():
    return _BOT.account


def send_message_by_owner(owner: str, message: str) -> None:
    _BOT.send_message_by_owner(owner, message)


__all__ = ["send_message_by_owner", "get_account", "startFunpay"]
