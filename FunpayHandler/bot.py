from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from FunPayAPI import Account, Runner, events, types

from config import (
    AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE,
    DOTA_MATCH_DELAY_EXPIRE,
    DOTA_MATCH_GRACE_MINUTES,
    FUNPAY_GOLDEN_KEY,
    HOURS_FOR_REVIEW,
    RENTAL_CHECK_INTERVAL,
)
from DatabaseHandler.databaseSetup import SQLiteDB
from logger import logger
from notifications import send_message_to_admin
from SteamHandler.SteamGuard import get_steam_guard_code
from SteamHandler.changePassword import changeSteamPassword
from SteamHandler.deauthorize import logout_all_steam_sessions
from SteamHandler.presence_bot import get_presence_bot

from .messages import USER
from .utils import (
    MOSCOW_TZ,
    format_duration_minutes,
    get_duration_minutes,
    get_remaining_time,
    match_account_choice,
    match_account_name,
    parse_lot_number,
)


REFRESH_INTERVAL_SECONDS = 1300  # 30 minutes
PENDING_EXTEND_TTL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class PendingLotExtend:
    hours: int
    lot_number: int
    created_ts: float


class FunpayBot:
    def __init__(self, token: str = FUNPAY_GOLDEN_KEY, db: SQLiteDB | None = None) -> None:
        self._token = token
        self._db = db or SQLiteDB()

        self._acc: Account | None = None
        self._runner: Runner | None = None

        self._feedback_given: set[str] = set()
        self._bonus_eligible: set[str] = set()
        self._pending_account_choice: dict[str, list[dict]] = {}
        self._pending_lot_extend: dict[str, PendingLotExtend] = {}
        self._processed_order_ids: set[str] = set()

        self._last_refresh_ts = 0.0
        self._expire_delay_since: dict[int, datetime] = {}
        self._expire_delay_notified: set[int] = set()
        self._expire_warning_sent: dict[int, set[int]] = {}
        self._expire_warning_start: dict[int, str] = {}

    def _has_feedback_in_chat(self, owner: str) -> bool:
        if self._acc is None:
            return False
        chat = self._acc.get_chat_by_name(owner, True)
        messages = getattr(chat, "messages", None) or []
        for message in reversed(messages):
            if getattr(message, "author_id", None) != 0:
                continue
            initiator = getattr(message, "initiator_username", None)
            if initiator and initiator != owner:
                continue
            msg_type = getattr(message, "type", None)
            if msg_type in (types.MessageTypes.NEW_FEEDBACK, types.MessageTypes.FEEDBACK_CHANGED):
                return True
            if msg_type is types.MessageTypes.FEEDBACK_DELETED:
                return False
        return False

    def _get_unit_minutes(self, account: dict) -> int:
        base_minutes = get_duration_minutes(account)
        if base_minutes <= 0:
            return 0
        if account.get("owner"):
            units = int(account.get("rental_duration") or 0)
            if units > 0 and base_minutes % units == 0:
                per_unit = base_minutes // units
                return max(per_unit, 1)
        return max(base_minutes, 1)

    def _set_rental_duration_for_order(self, account_id: int, units: int, unit_minutes: int) -> None:
        total_minutes = int(units) * int(unit_minutes)
        conn, cursor = self._db.open_connection()
        try:
            cursor.execute(
                """
                UPDATE accounts
                SET rental_duration = ?, rental_duration_minutes = ?
                WHERE ID = ?
                """,
                (int(units), total_minutes, account_id),
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def _extend_rental_for_order(self, account_id: int, owner: str, units: int, unit_minutes: int) -> bool:
        total_minutes = int(units) * int(unit_minutes)
        if total_minutes <= 0:
            return False
        conn, cursor = self._db.open_connection()
        try:
            cursor.execute(
                """
                UPDATE accounts
                SET rental_duration_minutes = COALESCE(rental_duration_minutes, rental_duration * 60) + ?,
                    rental_duration = COALESCE(rental_duration, 0) + ?
                WHERE ID = ? AND owner = ?
                """,
                (total_minutes, int(units), account_id, owner),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            conn.close()

    @property
    def account(self) -> Account | None:
        return self._acc

    def refresh_session(self) -> None:
        logger.info("Refreshing FunPay session...")
        self._acc = Account(self._token).get()
        self._runner = Runner(self._acc)
        logger.info("FunPay session refreshed successfully.")

    def start(self) -> None:
        logger.info("Starting FunPay bot...")
        if not self._token:
            logger.error("FUNPAY_GOLDEN_KEY is missing. FunPay automation stopped.")
            return

        self.refresh_session()
        self._last_refresh_ts = time.time()

        thread = threading.Thread(target=self._check_rental_expiration_loop, daemon=True)
        thread.start()
        logger.info("Rental expiration checker started.")

        if self._runner is None:
            raise RuntimeError("Runner not initialized")

        for event in self._runner.listen(requests_delay=8):
            try:
                self._tick_refresh_if_needed()

                if event.type is events.EventTypes.NEW_ORDER:
                    self._handle_new_order(event)
                elif hasattr(events.EventTypes, "ORDER_PAID") and event.type is events.EventTypes.ORDER_PAID:
                    self._handle_order_paid(event)

                if event.type is events.EventTypes.NEW_MESSAGE:
                    self._handle_new_message(event)

                message = getattr(event, "message", None)
                if message is not None and getattr(message, "type", None) == types.MessageTypes.NEW_FEEDBACK:
                    self._handle_new_feedback(event)
            except Exception as exc:
                logger.error(f"An error occurred while processing event: {exc}")

    def send_message_by_owner(self, owner: str, message: str) -> None:
        if self._acc is None:
            logger.error("FunPay session not initialized; cannot send message.")
            return
        chat = self._acc.get_chat_by_name(owner, True)
        self._acc.send_message(chat.id, message)

    def _tick_refresh_if_needed(self) -> None:
        now = time.time()
        if now - self._last_refresh_ts < REFRESH_INTERVAL_SECONDS:
            return
        logger.info("Refreshing session due to interval timeout...")
        self.refresh_session()
        self._last_refresh_ts = now

    def _handle_new_order(self, event: Any) -> None:
        self._process_order(event, source="NEW_ORDER")

    def _handle_order_paid(self, event: Any) -> None:
        self._process_order(event, source="ORDER_PAID")

    def _mark_order_processed(self, event: Any) -> None:
        order = getattr(event, "order", None)
        if not order:
            return
        order_id = getattr(order, "id", None)
        if order_id is None:
            return
        self._processed_order_ids.add(str(order_id))

    def _process_order(self, event: Any, source: str) -> None:
        if self._acc is None:
            self.refresh_session()
        acc = self._acc
        if acc is None:
            return

        order = getattr(event, "order", None)
        if order is None:
            return

        order_id = getattr(order, "id", None)
        if not order_id:
            logger.warning(f"Skipping order with invalid id from {source}: {order_id}")
            return
        order_id = str(order_id)

        if order_id in self._processed_order_ids:
            return

        buyer = str(order.buyer_username)
        chat = acc.get_chat_by_name(buyer, True)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            chat_id = getattr(order, "chat_id", None)
        if chat_id is None:
            logger.warning(f"Skipping order {order_id}: chat id not found")
            return

        description = str(getattr(order, "description", "") or "")
        amount = int(getattr(order, "amount", 1) or 1)

        lot_number = parse_lot_number(description)
        if lot_number is not None:
            self._process_lot_order(acc, chat_id, event, buyer, lot_number, amount)
            return

        self._process_named_order(acc, chat_id, event, buyer, description, amount)

    def _process_lot_order(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        buyer: str,
        lot_number: int,
        amount: int,
    ) -> None:
        mapping = self._db.get_lot_mapping(lot_number)
        if not mapping:
            acc.send_message(chat_id, "Лот не привязан к аккаунту. Дождитесь ответа администратора.")
            send_message_to_admin(
                "ЛОТ БЕЗ ПРИВЯЗКИ\n\n"
                f"Покупатель: {buyer}\n"
                f"Лот: №{lot_number}\n"
                f"Заказ: {event.order.id}"
            )
            return

        account = self._db.get_account_by_lot_number(lot_number)
        if not account:
            acc.send_message(chat_id, "Ошибка: лот привязан к аккаунту, но аккаунт не найден. Напишите администратору.")
            send_message_to_admin(
                "ОШИБКА ПРИ ВЫДАЧЕ\n\n"
                f"Покупатель: {buyer}\n"
                f"Лот: №{lot_number}\n"
                f"Заказ: {event.order.id}\n"
                "Причина: аккаунт по лоту не найден в БД"
            )
            return

        pending = self._pending_lot_extend.get(buyer)
        if pending is not None and (time.time() - pending.created_ts) > PENDING_EXTEND_TTL_SECONDS:
            self._pending_lot_extend.pop(buyer, None)
            pending = None

        is_requested_extend = pending is not None and pending.lot_number == lot_number
        if is_requested_extend:
            self._pending_lot_extend.pop(buyer, None)

        if account.get("owner") is None:
            self._issue_new_account(acc, chat_id, event, account, amount)
            self._mark_order_processed(event)
            return

        if account.get("owner") == buyer:
            unit_minutes = self._get_unit_minutes(account)
            success = self._extend_rental_for_order(account["id"], buyer, amount, unit_minutes)
            if not success:
                acc.send_message(chat_id, USER.extend_failed)
                return

            refreshed = self._db.get_account_by_id(account["id"])
            current_time = datetime.now(tz=MOSCOW_TZ)
            _, expiry_str, remaining_str = get_remaining_time(refreshed, current_time)
            duration_label = format_duration_minutes(unit_minutes * amount)

            note = ""
            if is_requested_extend and pending and pending.hours != amount:
                pending_label = format_duration_minutes(unit_minutes * pending.hours)
                note = (
                    f"\n\nПримечание: вы запросили {pending_label}, "
                    f"но оплатили {duration_label} (будет продлено на {amount} шт)."
                )

            acc.send_message(
                chat_id,
                f"Продлено на {duration_label}.\n"
                f"Лот: №{lot_number}\n"
                f"ID: {account['id']}\n"
                f"Аккаунт: {account['account_name']}\n"
                f"Истекает: {expiry_str} МСК | Осталось: {remaining_str}{note}",
            )
            acc.confirm(event.order.id)
            self._mark_order_processed(event)
            return

        acc.send_message(
            chat_id,
            "Этот лот сейчас уже арендован.\n"
            "Пожалуйста, выберите другой лот или напишите в чат — поможем.",
        )
        send_message_to_admin(
            "КОНФЛИКТ ПО ЛОТУ\n\n"
            f"Покупатель: {buyer}\n"
            f"Лот: №{lot_number}\n"
            f"Заказ: {event.order.id}\n"
            f"Текущий владелец: {account.get('owner')}"
        )

    def _process_named_order(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        buyer: str,
        order_name: str,
        amount: int,
    ) -> None:
        all_accounts = self._db.get_all_account_names()
        matched_account = match_account_name(order_name, all_accounts)
        if matched_account is None:
            logger.warning(f"No matching account found for order: {order_name}")
            return

        account_name = matched_account
        if account_name not in all_accounts:
            logger.info(f"Item '{account_name}' not found in rentals; skipping.")
            return

        specific_account = self._db.get_account_by_name(account_name)
        if not specific_account:
            logger.error(f"Account with name '{account_name}' not found in database")
            acc.send_message(
                chat_id,
                f"Ошибка: аккаунт '{account_name}' не найден.\n"
                "Возврат оформлен. Напишите, поможем.",
            )
            return

        if specific_account.get("owner") is not None:
            logger.warning(f"Account '{account_name}' is already rented by {specific_account['owner']}")
            acc.send_message(
                chat_id,
                "Этот аккаунт сейчас уже арендован.\n"
                "Пожалуйста, выберите другой лот или напишите в чат — поможем.",
            )
            return

        if amount > 1:
            unit_minutes = self._get_unit_minutes(specific_account)
            unit_label = format_duration_minutes(unit_minutes)
            total_label = format_duration_minutes(unit_minutes * amount)
            acc.send_message(
                chat_id,
                f"Вы оплатили {amount} шт. '{account_name}'.\n"
                f"Продление будет на {total_label} (1 шт = {unit_label}).\n\n"
                "Если нужен другой вариант — напишите в чат.",
            )

        existing_rentals = self._db.get_user_accounts_by_name(buyer, account_name)
        if existing_rentals:
            self._extend_existing_rental(acc, chat_id, event, existing_rentals[0], account_name, amount)
            self._mark_order_processed(event)
            return

        self._issue_new_account(acc, chat_id, event, specific_account, amount)
        self._mark_order_processed(event)

    def _extend_existing_rental(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        rental: dict,
        order_name: str,
        units: int,
    ) -> None:
        unit_minutes = self._get_unit_minutes(rental)
        duration_label = format_duration_minutes(unit_minutes * units)
        logger.info(
            f"User {event.order.buyer_username} already has active rental for {order_name}, extending by {duration_label}..."
        )
        success = self._extend_rental_for_order(
            rental["id"],
            event.order.buyer_username,
            units,
            unit_minutes,
        )
        if not success:
            acc.send_message(chat_id, USER.extend_failed)
            return

        acc.send_message(
            chat_id,
            "Аренда продлена!\n\n"
            f"Тип аккаунта: {order_name}\n"
            f"Продление: +{duration_label}\n"
            f"ID: {rental['id']}\n\n"
            "Данные аккаунта ниже.",
        )

        account = self._db.get_account_by_id(rental["id"])
        if account:
            rental_start = account["rental_start"]
            if isinstance(rental_start, datetime):
                start_dt = rental_start
            else:
                start_dt = datetime.strptime(rental_start, "%Y-%m-%d %H:%M:%S")
            duration_minutes = get_duration_minutes(account)
            expiry_time = start_dt + timedelta(minutes=duration_minutes)
            acc.send_message(
                chat_id,
                f"ID: {rental['id']}\n"
                f"Логин: {rental['login']}\n"
                f"Пароль: {rental['password']}\n"
                f"Истекает: {expiry_time.strftime('%H:%M:%S')} МСК\n"
                "Команды: !акк, !код",
            )

        send_message_to_admin(
            "RENTAL EXTENDED\n\n"
            f"User: {event.order.buyer_username}\n"
            f"Account type: {order_name}\n"
            f"Extension: +{duration_label}\n"
            f"Price: {event.order.price} RUB\n"
            f"Account ID: {rental['id']}\n"
            "Note: user already had an active rental",
        )

        acc.confirm(event.order.id)

    def _issue_new_account(self, acc: Account, chat_id: int, event: Any, account: dict, units: int) -> None:
        logger.info(f"Assigning specific account '{account['account_name']}' to user {event.order.buyer_username}")
        self._db.set_account_owner(account["id"], event.order.buyer_username)
        unit_minutes = self._get_unit_minutes(account)
        duration_label = format_duration_minutes(unit_minutes * units)
        self._set_rental_duration_for_order(account["id"], units, unit_minutes)

        send_message_to_admin(
            "NEW ACCOUNT ISSUED\n\n"
            f"Buyer: {event.order.buyer_username}\n"
            f"ID: {account['id']}\n"
            f"Account name: {account['account_name']}\n"
            f"Login: {account['login']}\n"
            f"Password: {account['password']}\n"
            f"Price: {event.order.price} RUB\n"
            f"Ordered: {units} pcs.\n"
            f"Rental time: {duration_label}\n"
            f"Note: specific account '{account['account_name']}' issued for {duration_label}",
        )

        acc.send_message(
            chat_id,
            "Ваш аккаунт:\n"
            f"ID: {account['id']}\n"
            f"Название: {account['account_name']}\n"
            f"Логин: {account['login']}\n"
            f"Пароль: {account['password']}\n"
            f"Аренда: {duration_label}\n\n"
            "Команды:\n"
            "!акк — данные аккаунта\n"
            "!код — код Steam Guard\n"
            "!сток — наличие\n\n"
            "Если нужна помощь — напишите в чат.",
        )

        acc.confirm(event.order.id)

    def _handle_new_message(self, event: Any) -> None:
        if self._acc is None:
            return
        acc = self._acc
        chat = acc.get_chat_by_name(event.message.author, True)

        if event.message.author_id == acc.id:
            return

        logger.info(f"{event.message.author} : {event.message.text}")
        raw_text = event.message.text.strip()
        message_text = raw_text.lower()

        if message_text and not message_text.startswith("!"):
            if self._try_handle_pending_choice(acc, chat.id, event.message.author, raw_text):
                return

        if message_text in ("!code", "!код"):
            self._handle_code(acc, chat.id, event.message.author)
            return

        if message_text in ("!acc", "!акк"):
            self._handle_acc(acc, chat.id, event.message.author)
            return

        if message_text == "!bonus":
            self._handle_bonus(acc, chat.id, event.message.author)
            return

        if message_text.startswith("!extend") or message_text.startswith("!продлить"):
            self._handle_extend(acc, chat.id, event.message.author, raw_text)
            return

        if message_text in ("!stock", "!сток"):
            self._handle_stock(acc, chat.id)
            return

        if message_text.startswith("!отмена"):
            self._handle_cancel(acc, chat.id, event.message.author, raw_text)
            return

    def _try_handle_pending_choice(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> bool:
        if owner in self._pending_account_choice:
            accounts = self._pending_account_choice[owner]
            choice = match_account_choice(raw_text, accounts)
            if choice:
                current_time = datetime.now(tz=MOSCOW_TZ)
                _, expiry_str, remaining_str = get_remaining_time(choice, current_time)
                acc.send_message(
                    chat_id,
                    USER.account_details_header
                    + f"ID: {choice['id']}\n"
                    + f"Аккаунт: {choice['account_name']}\n"
                    + f"Логин: {choice['login']}\n"
                    + f"Пароль: {choice['password']}\n"
                    + f"Истекает: {expiry_str} МСК | Осталось: {remaining_str}",
                )
                self._pending_account_choice.pop(owner, None)
            else:
                acc.send_message(chat_id, USER.choice_not_understood)
            return True

        return False

    def _handle_code(self, acc: Account, chat_id: int, owner: str) -> None:
        try:
            owner_data = self._db.get_owner_mafile(owner)
            if owner_data:
                lines = ["Коды Steam Guard:"]
                for account in owner_data:
                    (
                        _account_id,
                        account_name,
                        mafile_path,
                        mafile_json,
                        login,
                        _rental_duration,
                    ) = account
                    guard_code = get_steam_guard_code(
                        mafile_path=mafile_path,
                        mafile_json=mafile_json,
                    )
                    lines.append(f"{account_name} ({login}): {guard_code}")
                acc.send_message(chat_id, "\n".join(lines))
            else:
                acc.send_message(chat_id, USER.active_rentals_empty)
        except Exception as exc:
            acc.send_message(chat_id, f"Ошибка при получении кода: {exc}")

    def _handle_acc(self, acc: Account, chat_id: int, owner: str) -> None:
        try:
            accounts = self._db.get_user_active_accounts(owner)
            if not accounts:
                acc.send_message(chat_id, USER.active_rentals_empty)
                return

            current_time = datetime.now(tz=MOSCOW_TZ)
            if len(accounts) == 1:
                account = accounts[0]
                _, expiry_str, remaining_str = get_remaining_time(account, current_time)
                acc.send_message(
                    chat_id,
                    USER.account_details_header
                    + f"ID: {account['id']}\n"
                    + f"Аккаунт: {account['account_name']}\n"
                    + f"Логин: {account['login']}\n"
                    + f"Пароль: {account['password']}\n"
                    + f"Истекает: {expiry_str} МСК | Осталось: {remaining_str}",
                )
                return

            lines = [USER.choose_account_prompt]
            for account in accounts:
                _, _, remaining_str = get_remaining_time(account, current_time)
                lines.append(f"{account['id']}) {account['account_name']} ({account['login']}) — осталось {remaining_str}")
            self._pending_account_choice[owner] = accounts
            acc.send_message(chat_id, "\n".join(lines))
        except Exception as exc:
            logger.error(f"Failed to send account details to {owner}: {exc}")
            acc.send_message(chat_id, USER.acc_failed)

    def _handle_bonus(self, acc: Account, chat_id: int, owner: str) -> None:
        try:
            if owner in self._feedback_given:
                acc.send_message(chat_id, USER.bonus_already_given)
                return
            if owner not in self._bonus_eligible:
                if self._has_feedback_in_chat(owner):
                    self._bonus_eligible.add(owner)
                else:
                    acc.send_message(
                        chat_id,
                        f"Оставьте отзыв и напишите !bonus, чтобы добавить +{HOURS_FOR_REVIEW} ч к вашей аренде как бонус.",
                    )
                    return

            accounts = self._db.get_user_active_accounts(owner)
            if not accounts:
                acc.send_message(chat_id, USER.active_rentals_empty)
                return

            extended = 0
            for account in accounts:
                if self._db.extend_rental_duration(account["id"], HOURS_FOR_REVIEW):
                    extended += 1
            self._feedback_given.add(owner)
            self._bonus_eligible.discard(owner)
            acc.send_message(chat_id, f"Бонус начислен. +{HOURS_FOR_REVIEW} ч.\nПродлено аренд: {extended}.")
        except Exception as exc:
            logger.error(f"Failed to apply bonus for {owner}: {exc}")
            acc.send_message(chat_id, USER.bonus_failed)

    def _handle_extend(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> None:
        try:
            parts = raw_text.split()
            if len(parts) == 1:
                accounts = self._db.get_user_active_lot_accounts(owner)
                if not accounts:
                    acc.send_message(chat_id, USER.active_rentals_empty)
                    return

                current_time = datetime.now(tz=MOSCOW_TZ)
                lines = [
                    "Чтобы продлить аренду, оплатите нужный лот и укажите количество часов.",
                    "Команда: !продлить <часы> <номер_лота>",
                    "",
                    "Ваши активные аренды:",
                ]
                for account in accounts:
                    _, expiry_str, remaining_str = get_remaining_time(account, current_time)
                    lot_number = account.get("lot_number")
                    lot_url = account.get("lot_url")
                    if lot_number:
                        line = f"Лот №{lot_number}: {account['account_name']} — истекает {expiry_str} МСК (осталось {remaining_str})"
                        if lot_url:
                            line += f" — {lot_url}"
                        lines.append(line)
                    else:
                        lines.append(
                            f"ID {account['id']}: {account['account_name']} — лот не настроен (напишите администратору)."
                        )
                acc.send_message(chat_id, "\n".join(lines))
                return

            if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
                acc.send_message(chat_id, "Использование: !продлить <часы> <номер_лота>")
                return

            hours = int(parts[1])
            lot_number = int(parts[2])
            if hours <= 0:
                acc.send_message(chat_id, USER.extend_hours_positive)
                return
            if lot_number <= 0:
                acc.send_message(chat_id, "Номер лота должен быть больше 0.")
                return

            mapping = self._db.get_lot_mapping(lot_number)
            if not mapping:
                acc.send_message(chat_id, f"Лот №{lot_number} не привязан к аккаунту. Напишите администратору.")
                return

            lot_url = mapping.get("lot_url")
            link_line = f"\nСсылка: {lot_url}" if lot_url else ""
            acc.send_message(
                chat_id,
                f"Оплатите лот №{lot_number} в количестве {hours} шт, чтобы продлить аренду на {hours} ч."
                f"{link_line}\n\nПосле оплаты бот автоматически продлит аренду.",
            )
            self._pending_lot_extend[owner] = PendingLotExtend(
                hours=hours, lot_number=lot_number, created_ts=time.time()
            )
        except Exception as exc:
            logger.error(f"Failed to extend rental for {owner}: {exc}")
            acc.send_message(chat_id, USER.extend_failed)

    def _handle_stock(self, acc: Account, chat_id: int) -> None:
        try:
            available_lots = self._db.get_available_lot_accounts()
            if available_lots:
                lines = [USER.stock_title]
                for account in available_lots:
                    lot_label = f"№{account['lot_number']}"
                    lot_url = account.get("lot_url")
                    if lot_url:
                        lines.append(f"{account['account_name']} - {lot_label} - {lot_url}")
                    else:
                        lines.append(f"{account['account_name']} - {lot_label}")
                acc.send_message(chat_id, "\n".join(lines))
                return

            all_lots = self._db.get_all_lot_accounts()
            if not all_lots:
                acc.send_message(chat_id, USER.stock_no_lots_configured)
                return

            current_time = datetime.now(tz=MOSCOW_TZ)
            next_expiry = self._find_next_expiry(all_lots)
            if not next_expiry:
                acc.send_message(chat_id, "Свободных лотов нет. Не удалось определить время освобождения.")
                return

            remaining = next_expiry - current_time
            if remaining.total_seconds() < 0:
                remaining = timedelta(0)
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            acc.send_message(
                chat_id,
                "Свободных лотов нет. Ближайший освободится через "
                f"{hours} ч {minutes} мин (в {next_expiry.strftime('%H:%M:%S')} МСК).",
            )
        except Exception as exc:
            logger.error(f"Failed to load stock: {exc}")
            acc.send_message(chat_id, USER.stock_failed)

    def _handle_cancel(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> None:
        try:
            accounts = self._db.get_user_active_accounts(owner)
            if not accounts:
                acc.send_message(chat_id, USER.active_rentals_empty)
                return

            parts = raw_text.split()
            if len(parts) < 2:
                lines = [
                    "Выберите аренду для отмены.",
                    "Команда: !отмена <ID>",
                    "",
                    "Активные аренды:",
                ]
                current_time = datetime.now(tz=MOSCOW_TZ)
                for account in accounts:
                    _, _, remaining_str = get_remaining_time(account, current_time)
                    lines.append(f"ID {account['id']}: {account['account_name']} — осталось {remaining_str}")
                acc.send_message(chat_id, "\n".join(lines))
                return

            if not parts[1].isdigit():
                acc.send_message(chat_id, "Использование: !отмена <ID>")
                return

            account_id = int(parts[1])
            account = next((item for item in accounts if item["id"] == account_id), None)
            if not account:
                acc.send_message(chat_id, "Аккаунт с таким ID не найден в ваших активных арендах.")
                return

            acc.send_message(chat_id, "Отмена аренды... Это может занять некоторое время.")
            deauth_ok = False
            try:
                deauth_ok = asyncio.run(
                    logout_all_steam_sessions(
                        steam_login=account.get("login") or account.get("account_name") or "",
                        steam_password=account.get("password") or "",
                        mafile_json=account.get("mafile_json") or "",
                    )
                )
            except Exception as exc:
                logger.warning(f"Failed to deauthorize Steam sessions for account {account_id}: {exc}")

            self._db.release_account(account_id)
            self._db.update_account(
                account_id,
                {"rental_duration": 1, "rental_duration_minutes": 60},
            )

            send_message_to_admin(
                "RENTAL CANCELLED\n\n"
                f"Account ID: {account_id}\n"
                f"Owner: {owner}\n"
                f"Deauthorize: {'ok' if deauth_ok else 'failed'}\n"
            )
            acc.send_message(chat_id, "Аренда отменена. Доступ закрыт.")
        except Exception as exc:
            logger.error(f"Failed to cancel rental for {owner}: {exc}")
            acc.send_message(chat_id, USER.extend_failed)

    def _find_next_expiry(self, all_lots: list[dict]) -> datetime | None:
        current_time = datetime.now(tz=MOSCOW_TZ)
        next_expiry = None
        for account in all_lots:
            if account.get("owner") is None:
                continue
            rental_start = account.get("rental_start")
            duration_minutes = get_duration_minutes(account)
            if not rental_start or duration_minutes <= 0:
                continue

            if isinstance(rental_start, datetime):
                start_dt = rental_start
            else:
                try:
                    start_dt = datetime.strptime(rental_start, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

            if start_dt.tzinfo is None:
                start_dt = MOSCOW_TZ.localize(start_dt)

            expiry_time = start_dt + timedelta(minutes=duration_minutes)
            if next_expiry is None or expiry_time < next_expiry:
                next_expiry = expiry_time

        if next_expiry and next_expiry < current_time:
            return current_time
        return next_expiry

    def _handle_new_feedback(self, event: Any) -> None:
        try:
            message = getattr(event, "message", None)
            owner = None
            if message is not None:
                owner = message.initiator_username or message.author
            if owner and owner not in self._feedback_given:
                self._bonus_eligible.add(owner)
                if self._acc is None:
                    return
                chat = self._acc.get_chat_by_name(owner, True)
                self._acc.send_message(
                    chat.id,
                    f"Спасибо за отзыв! Напишите !bonus, чтобы получить +{HOURS_FOR_REVIEW} ч.",
                )
        except Exception as exc:
            logger.error(f"Error handling NEW_FEEDBACK event: {exc}")

    def _check_rental_expiration_loop(self) -> None:
        logger.info("Starting rental expiration checker...")
        invalid_accs: list[int] = []
        while True:
            try:
                self._check_rental_expiration_once(invalid_accs)
            except Exception as exc:
                logger.error(f"Error in rental expiration checker: {exc}")
            time.sleep(RENTAL_CHECK_INTERVAL)

    def _check_rental_expiration_once(self, invalid_accs: list[int]) -> None:
        conn, cursor = self._db.open_connection()
        try:
            current_time = datetime.now(tz=MOSCOW_TZ)
            cursor.execute(
                """
                SELECT a.ID, a.owner, a.rental_start, a.rental_duration, a.rental_duration_minutes, a.path_to_maFile, a.mafile_json, a.password, a.login, a.account_name
                FROM accounts a
                WHERE a.owner IS NOT NULL
                AND a.rental_start IS NOT NULL
                """
            )
            accounts_data = cursor.fetchall()

            for row in accounts_data:
                (
                    account_id,
                    owner,
                    start_time,
                    duration,
                    duration_minutes,
                    mafile_path,
                    mafile_json,
                    password,
                    login,
                    account_name,
                ) = row
                if not owner:
                    continue

                if isinstance(start_time, datetime):
                    start_datetime = start_time
                else:
                    start_datetime = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
                start_datetime = MOSCOW_TZ.localize(start_datetime)
                try:
                    total_minutes = int(duration_minutes) if duration_minutes is not None else int(duration) * 60
                except Exception:
                    total_minutes = 0
                if total_minutes <= 0:
                    continue
                expiry_time = start_datetime + timedelta(minutes=total_minutes)

                time_remaining = expiry_time - current_time
                minutes_remaining = time_remaining.total_seconds() / 60
                start_key = f"{start_datetime.isoformat()}|{total_minutes}"
                if self._expire_warning_start.get(account_id) != start_key:
                    self._expire_warning_start[account_id] = start_key
                    self._expire_warning_sent.pop(account_id, None)

                sent = self._expire_warning_sent.setdefault(account_id, set())
                if 5 < minutes_remaining <= 10 and 10 not in sent:
                    self._send_expiration_warning(owner, account_id, minutes_remaining, expiry_time, 10)
                    sent.add(10)
                if 0 < minutes_remaining <= 5 and 5 not in sent:
                    self._send_expiration_warning(owner, account_id, minutes_remaining, expiry_time, 5)
                    sent.add(5)

                if current_time >= expiry_time and account_id not in invalid_accs:
                    steam_login = login or account_name
                    if self._should_delay_expire_due_to_dota_match(
                        account_id=account_id,
                        owner=owner,
                        current_time=current_time,
                        mafile_json=mafile_json,
                    ):
                        continue
                    self._expire_rental(
                        cursor=cursor,
                        conn=conn,
                        invalid_accs=invalid_accs,
                        owner=owner,
                        account_id=account_id,
                        mafile_path=mafile_path,
                        mafile_json=mafile_json,
                        password=password,
                        steam_login=steam_login,
                        expiry_time=expiry_time,
                    )

            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def _steamid64_from_mafile(self, mafile_json: str | None) -> int | None:
        if not mafile_json:
            return None
        try:
            data = json.loads(mafile_json) if isinstance(mafile_json, str) else mafile_json
            value = (data or {}).get("Session", {}).get("SteamID")
            if value is None:
                value = (data or {}).get("steamid") or (data or {}).get("SteamID")
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    def _should_delay_expire_due_to_dota_match(
        self,
        *,
        account_id: int,
        owner: str,
        current_time: datetime,
        mafile_json: str | None,
    ) -> bool:
        if not DOTA_MATCH_DELAY_EXPIRE:
            return False
        bot = get_presence_bot()
        if bot is None:
            return False

        steamid64 = self._steamid64_from_mafile(mafile_json)
        if steamid64 is None:
            return False

        snapshot = bot.get_cached(steamid64)
        if snapshot is None:
            try:
                snapshot = asyncio.run(bot.fetch_presence(steamid64))
            except Exception:
                snapshot = None

        if not snapshot or not snapshot.in_match:
            self._expire_delay_since.pop(account_id, None)
            self._expire_delay_notified.discard(account_id)
            return False

        since = self._expire_delay_since.get(account_id)
        if since is None:
            self._expire_delay_since[account_id] = current_time
            since = current_time

        if current_time - since >= timedelta(minutes=DOTA_MATCH_GRACE_MINUTES):
            self._expire_delay_since.pop(account_id, None)
            self._expire_delay_notified.discard(account_id)
            return False

        if account_id not in self._expire_delay_notified:
            steam_display = snapshot.rich_presence.get("steam_display") if snapshot.rich_presence else None
            extra = f"\nСтатус: {steam_display}\n" if steam_display else ""
            try:
                self.send_message_by_owner(
                    owner,
                    "Ваша аренда уже закончилась, но вы сейчас в матче Dota 2.\n"
                    f"Я подожду до {DOTA_MATCH_GRACE_MINUTES} минут и затем автоматически закрою доступ.\n"
                    f"{extra}",
                )
            except Exception:
                pass
            try:
                send_message_to_admin(
                    "EXPIRE DELAYED (DOTA MATCH)\n\n"
                    f"Account ID: {account_id}\n"
                    f"Owner: {owner}\n"
                    f"steam_display: {steam_display}\n"
                    f"Grace: {DOTA_MATCH_GRACE_MINUTES} minutes\n",
                )
            except Exception:
                pass
            self._expire_delay_notified.add(account_id)

        return True

    def _should_delay_expire_due_to_in_game(self, mafile_json: str | None) -> bool:
        steamid64 = self._steamid64_from_mafile(mafile_json)
        if steamid64 is None:
            return False
        try:
            presence = fetch_web_presence(steamid64)
            return bool(presence.get("in_game"))
        except Exception:
            return False

    def _send_expiration_warning(
        self,
        owner: str,
        account_id: int,
        minutes_remaining: float,
        expiry_time: datetime,
        reminder_minutes: int,
    ) -> None:
        try:
            remaining_minutes = max(int(minutes_remaining), 0)
            send_message_to_admin(
                "EXPIRATION WARNING!\n\n"
                f"Account ID: {account_id}\n"
                f"Owner: {owner}\n"
                f"Time left: ~{remaining_minutes} minutes\n"
                f"Reminder: {reminder_minutes} minutes\n"
                "Tip: user will lose access soon!",
            )
            self.send_message_by_owner(
                owner,
                f"Внимание! Ваша аренда скоро закончится (~{reminder_minutes} минут).\n\n"
                f"ID аккаунта: {account_id}\n"
                f"Осталось: ~{remaining_minutes} мин\n"
                "Если нужно продление — напишите в чат на FunPay.\n\n"
                "Команды:\n"
                "!акк — данные аккаунта\n"
                "!код — код Steam Guard\n\n"
                f"Окончание: {expiry_time.strftime('%H:%M:%S')} МСК",
            )
        except Exception as exc:
            logger.error(f"Failed to send warning notification: {exc}")

    def _expire_rental(
        self,
        cursor: Any,
        conn: Any,
        invalid_accs: list[int],
        owner: str,
        account_id: int,
        mafile_path: str,
        mafile_json: str,
        password: str,
        steam_login: str,
        expiry_time: datetime,
    ) -> None:
        logger.info(f"Account {account_id} rental expired.")
        self._expire_warning_sent.pop(account_id, None)
        self._expire_warning_start.pop(account_id, None)
        try:
            deauth_ok = False
            if AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE:
                try:
                    deauth_ok = asyncio.run(
                        logout_all_steam_sessions(
                            steam_login=steam_login,
                            steam_password=password,
                            mafile_json=mafile_json,
                        )
                    )
                except Exception as exc:
                    logger.warning(f"Failed to deauthorize Steam sessions for account {account_id}: {exc}")

            new_password = asyncio.run(
                changeSteamPassword(
                    path_to_maFile=mafile_path,
                    password=password,
                    mafile_json=mafile_json,
                )
            )
            send_message_to_admin(
                "RENTAL EXPIRED\n\n"
                f"Account ID: {account_id}\n"
                f"Owner: {owner}\n"
                f"Deauthorize: {'ok' if deauth_ok else 'failed'}\n"
                f"New password: {new_password}\n"
                f"Expired at: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}",
            )

            cursor.execute(
                """
                UPDATE accounts
                SET password = ?, owner = NULL, rental_start = NULL, rental_duration = 1, rental_duration_minutes = 60
                WHERE ID = ?
                """,
                (new_password, account_id),
            )
            conn.commit()

            try:
                self.send_message_by_owner(
                    owner,
                    "Срок аренды истёк.\n\n"
                    f"ID аккаунта: {account_id}\n"
                    "Доступ закрыт, пароль изменён.\n"
                    "Если нужна помощь или продление — напишите в чат.",
                )
            except Exception as exc:
                logger.error(f"Failed to send expiration notification: {exc}")
        except Exception as exc:
            logger.error(f"Failed to expire account {account_id}: {exc}")
            try:
                send_message_to_admin(
                    "RENTAL EXPIRED (PARTIAL)\n\n"
                    f"Account ID: {account_id}\n"
                    f"Owner: {owner}\n"
                    "Result: password rotation failed; owner cleared anyway\n"
                    f"Error: {exc}\n",
                )
            except Exception:
                pass

            try:
                cursor.execute(
                    """
                    UPDATE accounts
                    SET owner = NULL, rental_start = NULL, rental_duration = 1, rental_duration_minutes = 60
                    WHERE ID = ?
                    """,
                    (account_id,),
                )
                conn.commit()
            except Exception as exc2:
                logger.error(f"Failed to clear expired rental state for account {account_id}: {exc2}")
                invalid_accs.append(account_id)
