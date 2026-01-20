# Standard library imports
import random
import time
import asyncio
import threading
import re
from datetime import datetime, timedelta

# Third-party imports
from FunPayAPI import Account, Runner, types, enums, events

# Project-specific imports
from config import (
    FUNPAY_GOLDEN_KEY,
    HOURS_FOR_REVIEW,
    RENTAL_CHECK_INTERVAL,
)

from databaseHandler.databaseSetup import SQLiteDB
from steamHandler.SteamGuard import get_steam_guard_code
from steamHandler.changePassword import changeSteamPassword
from logger import logger
from notifications import send_message_to_admin
from pytz import timezone


TOKEN = FUNPAY_GOLDEN_KEY
REFRESH_INTERVAL = 1300  # 30 minutes in seconds

feedbackGiven = set()
bonusEligible = set()
pendingAccountChoice = {}
pendingExtendChoice = {}

moscow_tz = timezone("Europe/Moscow")

db = SQLiteDB()
acc = None
runner = None


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
    match = re.search(r"(?:№|#)\s*(\\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None



def normalize_choice_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def get_remaining_time(account: dict, current_time: datetime):
    rental_start = account.get("rental_start")
    if not rental_start:
        return None, "неизвестно", "неизвестно"
    if isinstance(rental_start, datetime):
        start_dt = rental_start
    else:
        start_dt = datetime.strptime(rental_start, "%Y-%m-%d %H:%M:%S")
    if start_dt.tzinfo is None:
        start_dt = moscow_tz.localize(start_dt)
    expiry_time = start_dt + timedelta(hours=int(account["rental_duration"]))
    remaining = expiry_time - current_time
    if remaining.total_seconds() < 0:
        remaining = timedelta(0)
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    remaining_str = f"{hours} ч {minutes} мин"
    expiry_str = expiry_time.strftime("%H:%M:%S")
    return expiry_time, expiry_str, remaining_str


def match_account_choice(choice: str, accounts: list[dict]):
    choice = normalize_choice_text(choice)
    if not choice:
        return None
    if choice.isdigit():
        account_id = int(choice)
        for account in accounts:
            if account["id"] == account_id:
                return account
    for account in accounts:
        if normalize_choice_text(account.get("account_name", "")) == choice:
            return account
        if normalize_choice_text(account.get("login", "")) == choice:
            return account
    return None
def refresh_session():
    global acc, runner
    logger.info("Refreshing FunPay session...")
    acc = Account(TOKEN).get()
    runner = Runner(acc)
    logger.info("FunPay session refreshed successfully.")


def check_rental_expiration():
    """Checks for expired rentals and changes passwords every minute"""
    logger.info("Starting rental expiration checker...")
    invalid_accs = []
    while True:
        try:
            conn, cursor = db.open_connection()

            current_time = datetime.now(tz=moscow_tz)

            # Get all active rentals with their maFile paths
            cursor.execute(
                """
                SELECT a.ID, a.owner, a.rental_start, a.rental_duration, a.path_to_maFile, a.mafile_json, a.password
                FROM accounts a
                WHERE a.owner IS NOT NULL 
                AND a.rental_start IS NOT NULL
                """
            )

            accounts_data = cursor.fetchall()

            for row in accounts_data:
                account_id, owner, start_time, duration, mafile_path, mafile_json, password = row
                logger.debug(f"Processing account ID: {account_id}, Owner: {owner}")

                if isinstance(start_time, datetime):
                    start_datetime = start_time
                else:
                    start_datetime = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
                start_datetime = moscow_tz.localize(start_datetime)
                expiry_time = start_datetime + timedelta(hours=int(duration))
                
                # Calculate time remaining
                time_remaining = expiry_time - current_time
                hours_remaining = time_remaining.total_seconds() / 3600

                logger.debug(
                    f"Start time: {start_datetime}, Expiry time: {expiry_time}, Current time: {current_time}, Hours remaining: {hours_remaining:.2f}"
                )

                # Send warning notifications
                if 0.1 <= hours_remaining <= 0.2:
                    try:
                        send_message_to_admin(
                            "EXPIRATION WARNING!\n\n"
                            f"Account ID: {account_id}\n"
                            f"Owner: {owner}\n"
                            f"Time left: {hours_remaining:.1f} hours (~{int(hours_remaining * 60)} minutes)\n"
                            "Tip: user will lose access soon!"
                        )
                        
                        send_message_by_owner(
                            owner,
                            f"Внимание! Аренда скоро закончится (~10 минут).\n\n"
                            f"ID аккаунта: {account_id}\n"
                            f"Осталось: ~{int(hours_remaining * 60)} мин\n"
                            f"Если оставите отзыв на FunPay — добавим +{HOURS_FOR_REVIEW} ч.\n\n"
                            f"Команды:\n"
                            f"!acc — данные аккаунта\n"
                            f"!code — код Steam Guard\n\n"
                            f"Окончание: {expiry_time.strftime('%H:%M:%S')} МСК"
                        )
                        logger.info(f"Warning notification sent to {owner} for account {account_id} - {hours_remaining:.1f} hours remaining")
                    except Exception as e:
                        logger.error(f"Failed to send warning notification: {str(e)}")

                # Check if expired
                if current_time >= expiry_time and account_id not in invalid_accs:
                    logger.info(
                        f"Account {account_id} rental expired. Time difference: {current_time - expiry_time}"
                    )
                    try:
                        new_password = asyncio.run(
                            changeSteamPassword(
                                path_to_maFile=mafile_path,
                                password=password,
                                mafile_json=mafile_json,
                            )
                        )
                        logger.info(
                            f"Password changed successfully for account {account_id}. New password: {new_password}"
                        )
                        send_message_to_admin(
                            "RENTAL EXPIRED\n\n"
                            f"Account ID: {account_id}\n"
                            f"Owner: {owner}\n"
                            f"New password: {new_password}\n"
                            f"Expired at: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}"
                        )

                        # Update password and nullify all accounts with the same login
                        logger.debug(f"Updating database for account {account_id}...")
                        cursor.execute(
                            """
                            UPDATE accounts
                            SET password = ?, owner = NULL, rental_start = NULL, rental_duration = 1
                            WHERE login = (
                                SELECT login
                                FROM accounts
                                WHERE ID = ?
                            )
                            """,
                            (new_password, account_id),
                        )
                        logger.info(f"Database updated for account {account_id}.")

                        try:
                            send_message_by_owner(
                                owner,
                                f"Срок аренды истёк.\n\n"
                                f"ID аккаунта: {account_id}\n"
                                f"Доступ закрыт, пароль изменён.\n"
                                f"Если нужна помощь или продление — напишите в чат."
                            )
                            logger.info(
                                f"Expiration notification sent to user {owner}."
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to send expiration notification: {str(e)}"
                            )

                    except Exception as e:
                        logger.error(
                            f"Failed to change password for account {account_id}: {str(e)}"
                        )
                        invalid_accs.append(account_id)

                        continue

            conn.commit()
            cursor.close()
            conn.close()

        except Exception as e:
            logger.error(f"Error in rental expiration checker: {str(e)}")

        time.sleep(RENTAL_CHECK_INTERVAL)


def startFunpay():
    global acc, runner

    logger.info("Starting FunPay bot...")
    if not TOKEN:
        logger.error("FUNPAY_GOLDEN_KEY is missing. FunPay automation stopped.")
        return
    acc = Account(TOKEN).get()
    runner = Runner(acc)
    logger.info("FunPay account and runner initialized.")
    last_refresh = time.time()

    logger.info("Starting rental expiration checker thread...")

    timerChecker_thread = threading.Thread(target=check_rental_expiration).start()

    for event in runner.listen(requests_delay=8):
        try:
            current_time = time.time()
            if current_time - last_refresh >= REFRESH_INTERVAL:
                logger.info("Refreshing session due to interval timeout...")
                refresh_session()
                last_refresh = current_time

            if event.type is events.EventTypes.NEW_ORDER:
                logger.info("Processing new order event...")

                accounts = db.get_unowned_accounts()

                acc = Account(TOKEN).get()
                chat = acc.get_chat_by_name(event.order.buyer_username, True)

                all_accounts = db.get_all_account_names()

                order_name = event.order.description
                number_of_orders = event.order.amount

                logger.info(f"Original order name: {order_name}")
                lot_number = parse_lot_number(order_name)
                if lot_number is not None:
                    specific_account = db.get_account_by_lot_number(lot_number)
                    if not specific_account:
                        acc.send_message(
                            chat.id,
                            "Лот не привязан к аккаунту. Дождитесь ответа администратора.",
                        )
                        send_message_to_admin(
                            "ЛОТ БЕЗ ПРИВЯЗКИ\n\n"
                            f"Покупатель: {event.order.buyer_username}\n"
                            f"Лот: №{lot_number}\n"
                            f"Заказ: {event.order.id}"
                        )
                        continue
                    order_name = specific_account["account_name"]
                    logger.info(f"Matched lot number: {lot_number} -> {order_name}")
                else:
                    matched_account = match_account_name(order_name, all_accounts)
                    if matched_account:
                        order_name = matched_account
                        logger.info(f"Matched order name: {order_name}")
                    else:
                        logger.warning(f"No matching account found for order: {order_name}")
                        continue

                if order_name in all_accounts:
                    logger.info(f"New order: {order_name}")

                    if number_of_orders > 1:
                        acc.send_message(
                            chat.id,
                            f"Вы оплатили {number_of_orders} шт. '{order_name}'.\n"
                            f"Система выдаёт 1 аккаунт на {number_of_orders} часов (1 шт = 1 час).\n\n"
                            f"Если нужен другой вариант — напишите в чат."
                        )
                        logger.info(f"User {event.order.buyer_username} ordered {number_of_orders} accounts but will receive only 1 for {number_of_orders} hours")

                    if lot_number is None:
                        specific_account = db.get_account_by_name(order_name)
                    
                    if not specific_account:
                        logger.error(f"Account with name '{order_name}' not found in database")
                        acc.send_message(
                            chat.id,
                            f"Ошибка: аккаунт '{order_name}' не найден.\n"
                            f"Возврат оформлен. Напишите, поможем."
                        )
                        continue
                    
                    if specific_account['owner'] is not None:
                        logger.warning(f"Account '{order_name}' is already rented by {specific_account['owner']}")
                        acc.send_message(
                            chat.id,
                            "???? ??????? ?????? ?????.\n"
                            "????????? ?????????????? ??? ????????, ????? ??????? ???????."
                        )
                        continue
                    
                    existing_rentals = db.get_user_accounts_by_name(event.order.buyer_username, order_name)
                    
                    if existing_rentals:
                        logger.info(f"User {event.order.buyer_username} already has active rental for {order_name}, extending by {number_of_orders} hours...")
                        
                        rental = existing_rentals[0]
                        db.extend_rental_duration(rental['id'], number_of_orders)
                        
                        acc.send_message(
                            chat.id,
                            f"Аренда продлена!\n\n"
                            f"Тип аккаунта: {order_name}\n"
                            f"Продление: +{number_of_orders} ч\n"
                            f"ID: {rental['id']}\n\n"
                            f"Данные аккаунта ниже."
                        )
                        
                        account = db.get_account_by_id(rental['id'])
                        if account:
                            rental_start = account['rental_start']
                            if isinstance(rental_start, datetime):
                                start_dt = rental_start
                            else:
                                start_dt = datetime.strptime(rental_start, "%Y-%m-%d %H:%M:%S")
                            expiry_time = start_dt + timedelta(hours=int(account['rental_duration']))
                            acc.send_message(
                                chat.id,
                                f"ID: {rental['id']}\n"
                                f"Логин: {rental['login']}\n"
                                f"Пароль: {rental['password']}\n"
                                f"Истекает: {expiry_time.strftime('%H:%M:%S')} МСК\n"
                                f"Команды: !acc, !code"
                            )
                        
                        send_message_to_admin(
                            "RENTAL EXTENDED\n\n"
                            f"User: {event.order.buyer_username}\n"
                            f"Account type: {order_name}\n"
                            f"Extension: +{number_of_orders} hours\n"
                            f"Price: {event.order.price} RUB\n"
                            f"Account ID: {rental['id']}\n"
                            "Note: user already had an active rental"
                        )
                        
                        acc.confirm(event.order.id)
                        
                    else:
                        logger.info(f"Assigning specific account '{order_name}' to user {event.order.buyer_username}")
                        
                        db.set_account_owner(
                            specific_account["id"], event.order.buyer_username
                        )
                        
                        conn, cursor = db.open_connection()
                        cursor.execute(
                            """
                            UPDATE accounts
                            SET rental_duration = ?
                            WHERE ID = ?
                            """,
                            (number_of_orders, specific_account["id"]),
                        )
                        conn.commit()
                        cursor.close()
                        conn.close()
                        
                        send_message_to_admin(
                            "NEW ACCOUNT ISSUED\n\n"
                            f"Buyer: {event.order.buyer_username}\n"
                            f"ID: {specific_account['id']}\n"
                            f"Account name: {specific_account['account_name']}\n"
                            f"Login: {specific_account['login']}\n"
                            f"Password: {specific_account['password']}\n"
                            f"Price: {event.order.price} RUB\n"
                            f"Ordered: {number_of_orders} pcs.\n"
                            f"Rental time: {number_of_orders} hours\n"
                            f"Note: specific account '{order_name}' issued for {number_of_orders} hours"
                        )

                        acc.send_message(
                            chat.id,
                            text=f"Ваш аккаунт:\n"
                            f"ID: {specific_account['id']}\n"
                            f"Название: {specific_account['account_name']}\n"
                            f"Логин: {specific_account['login']}\n"
                            f"Пароль: {specific_account['password']}\n"
                            f"Аренда: {number_of_orders} ч\n\n"
                            f"Команды:\n"
                            f"!acc — данные аккаунта\n"
                            f"!code — код Steam Guard\n"
                            f"!stock — наличие\n\n"
                            f"Если нужна помощь — напишите в чат."
                        )
                        
                        acc.confirm(event.order.id)
                        
                else:
                    logger.info(f"Item '{order_name}' not found in rentals; skipping.")
                    continue
                
                logger.info(f"New order processed successfully.")

            elif hasattr(events.EventTypes, "ORDER_PAID") and event.type is events.EventTypes.ORDER_PAID:
                order_name = event.order.description
                lot_number = parse_lot_number(order_name)
                matched_account = None
                if lot_number is not None:
                    specific_account = db.get_account_by_lot_number(lot_number)
                    if specific_account:
                        matched_account = specific_account["account_name"]
                if matched_account is None:
                    all_accounts = db.get_all_account_names()
                    matched_account = match_account_name(order_name, all_accounts)
                if matched_account:
                    logger.info(
                        f"Order paid for rental lot. Buyer: {event.order.buyer_username}, Lot: {matched_account}, Order ID: {event.order.id}"
                    )
                    send_message_to_admin(
                        "?????? ????????\n\n"
                        f"??????????: {event.order.buyer_username}\n"
                        f"???: {matched_account}\n"
                        f"?????: {event.order.id}\n"
                        f"?????: {event.order.price} ?"
                    )
                else:
                    logger.info(
                        f"Order paid for non-rental lot. Buyer: {event.order.buyer_username}, Order ID: {event.order.id}"
                    )
            if event.type is events.EventTypes.NEW_MESSAGE:
                logger.info("Processing new message event...")

                chat = acc.get_chat_by_name(event.message.author, True)

                if event.message.author_id != acc.id:

                    logger.info(f"{event.message.author} : {event.message.text}")

                    raw_text = event.message.text.strip()
                    message_text = raw_text.lower()
                    if message_text and not message_text.startswith("!"):
                        if event.message.author in pendingAccountChoice:
                            accounts = pendingAccountChoice[event.message.author]
                            choice = match_account_choice(raw_text, accounts)
                            if choice:
                                current_time = datetime.now(tz=moscow_tz)
                                _, expiry_str, remaining_str = get_remaining_time(choice, current_time)
                                acc.send_message(
                                    chat.id,
                                    "Данные аккаунта:\n"
                                    f"ID: {choice['id']}\n"
                                    f"Аккаунт: {choice['account_name']}\n"
                                    f"Логин: {choice['login']}\n"
                                    f"Пароль: {choice['password']}\n"
                                    f"Истекает: {expiry_str} МСК | Осталось: {remaining_str}",
                                )
                                pendingAccountChoice.pop(event.message.author, None)
                            else:
                                acc.send_message(chat.id, "Не понял выбор. Напишите ID или логин аккаунта.")
                            continue

                        if event.message.author in pendingExtendChoice:
                            pending = pendingExtendChoice[event.message.author]
                            choice = match_account_choice(raw_text, pending["accounts"])
                            if choice:
                                hours = pending["hours"]
                                success = db.extend_rental_duration(choice["id"], hours)
                                if success:
                                    account = db.get_account_by_id(choice["id"])
                                    current_time = datetime.now(tz=moscow_tz)
                                    _, expiry_str, remaining_str = get_remaining_time(account, current_time)
                                    acc.send_message(
                                        chat.id,
                                        f"Продлено на {hours} ч.\n"
                                        f"ID: {choice['id']}\n"
                                        f"Аккаунт: {choice['account_name']}\n"
                                        f"Истекает: {expiry_str} МСК | Осталось: {remaining_str}",
                                    )
                                else:
                                    acc.send_message(chat.id, "Не удалось продлить аренду. Попробуйте позже.")
                                pendingExtendChoice.pop(event.message.author, None)
                            else:
                                acc.send_message(chat.id, "Не понял выбор. Напишите ID или логин аккаунта.")
                            continue

                    if message_text == "!code":
                        try:
                            owner_data = db.get_owner_mafile(event.message.author)

                            if owner_data:
                                lines = ["???? Steam Guard:"]
                                for account in owner_data:
                                    (
                                        account_id,
                                        account_name,
                                        mafile_path,
                                        mafile_json,
                                        login,
                                        rental_duration,
                                    ) = account
                                    guard_code = get_steam_guard_code(
                                        mafile_path=mafile_path,
                                        mafile_json=mafile_json,
                                    )
                                    lines.append(f"{account_name} ({login}): {guard_code}")
                                acc.send_message(chat.id, "\n".join(lines))
                            else:
                                acc.send_message(chat.id, "???????? ????? ???.")
                        except Exception as e:
                            acc.send_message(
                                chat.id, f"?????? ??? ????????? ????: {str(e)}"
                            )
                    elif message_text == "!acc":
                        try:
                            accounts = db.get_user_active_accounts(event.message.author)

                            if not accounts:
                                acc.send_message(chat.id, "???????? ????? ???.")
                            elif len(accounts) == 1:
                                current_time = datetime.now(tz=moscow_tz)
                                account = accounts[0]
                                _, expiry_str, remaining_str = get_remaining_time(account, current_time)
                                acc.send_message(
                                    chat.id,
                                    "?????? ????????:\n"
                                    f"ID: {account['id']}\n"
                                    f"???????: {account['account_name']}\n"
                                    f"?????: {account['login']}\n"
                                    f"??????: {account['password']}\n"
                                    f"????????: {expiry_str} ??? | ????????: {remaining_str}",
                                )
                            else:
                                current_time = datetime.now(tz=moscow_tz)
                                lines = [
                                    "?? ?????? ???????? ?? ?? ?????? ???????? ??????? ???????? ID ??? ?????:",
                                ]
                                for account in accounts:
                                    _, _, remaining_str = get_remaining_time(account, current_time)
                                    lines.append(
                                        f"{account['id']}) {account['account_name']} ({account['login']}) ? ???????? {remaining_str}"
                                    )
                                pendingAccountChoice[event.message.author] = accounts
                                acc.send_message(chat.id, "\n".join(lines))
                        except Exception as e:
                            logger.error(
                                f"Failed to send account details to {event.message.author}: {str(e)}"
                            )
                            acc.send_message(
                                chat.id, "?? ??????? ???????? ?????? ????????."
                            )
                    elif message_text == "!bonus":
                        try:
                            owner = event.message.author
                            if owner in feedbackGiven:
                                acc.send_message(chat.id, "????? ??? ??? ???????????.")
                            elif owner not in bonusEligible:
                                acc.send_message(
                                    chat.id,
                                    "????? ?? ??????. ???????? ????? ? ???????? !bonus.",
                                )
                            else:
                                accounts = db.get_user_active_accounts(owner)
                                if not accounts:
                                    acc.send_message(chat.id, "???????? ????? ???.")
                                else:
                                    extended = 0
                                    for account in accounts:
                                        if db.extend_rental_duration(account["id"], HOURS_FOR_REVIEW):
                                            extended += 1
                                    feedbackGiven.add(owner)
                                    bonusEligible.discard(owner)
                                    acc.send_message(
                                        chat.id,
                                        f"????? ???????????. +{HOURS_FOR_REVIEW} ?.\n"
                                        f"???????? ?????????: {extended}.",
                                    )
                        except Exception as e:
                            logger.error(f"Failed to apply bonus for {event.message.author}: {str(e)}")
                            acc.send_message(chat.id, "?? ??????? ????????? ?????.")
                    elif message_text.startswith("!extend"):
                        try:
                            parts = raw_text.split()
                            if len(parts) < 2 or not parts[1].isdigit():
                                acc.send_message(chat.id, "???????????: !extend <????>")
                                continue
                            hours = int(parts[1])
                            if hours <= 0:
                                acc.send_message(chat.id, "?????????? ????? ?????? ???? ?????? 0.")
                                continue

                            accounts = db.get_user_active_accounts(event.message.author)
                            if not accounts:
                                acc.send_message(chat.id, "???????? ????? ???.")
                                continue

                            choice = None
                            if len(parts) >= 3:
                                choice_text = " ".join(parts[2:])
                                choice = match_account_choice(choice_text, accounts)

                            if choice:
                                success = db.extend_rental_duration(choice["id"], hours)
                                if success:
                                    account = db.get_account_by_id(choice["id"])
                                    current_time = datetime.now(tz=moscow_tz)
                                    _, expiry_str, remaining_str = get_remaining_time(account, current_time)
                                    acc.send_message(
                                        chat.id,
                                        f"???????? ?? {hours} ?.\n"
                                        f"ID: {choice['id']}\n"
                                        f"???????: {choice['account_name']}\n"
                                        f"????????: {expiry_str} ??? | ????????: {remaining_str}",
                                    )
                                else:
                                    acc.send_message(chat.id, "?? ??????? ???????? ??????.")
                            elif len(accounts) == 1:
                                account = accounts[0]
                                success = db.extend_rental_duration(account["id"], hours)
                                if success:
                                    current_time = datetime.now(tz=moscow_tz)
                                    _, expiry_str, remaining_str = get_remaining_time(account, current_time)
                                    acc.send_message(
                                        chat.id,
                                        f"???????? ?? {hours} ?.\n"
                                        f"ID: {account['id']}\n"
                                        f"???????: {account['account_name']}\n"
                                        f"????????: {expiry_str} ??? | ????????: {remaining_str}",
                                    )
                                else:
                                    acc.send_message(chat.id, "?? ??????? ???????? ??????.")
                            else:
                                current_time = datetime.now(tz=moscow_tz)
                                lines = [
                                    "????? ??????? ????????? ???????? ID ??? ?????:",
                                ]
                                for account in accounts:
                                    _, _, remaining_str = get_remaining_time(account, current_time)
                                    lines.append(
                                        f"{account['id']}) {account['account_name']} ({account['login']}) ? ???????? {remaining_str}"
                                    )
                                pendingExtendChoice[event.message.author] = {
                                    "hours": hours,
                                    "accounts": accounts,
                                }
                                acc.send_message(chat.id, "\n".join(lines))
                        except Exception as e:
                            logger.error(f"Failed to extend rental for {event.message.author}: {str(e)}")
                            acc.send_message(chat.id, "?? ??????? ???????? ??????.")
                    elif message_text == "!stock":
                        try:
                            available_lots = db.get_available_lot_accounts()
                            if available_lots:
                                lines = ["????????? ????:"]
                                for account in available_lots:
                                    lot_label = f"?{account['lot_number']}"
                                    lot_url = account.get("lot_url")
                                    if lot_url:
                                        lines.append(f"{account['account_name']} - {lot_label} - {lot_url}")
                                    else:
                                        lines.append(f"{account['account_name']} - {lot_label}")
                                acc.send_message(chat.id, "\n".join(lines))
                            else:
                                all_lots = db.get_all_lot_accounts()
                                if not all_lots:
                                    acc.send_message(chat.id, "???? ?? ?????????.")
                                else:
                                    current_time = datetime.now(tz=moscow_tz)
                                    next_expiry = None
                                    for account in all_lots:
                                        if account.get("owner") is None:
                                            continue
                                        rental_start = account.get("rental_start")
                                        duration = account.get("rental_duration")
                                        if not rental_start or not duration:
                                            continue
                                        if isinstance(rental_start, datetime):
                                            start_dt = rental_start
                                        else:
                                            try:
                                                start_dt = datetime.strptime(rental_start, "%Y-%m-%d %H:%M:%S")
                                            except ValueError:
                                                continue
                                        if start_dt.tzinfo is None:
                                            start_dt = moscow_tz.localize(start_dt)
                                        expiry_time = start_dt + timedelta(hours=int(duration))
                                        if next_expiry is None or expiry_time < next_expiry:
                                            next_expiry = expiry_time
                                    if next_expiry:
                                        remaining = next_expiry - current_time
                                        if remaining.total_seconds() < 0:
                                            remaining = timedelta(0)
                                        hours = int(remaining.total_seconds() // 3600)
                                        minutes = int((remaining.total_seconds() % 3600) // 60)
                                        acc.send_message(
                                            chat.id,
                                            "??? ? ??????. ????????? ??????? ??????????? ????? "
                                            f"{hours} ? {minutes} ??? (? {next_expiry.strftime('%H:%M:%S')} ???).",
                                        )
                                    else:
                                        acc.send_message(
                                            chat.id,
                                            "??? ? ??????. ??? ?????? ?? ?????????? ????????????.",
                                        )
                        except Exception as e:
                            logger.error(f"Failed to load stock for {event.message.author}: {str(e)}")
                            acc.send_message(chat.id, "?? ??????? ???????? ?????? ?????.")
                    elif event.message.type == types.MessageTypes.NEW_FEEDBACK:

                        try:
                            owner = event.message.author
                            if owner and owner not in feedbackGiven:
                                bonusEligible.add(owner)
                                chat = acc.get_chat_by_name(owner, True)
                                acc.send_message(
                                    chat.id,
                                    f"??????? ?? ?????! ???????? !bonus, ????? ???????? +{HOURS_FOR_REVIEW} ?.",
                                )
                        except Exception as e:
                            logger.error(f"Error handling NEW_FEEDBACK event: {str(e)}")

                logger.info("New message processed successfully.")


        except Exception as e:
            logger.error(f"An error occurred while processing event: {str(e)}")


def send_message_by_owner(owner, message):
    """Send a message to the specified owner."""
    try:
        if acc is None:
            logger.error("FunPay session not initialized; cannot send message.")
            return
        chat = acc.get_chat_by_name(owner, True)
        acc.send_message(chat.id, message)
    except Exception as e:
        logger.error(f"Failed to send message to {owner}: {str(e)}")


def get_account():
    """Return the current FunPay account session, if initialized."""
    return acc


# Ensure the function is available for import
__all__ = ["send_message_by_owner", "get_account"]




