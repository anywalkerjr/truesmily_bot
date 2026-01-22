from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional, Dict, List, Tuple, Any, NamedTuple
from mysql.connector import connect
import asyncio
from PIL import Image
import os
import json

from telegram import Bot
from telegram.constants import ChatMemberStatus
from telegram.error import TimedOut, NetworkError, RetryAfter
# Импорт констант
from constants import (
    DB_CONFIG, MAX_LEVEL, LEVELS, TALENT_BONUSES,
    LUCKY_WHEEL_COOLDOWN, STEAL_COOLDOWN,
    EXP_MULTIPLIERS_BY_BET, SLOTS, BUSINESS_LIST, TOKEN, EXP_CASE_COOLDOWN
)


# ======================= РАБОТА С БД =======================

@contextmanager
def get_db_connection():
    """Context manager для безопасной работы с БД"""
    conn = connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    try:
        yield cursor, conn
    finally:
        cursor.close()
        conn.close()


def get_cursor():
    """Устаревшая функция, оставлена для совместимости"""
    conn = connect(**DB_CONFIG)
    return [conn.cursor(dictionary=True), conn]


# ======================= УТИЛИТЫ =======================

async def safe_reply_text(message, text, **kwargs):
    for attempt in range(3):
        try:
            return await message.reply_text(text, **kwargs)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
        except (TimedOut, NetworkError):
            await asyncio.sleep(1.5 * (attempt + 1))
    # после 3 попыток просто сдаёмся
    return None


class UserResult(NamedTuple):
    id: int
    username: str
    first_name: str


def get_user_by_username(username: str) -> UserResult:
    with get_db_connection() as (cursor, conn):
        query = f"SELECT telegram_id, first_name FROM users WHERE username = %s"
        cursor.execute(query, (username[1:],))
        result = cursor.fetchone()
        if result:
            return UserResult(id=result['telegram_id'], username=username[1:], first_name=result['first_name'])
        else:
            return UserResult(id=-1, username=username[1:], first_name=result['first_name'])


def spaced_num(num: int | float) -> str:
    """Форматирование числа с пробелами: 1000000 -> 1 000 000"""
    return f"{int(num):,}".replace(",", " ")


async def cropped_num(num: int | str) -> str:
    """Сокращение больших чисел: 1500 -> 1.5k"""
    num = int(num)
    suffixes = ['', 'k', 'kk', 'kkk']
    suffix_index = 0

    while num >= 1000 and suffix_index < len(suffixes) - 1:
        num = round(num / 1000, 1)
        suffix_index += 1

    return f"{num}{suffixes[suffix_index]}"


def parse_bet_amount(amount_str: str, user_id: int, username: Optional[str] = None) -> Optional[int]:
    """Универсальный парсер ставок"""
    amount_str = str(amount_str).lower().strip()

    if amount_str in ['all', 'все', 'всё']:
        return get_balance(user_id, username)

    if 'k' in amount_str or 'к' in amount_str:
        separator = 'k' if 'k' in amount_str else 'к'
        parts = amount_str.split(separator)

        try:
            base_num = float(parts[0])
            k_count = amount_str.count(separator)
            return int(base_num * (1000 ** k_count))
        except (ValueError, IndexError):
            return None

    try:
        return int(float(amount_str))
    except ValueError:
        return None


def calculate_exp_multiplier(bet_amount: int, mastery_bonus: float = 0, business_bonus: float = 0) -> float:
    """Расчёт множителя опыта на основе ставки и бонусов"""
    base_mult = 1

    for threshold, mult in EXP_MULTIPLIERS_BY_BET:
        if bet_amount >= threshold:
            base_mult = mult

    return base_mult + mastery_bonus + business_bonus


# ======================= БАЛАНС =======================

def get_balance(user_id: int, username: Optional[str] = None) -> int:
    """Получение баланса пользователя"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT balance FROM users WHERE telegram_id = %s", (user_id,))
        result = cursor.fetchone()

        if result:
            return result['balance']
        else:
            cursor.execute(
                "INSERT INTO users (telegram_id, username, balance, level, experience) VALUES (%s, %s, %s, %s, %s)",
                (user_id, username, 100, 1, 0.0)
            )
            conn.commit()
            return 100


def set_balance(user_id: int, amount: int) -> None:
    """Обновление баланса"""
    amount = int(round(amount))
    with get_db_connection() as (cursor, conn):
        cursor.execute("UPDATE users SET balance = %s WHERE telegram_id = %s", (amount, user_id))
        conn.commit()


def update_user(telegram_id: int, fields: Dict[str, Any]) -> None:
    """Универсальное обновление полей"""
    if not fields:
        return

    with get_db_connection() as (cursor, conn):
        set_clause = ", ".join(f"{key} = %s" for key in fields.keys())
        values = list(fields.values())
        values.append(telegram_id)

        query = f"UPDATE users SET {set_clause} WHERE telegram_id = %s"
        cursor.execute(query, values)
        conn.commit()


# ======================= ОПЫТ И УРОВНИ =======================

def get_experience(user_id: int, username: Optional[str] = None) -> Tuple[int, float, float]:
    """Получение уровня и опыта пользователя"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT level, experience FROM users WHERE telegram_id = %s", (user_id,))
        result = cursor.fetchone()

        if result:
            true_lvl = next((lvl for lvl, xp in LEVELS if xp >= float(result['experience'])), float("inf")) - 1
            if int(result['level']) != true_lvl:
                cursor.execute("UPDATE users SET level = %s WHERE telegram_id = %s", (true_lvl, user_id,))
                conn.commit()
                return true_lvl, float(result['experience']), LEVELS[true_lvl+1][1]

            return int(result['level']), float(result['experience']), LEVELS[true_lvl+1][1]
        else:
            # Создаём пользователя если нет
            get_balance(user_id, username)
            conn.commit()
            return 1, 0.0, LEVELS[1][1]


def update_experience(user_id: int, amount: float) -> Dict[str, Any]:
    """
    Обновление опыта с автоматическим повышением уровня
    Возвращает dict с информацией о повышении: {'leveled_up': bool, 'new_level': int}
    """
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT level, experience FROM users WHERE telegram_id = %s", (user_id,))
        result = cursor.fetchone()

        if not result:
            return {'leveled_up': False, 'new_level': 1}

        current_level = int(result['level'])
        current_exp = float(result['experience'])
        new_exp = round(current_exp + amount, 1)

        # Проверка повышения уровня
        leveled_up = False
        while current_level < MAX_LEVEL:
            next_level_xp = next((xp for lvl, xp in LEVELS if lvl == current_level + 1), float('inf'))

            if new_exp >= next_level_xp:
                current_level += 1
                leveled_up = True
            else:
                break

        cursor.execute(
            "UPDATE users SET experience = %s, level = %s WHERE telegram_id = %s",
            (new_exp, current_level, user_id)
        )
        conn.commit()

        return {
            'leveled_up': leveled_up,
            'new_level': current_level,
            'new_exp': new_exp
        }


# ======================= БАНК И ВКЛАДЫ =======================

def update_bank_balance(user_id: int, bank_balance: int, hours: Optional[int]) -> None:
    """Обновление вклада пользователя"""
    with get_db_connection() as (cursor, conn):
        end_time = datetime.now() + timedelta(hours=hours) if hours else None

        cursor.execute(
            "UPDATE users SET bank_balance = %s, deposit_end = %s WHERE telegram_id = %s",
            (bank_balance, end_time, user_id)
        )
        conn.commit()


def check_deposit_ready(user_id: int) -> bool | List[int]:
    """
    Проверка готовности вклада
    Возвращает: True (готов), False (нет вклада), [hours, mins] или [mins] (осталось времени)
    """
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT bank_balance, deposit_end FROM users WHERE telegram_id = %s", (user_id,))
        user = cursor.fetchone()

        if not user or user["bank_balance"] <= 0:
            return False

        # Вклад без времени (устаревший) - готов сразу
        if user["deposit_end"] is None:
            return True

        # Проверяем готовность
        now = datetime.now()
        if now >= user["deposit_end"]:
            return True

        # Считаем оставшееся время
        remaining = user["deposit_end"] - now
        mins = int(remaining.total_seconds() // 60)

        if mins >= 60:
            hours = mins // 60
            mins -= (hours * 60)
            return [hours, mins]

        return [mins]


def claim_bank_balance(user_id: int) -> Optional[int]:
    """Забрать вклад, возвращает сумму или None"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "SELECT bank_balance, deposit_end, balance FROM users WHERE telegram_id = %s",
            (user_id,)
        )
        user = cursor.fetchone()

        if not user or user["bank_balance"] <= 0:
            return None

        # Проверяем готовность
        if user["deposit_end"] and datetime.now() < user["deposit_end"]:
            return None

        deposit_income_bonus = get_user_business_bonuses(user_id).get('deposit_income_bonus', 0)
        # Переводим на баланс
        claimed_amount = user["bank_balance"] + deposit_income_bonus*user["bank_balance"]
        new_balance = user["balance"] + claimed_amount

        set_balance(user_id, new_balance)
        update_bank_balance(user_id, 0, None)

        return claimed_amount


def get_all_users_with_deposit() -> List[Dict]:
    """Получить всех пользователей с активными вкладами"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT * FROM users WHERE bank_balance != 0")
        return cursor.fetchall()


# ======================= BLACKJACK =======================

def create_blackjack_session(user_id: int, bet: int, player: list, dealer: list) -> None:
    """Создание сессии блэкджека (безопасно с JSON)"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "REPLACE INTO blackjack_sessions (telegram_id, bet, player_cards, dealer_cards) VALUES (%s, %s, %s, %s)",
            (user_id, bet, json.dumps(player), json.dumps(dealer))
        )
        conn.commit()


def get_blackjack_session(user_id: int) -> Optional[Dict]:
    """Получение сессии блэкджека"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT * FROM blackjack_sessions WHERE telegram_id = %s", (user_id,))
        result = cursor.fetchone()

        if result:
            return {
                "bet": result["bet"],
                "player": json.loads(result["player_cards"]),  # Безопасно вместо eval()
                "dealer": json.loads(result["dealer_cards"])
            }
        return None


def delete_blackjack_session(user_id: int) -> None:
    """Удаление сессии блэкджека"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("DELETE FROM blackjack_sessions WHERE telegram_id = %s", (user_id,))
        conn.commit()


# ======================= MINES =======================

def create_mines_session(user_id: int, bet: int, field: list, open_cells: list) -> None:
    """Создание сессии минок (безопасно с JSON)"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "REPLACE INTO mines_sessions (telegram_id, bet, field, open_cells) VALUES (%s, %s, %s, %s)",
            (user_id, bet, json.dumps(field), json.dumps(open_cells))
        )
        conn.commit()


def get_mines_session(user_id: int) -> Optional[Dict]:
    """Получение сессии минок"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT * FROM mines_sessions WHERE telegram_id = %s", (user_id,))
        result = cursor.fetchone()

        if result:
            return {
                "bet": result["bet"],
                "field": json.loads(result["field"]),
                "open_cells": json.loads(result["open_cells"])
            }
        return None


def delete_mines_session(user_id: int) -> None:
    """Удаление сессии минок"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("DELETE FROM mines_sessions WHERE telegram_id = %s", (user_id,))
        conn.commit()


# ======================= ПОЛЬЗОВАТЕЛИ =======================

def ensure_user_exists(user) -> bool:
    """
    Проверка существования пользователя (создание если нет)
    Возвращает True если пользователь уже был, False если создан новый
    """
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (user.id,))

        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (telegram_id, username, first_name, balance) VALUES (%s, %s, %s, %s)",
                (user.id, user.username, user.first_name, 100)
            )
            conn.commit()
            return False
        else:
            cursor.execute(
                "UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE telegram_id = %s",
                (user.id,)
            )
            conn.commit()
            return True


def user_exists(user_id: Optional[int] = None, username: Optional[str] = None) -> bool:
    """Проверка существования пользователя по ID или username"""
    with get_db_connection() as (cursor, conn):
        if user_id:
            cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (user_id,))
        elif username:
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        else:
            return False

        return cursor.fetchone() is not None


def get_user(user_id: Optional[int] = None, username: Optional[str] = None) -> Optional[str]:
    """Получение имени пользователя (username или first_name) или его ID"""
    with get_db_connection() as (cursor, conn):
        if user_id:
            cursor.execute("SELECT username, first_name FROM users WHERE telegram_id = %s", (user_id,))
            fetch = cursor.fetchone()
            return fetch['username'] if fetch and fetch['username'] else fetch['first_name'] if fetch else None
        elif username:
            cursor.execute("SELECT telegram_id FROM users WHERE username = %s", (username,))
            fetch = cursor.fetchone()
            return fetch['telegram_id'] if fetch else None
        return None


# ======================= ДУЭЛИ =======================

def set_new_duel(user_id: int, target_id: int, bet: int, game: str = 'dice') -> bool | Dict:
    """Создание дуэли (возвращает False если создана, dict с существующей если есть)"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT * FROM duels_sessions WHERE user_id = %s", (user_id,))
        fetch = cursor.fetchone()

        if not fetch:
            cursor.execute(
                'INSERT INTO duels_sessions (user_id, target_id, bet, game) VALUES (%s, %s, %s, %s)',
                (user_id, target_id, bet, game)
            )
            conn.commit()
            return False
        else:
            return fetch


# ======================= ТАЛАНТЫ =======================

def ensure_talent_exists(user_id: int) -> None:
    """Создание записи талантов если не существует"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT user_id FROM talents WHERE user_id = %s", (user_id,))

        if not cursor.fetchone():
            cursor.execute("INSERT INTO talents (user_id) VALUES (%s)", (user_id,))
            conn.commit()


def get_user_talents(user_id: int) -> Dict[str, int]:
    """Получение уровней талантов пользователя"""
    with get_db_connection() as (cursor, conn):
        ensure_talent_exists(user_id)

        cursor.execute(
            "SELECT untouchable, agility, mastery, luck FROM talents WHERE user_id = %s",
            (user_id,)
        )
        row = cursor.fetchone()

        return {
            "untouchable": row['untouchable'],
            "agility": row['agility'],
            "mastery": row['mastery'],
            "luck": row['luck']
        }


def get_user_bonuses(user_id: int, talent_name: str) -> float:
    """
    Получение бонуса от таланта
    Возвращает числовое значение бонуса (например, 0.3 для 30%)
    """
    with get_db_connection() as (cursor, conn):
        ensure_talent_exists(user_id)

        cursor.execute(f"SELECT {talent_name} FROM talents WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()

        level = result[talent_name] if result else 0
        bonus_per_level = TALENT_BONUSES.get(talent_name, 0)

        return round(level * bonus_per_level, 4)


# ======================= КОЛЕСО УДАЧИ =======================

def update_luckywheel_timestamp(user_id: int) -> None:
    """Обновление времени последнего спина колеса"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "UPDATE users SET last_lucky_wheel = CURRENT_TIMESTAMP WHERE telegram_id = %s",
            (user_id,)
        )
        conn.commit()

def update_expcase_timestamp(user_id: int) -> None:
    """Обновление времени последнего кейса"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "UPDATE users SET last_exp_case = CURRENT_TIMESTAMP WHERE telegram_id = %s",
            (user_id,)
        )
        conn.commit()


def check_lucky_wheel_availability(user_id: int) -> bool | int:
    """
    Проверка доступности колеса удачи
    Возвращает: True (доступно) или int (минут до доступности)
    """
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT last_lucky_wheel FROM users WHERE telegram_id = %s", (user_id,))
        last_spin = cursor.fetchone()

        if not last_spin or last_spin['last_lucky_wheel'] is None:
            update_luckywheel_timestamp(user_id)
            return 0

        last_lucky_wheel = last_spin['last_lucky_wheel']
        current_time = datetime.now()
        time_passed = current_time - last_lucky_wheel

        if time_passed >= timedelta(minutes=LUCKY_WHEEL_COOLDOWN):
            update_luckywheel_timestamp(user_id)
            return 0

        remaining = timedelta(minutes=LUCKY_WHEEL_COOLDOWN) - time_passed
        return int(remaining.total_seconds() // 60)


def check_exp_case_availability(user_id: int) -> bool | int:
    """
    Проверка доступности кейса опыта
    Возвращает: 0 (доступно) или int (минут до доступности)
    """
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT last_exp_case FROM users WHERE telegram_id = %s", (user_id,))
        last_case = cursor.fetchone()

        if not last_case or last_case['last_exp_case'] is None:
            update_expcase_timestamp(user_id)
            return 0

        last_exp_case = last_case['last_exp_case']
        current_time = datetime.now()
        time_passed = current_time - last_exp_case

        if time_passed >= timedelta(minutes=EXP_CASE_COOLDOWN):
            update_expcase_timestamp(user_id)
            return 0

        remaining = timedelta(minutes=EXP_CASE_COOLDOWN) - time_passed
        return int(remaining.total_seconds() // 60)

# ======================= КРАЖА =======================

def update_steal_timestamp(user_id: int) -> None:
    """Обновление времени последней кражи"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "UPDATE users SET last_steal = CURRENT_TIMESTAMP WHERE telegram_id = %s",
            (user_id,)
        )
        conn.commit()


def check_steal_availability(user_id: int) -> bool | int:
    """
    Проверка доступности кражи
    Возвращает: True (доступно) или int (минут до доступности)
    """
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT last_steal FROM users WHERE telegram_id = %s", (user_id,))
        last_attempt = cursor.fetchone()

        if not last_attempt or last_attempt['last_steal'] is None:
            update_steal_timestamp(user_id)
            return True

        last_steal = last_attempt['last_steal']
        current_time = datetime.now()
        time_passed = current_time - last_steal

        if time_passed >= timedelta(minutes=STEAL_COOLDOWN):
            update_steal_timestamp(user_id)
            return True

        remaining = timedelta(minutes=STEAL_COOLDOWN) - time_passed
        return int(remaining.total_seconds() // 60)


# ======================= БИЗНЕС =======================

def ensure_business_profile(user_id: int) -> None:
    """Создание профиля бизнесов если не существует"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute("SELECT user_id FROM user_businesses WHERE user_id = %s", (user_id,))

    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO user_businesses (user_id, businesses_ids) VALUES (%s, %s)",
            (user_id, json.dumps([]))
        )
        conn.commit()


def get_user_business_profile(user_id: int) -> Dict:
    """
    Получение профиля бизнесов пользователя
    Возвращает: {'businesses_ids': [1, 3, 5], 'passive_income': 50000}
    """
    c = get_cursor()
    cursor, conn = c[0], c[1]

    ensure_business_profile(user_id)

    cursor.execute(
        "SELECT businesses_ids FROM user_businesses WHERE user_id = %s",
        (user_id,)
    )
    row = cursor.fetchone()

    # Безопасная десериализация
    try:
        businesses_ids = json.loads(row['businesses_ids'])
    except (json.JSONDecodeError, TypeError):
        businesses_ids = []

    passive_income = sum(b["income"] for b in BUSINESS_LIST if b["id"] in businesses_ids)

    return {
        "businesses_ids": businesses_ids,
        "passive_income": passive_income
    }


def get_user_business_bonuses(user_id: int) -> Dict[str, float]:
    """
    Получение всех бонусов от бизнесов пользователя
    Возвращает: {'game_mastery': 0.3, 'steal_chance': -5}
    """
    profile = get_user_business_profile(user_id)
    bonuses = {}

    for biz_id in profile['businesses_ids']:
        biz_data = next((b for b in BUSINESS_LIST if b['id'] == biz_id), None)

        if not biz_data or not biz_data['user_bonus']:
            continue

        for bonus_type, value in biz_data['user_bonus'].items():
            bonuses[bonus_type] = bonuses.get(bonus_type, 0) + value

    return bonuses


def add_user_business(user_id: int, business_id: int) -> bool:
    """
    Добавление бизнеса пользователю
    Возвращает: True если успешно, False если уже есть
    """
    c = get_cursor()
    cursor, conn = c[0], c[1]

    profile = get_user_business_profile(user_id)
    businesses = profile["businesses_ids"]

    if business_id in businesses:
        return False

    businesses.append(business_id)
    businesses.sort()

    cursor.execute(
        "UPDATE user_businesses SET businesses_ids = %s WHERE user_id = %s",
        (json.dumps(businesses), user_id)
    )
    conn.commit()

    return True


def calculate_total_income(user_id: int) -> int:
    """Расчёт общего дохода с учётом множителей"""
    profile = get_user_business_profile(user_id)
    businesses = profile["businesses_ids"]
    base_income = sum(b["income"] for b in BUSINESS_LIST if b["id"] in businesses)

    # Применяем бонус от блокчейн-стартапа (+10% доходов)
    bonuses = get_user_business_bonuses(user_id)
    income_mult = bonuses.get('income_multiplier', 0)

    if income_mult:
        base_income = int(base_income * (1 + income_mult))

    return base_income

# ======================= ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ =======================

def generate_spin_image(emojis: List[str], output_path: str = "spin_result.png") -> str:
    """Генерация изображения результата спина"""
    sprite_dir = "sprites"
    sprite_width, sprite_height = 100, 100
    padding = 10

    total_width = len(emojis) * sprite_width + (len(emojis) - 1) * padding
    total_height = sprite_height

    image = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 0))

    for i, emoji in enumerate(emojis):
        filename = SLOTS["emoji_to_filename"].get(emoji)
        if not filename:
            continue

        sprite_path = os.path.join(sprite_dir, filename)
        if not os.path.exists(sprite_path):
            continue

        sprite = Image.open(sprite_path).convert("RGBA")
        sprite = sprite.resize((sprite_width, sprite_height), Image.Resampling.LANCZOS)

        x = i * (sprite_width + padding)
        image.paste(sprite, (x, 0), sprite)

    image.save(output_path)
    return output_path


# ======================= ПРОМОКОДЫ И ДОНАТ =======================

def check_promocode(promocode: str, user_id: int) -> Tuple[bool, str]:
    data = get_promocode_data(promocode)

    if not data:
        return False, "Такого промокода не существует"

    now = datetime.now().date()

    if not data["is_active"]:
        return False, "Промокод неактивен"

    if data["expiration_date"] and data["expiration_date"] < now:
        deactivate_promocode(promocode)
        return False, "Срок активации промокода истёк"

    if data["max_activations"] != -1 and data["activations_remaining"] <= 0:
        deactivate_promocode(promocode)
        return False, "Закончились активации промокода"

    if user_id in data["users"]:
        return False, "Промокод уже был применен"

    return True, ""


def activate_promocode(user_id: int, promocode: str) -> str:
    data = get_promocode_data(promocode)
    award = data["award"]

    msg = "*✅ Награда:*\n\n"

    if award.get("business"):
        for biz_id in award["business"]:
            has_business = add_user_business(user_id, biz_id)
            msg += f"• {BUSINESS_LIST[biz_id]['emoji']} {BUSINESS_LIST[biz_id]['name']}"
            msg += " (уже есть)\n" if not has_business else "\n"

    if award.get("experience"):
        update_experience(user_id, award["experience"])
        msg += f"• ✨ +{award['experience']} EXP\n"

    if award.get("lvl"):
        current_lvl, current_xp, next_level_xp = get_experience(user_id)
        target_lvl = current_lvl + award["lvl"]

        next_level_xp = next(
            (xp for lvl, xp in LEVELS if lvl == target_lvl),
            float('inf')
        )

        update_experience(user_id, next_level_xp - current_xp)
        msg += f"• ✨ +{award['lvl']} LVL\n"

    if award.get("balance"):
        set_balance(user_id, get_balance(user_id) + award["balance"])
        msg += f"• 💰 +{award['balance']} $miles\n"

    return msg


def deactivate_promocode(promocode: str):
    with get_db_connection() as (cursor, conn):
        query = """
            UPDATE promocodes
            SET is_active = 0
            WHERE promocode = %s
        """

        cursor.execute(query, (promocode,))
        conn.commit()


def try_activate_promocode(promocode: str, user_id: int) -> bool:
    """
    Атомарно активирует промокод:
    - уменьшает activations_remaining
    - добавляет пользователя в users

    Возвращает True, если активация успешна
    """

    with get_db_connection() as (cursor, conn):
        cursor.execute(
            """
            UPDATE promocodes
            SET activations_remaining = activations_remaining - 1,
                users = JSON_ARRAY_APPEND(users, '$', %s)
            WHERE promocode = %s
              AND is_active = 1
              AND (max_activations = -1 OR activations_remaining > 0)
              AND JSON_CONTAINS(users, %s) = 0
            """,
            (user_id, promocode, json.dumps(user_id))
        )

        conn.commit()

        return cursor.rowcount == 1


async def check_promocode_requirements(user_id: int, promocode: str) -> Tuple[bool, str]:
    data = get_promocode_data(promocode)
    requirements = data.get("requirements", {})

    if not requirements:
        return True, ""

    errors = []

    user_level, user_experience, next_level_xp = get_experience(user_id)
    user_businesses = get_user_business_profile(user_id).get("businesses", [])
    user_talents = get_user_talents(user_id)

    if requirements.get("required_lvl") and user_level < requirements["required_lvl"]:
        errors.append(f"⚠️ Необходим уровень {requirements['required_lvl']} или выше.")

    for biz_id in requirements.get("required_business", []):
        if biz_id not in user_businesses:
            errors.append(
                f"⚠️ Необходим бизнес <i>{BUSINESS_LIST[biz_id]['emoji']} {BUSINESS_LIST[biz_id]['name']}</i>."
            )

    for talent, lvl in requirements.get("required_talents", {}).items():
        if user_talents.get(talent, 0) < lvl:
            errors.append(f"⚠️ Необходим талант <i>'{talent}'</i> уровня {lvl} или выше.")

    for channel_id in requirements.get("required_channels", []):
        ok, link = await is_subscribed(user_id, channel_id)
        if not ok:
            errors.append(f"⚠️ Подпишись на <a href='{link}'><b>канал</b></a>.")

    if errors:
        return False, "\n".join(errors)

    return True, ""


async def is_subscribed(user_id, channel_id) -> Tuple[bool, str]:
    bot = Bot(TOKEN)
    member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        return True, ""
    invite_link = await bot.export_chat_invite_link(chat_id=channel_id)
    return False, invite_link


def get_promocode_data(promocode: str) -> Dict:
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            """
            SELECT award, requirements, users, max_activations,
                   activations_remaining, expiration_date, is_active
            FROM promocodes
            WHERE promocode = %s
            """,
            (promocode,)
        )
        row = cursor.fetchone()

        if row is None:
            return {}

        return {
            "award": json.loads(row["award"]) if row["award"] else {},
            "requirements": json.loads(row["requirements"]) if row["requirements"] else {},
            "users": json.loads(row["users"]),
            "max_activations": row["max_activations"],
            "activations_remaining": row["activations_remaining"],
            "expiration_date": row["expiration_date"],
            "is_active": bool(row["is_active"])
        }


def create_promocode(promocode: str, requirements: Dict, max_activations: int, expiration_date: datetime, award: Dict):
    with get_db_connection() as (cursor, conn):
        query = """
            INSERT INTO promocodes (promocode, max_activations, activations_remaining, expiration_date, requirements, award, users) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (promocode, max_activations, max_activations, expiration_date, json.dumps(requirements),
                               json.dumps(award), json.dumps([])))
        conn.commit()

# create_promocode("CHANNEL", {"required_channels": [-1003523970109]}, max_activations=100, expiration_date=datetime.today() + timedelta(days=5), award={"business": [1, 2], "balance": 250_000, "lvl": 1})
