from __future__ import annotations

import re
from datetime import datetime, timedelta

from pytz import timezone


MOSCOW_TZ = timezone("Europe/Moscow")


def normalize_choice_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def match_account_choice(choice: str, accounts: list[dict]) -> dict | None:
    normalized = normalize_choice_text(choice)
    if not normalized:
        return None

    if normalized.isdigit():
        account_id = int(normalized)
        for account in accounts:
            if account.get("id") == account_id:
                return account

    for account in accounts:
        if normalize_choice_text(account.get("account_name", "")) == normalized:
            return account
        if normalize_choice_text(account.get("login", "")) == normalized:
            return account

    return None


def match_account_name(order_name: str, all_accounts: list[str]) -> str | None:
    cleaned_order_name = re.sub(r"[^\w\s]", " ", order_name)
    cleaned_order_name = " ".join(cleaned_order_name.split())
    matched_account = None
    max_similarity = 0

    for account in all_accounts:
        cleaned_account = re.sub(r"[^\w\s]", " ", account)
        cleaned_account = " ".join(cleaned_account.split())

        if cleaned_account.lower() in cleaned_order_name.lower():
            similarity = len(cleaned_account)
            if similarity > max_similarity:
                max_similarity = similarity
                matched_account = account

    return matched_account


def parse_lot_number(text: str) -> int | None:
    match = re.search(r"(?:№|#)\s*(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def get_remaining_time(account: dict, current_time: datetime):
    rental_start = account.get("rental_start")
    if not rental_start:
        return None, "неизвестно", "неизвестно"

    freeze_at = account.get("rental_frozen_at")
    if account.get("rental_frozen") and freeze_at:
        if isinstance(freeze_at, datetime):
            freeze_dt = freeze_at
        else:
            try:
                freeze_dt = datetime.strptime(str(freeze_at), "%Y-%m-%d %H:%M:%S")
            except Exception:
                freeze_dt = None
        if freeze_dt:
            if freeze_dt.tzinfo is None:
                freeze_dt = MOSCOW_TZ.localize(freeze_dt)
            if current_time > freeze_dt:
                current_time = freeze_dt

    if isinstance(rental_start, datetime):
        start_dt = rental_start
    else:
        start_dt = datetime.strptime(rental_start, "%Y-%m-%d %H:%M:%S")

    if start_dt.tzinfo is None:
        start_dt = MOSCOW_TZ.localize(start_dt)

    duration_minutes = get_duration_minutes(account)
    if duration_minutes <= 0:
        return None, "не задано", "не задано"
    expiry_time = start_dt + timedelta(minutes=duration_minutes)
    remaining = expiry_time - current_time
    if remaining.total_seconds() < 0:
        remaining = timedelta(0)
    max_remaining = timedelta(minutes=duration_minutes)
    if remaining > max_remaining:
        remaining = max_remaining

    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    remaining_str = f"{hours} ч {minutes} мин"
    expiry_str = expiry_time.strftime("%H:%M:%S")
    return expiry_time, expiry_str, remaining_str


def get_duration_minutes(account: dict) -> int:
    minutes = account.get("rental_duration_minutes")
    if minutes is not None:
        try:
            return int(minutes)
        except Exception:
            return 0
    hours = account.get("rental_duration")
    if hours is None:
        return 0
    try:
        return int(hours) * 60
    except Exception:
        return 0


def format_duration_minutes(total_minutes: int) -> str:
    if total_minutes <= 0:
        return "0 мин"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"
