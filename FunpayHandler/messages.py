from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserMessages:
    extend_usage: str = "Использование: !продлить <часы> <ID аккаунта>"
    extend_hours_positive: str = "Количество часов должно быть больше 0."
    active_rentals_empty: str = "Активных аренд нет."
    choose_account_prompt: str = "У вас несколько активных аренд. Напишите ID или логин аккаунта:"
    choice_not_understood: str = "Не понял выбор. Напишите ID или логин аккаунта."
    account_details_header: str = "Данные аккаунта:\n"
    extend_failed: str = "Не удалось продлить аренду. Попробуйте позже."
    acc_failed: str = "Не удалось получить данные аккаунта. Попробуйте позже."
    stock_title: str = "Свободные лоты:"
    stock_no_lots_configured: str = "Лоты не добавлены."
    stock_failed: str = "Не удалось получить наличие. Попробуйте позже."


USER = UserMessages()
