"""
Модуль игры Crash (/crash)

Архитектура:
  - ЛС (приватный чат): мгновенная одиночная игра без таблиц сессий.
  - Группа: мультиплеерный раунд; ракета взлетает одна на весь чат.

Таблицы БД:
  crash_games  — активные раунды (одна строка на чат)
  crash_bets   — ставки игроков на текущий раунд
"""

import os
import asyncio
import random
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

from telegram import Bot, Update
from telegram.ext import ContextTypes

from constants import MIN_BET, LEVELS, GROUP_GAME_DURATION, BETTING_DEADLINE_OFFSET, CRASH, MESSAGES
from helpers import (
    get_balance, spaced_num,
    get_experience, update_experience,
    get_user_bonuses, get_db_connection, parse_bet_amount,
    calculate_exp_multiplier, ensure_user_exists,
    debit_balance, credit_balance,
    get_user_business_bonuses, try_gem_drop,
)

import io
from PIL import Image, ImageDraw, ImageFont

# ======================= КОНСТАНТЫ =======================
# Шрифт
CRASH_FONT = ImageFont.truetype("fonts/SF-Pro-Rounded-Bold.ttf", 72)


# ======================= ВСПОМОГАТЕЛЬНЫЕ =======================

def get_crash_card_path(won: bool, crash_multiplier: float) -> str:
    """Возвращает путь к карточке для отображения результата /crash"""
    if not won:
        return os.path.join("images", "crash_lvl0.jpg")  # 💥 Поражение

    if crash_multiplier >= 50.0:
        return os.path.join("images", "crash_lvl5.jpg")  # 😈 50x+
    elif crash_multiplier >= 25.0:
        return os.path.join("images", "crash_lvl4.jpg")  # 🤑 25x – 49.99x
    elif crash_multiplier >= 10.0:
        return os.path.join("images", "crash_lvl3.jpg")  # 😎 10x – 24.99x
    elif crash_multiplier >= 2.5:
        return os.path.join("images", "crash_lvl2.jpg")  # 😃 2.50x – 9.99x
    else:
        return os.path.join("images", "crash_lvl1.jpg")  # 🙂 1.01x – 2.49x


def generate_crash_image(image_path: str, multiplier: float) -> io.BytesIO:
    """Генерирует картинку краша и возвращает BytesIO буфер"""

    with Image.open(image_path) as base_img:
        img = base_img.convert("RGBA")

    try:
        draw = ImageDraw.Draw(img)
        text = f"{multiplier:.2f}x"

        target_x = img.width - 39
        target_y = img.height - 108

        draw.text(
            (target_x, target_y),
            text,
            font=CRASH_FONT,
            fill=(255, 255, 255),
            anchor="rb"
        )

        final_img = img.convert("RGB")
        bio = io.BytesIO()
        final_img.save(bio, format="JPEG", quality=85, optimize=True)
        bio.seek(0)
        return bio
    finally:
        img.close()
        if 'final_img' in locals():
            final_img.close()


def generate_crash_multiplier() -> float:
    """
    Генерирует коэффициент краша по экспоненциальному распределению
    с учетом фиксированного процента мгновенного проигрыша (House Edge).

    Алгоритм:
    1. С вероятностью HOUSE_EDGE самолет взрывается на 1.00x (мгновенный краш).
    2. В остальных случаях: crash = 1 / U, где U ~ Uniform(0, 1).

    Вероятности долететь (без учета House Edge):
    - до 2.00x — 50%
    - до 10.00x — 10%
    - до 100.00x — 1%
    """
    if random.random() < CRASH["house_edge_percent"]:
        return 1.00

    u = random.random()

    if u == 0:
        return 1.00

    raw = 1.0 / u

    return round(min(raw, CRASH["max_multiplier"]), 2)


def calculate_crash_exp(won: bool, bet_amount: int, user_id: int) -> float:
    """Расчёт опыта за игру в краш"""
    base_exp = CRASH["exp_win"] if won else CRASH["exp_loss"]
    mastery_bonus = get_user_bonuses(user_id, 'mastery')
    business_bonus = get_user_business_bonuses(user_id).get('game_mastery', 0)
    exp_mult = calculate_exp_multiplier(bet_amount, mastery_bonus, business_bonus)
    return round(base_exp * exp_mult, 1)


def apply_luck_cashback(user_id: int, username: str, bet_amount: int) -> Tuple[int, str]:
    """
    Применяет кэшбэк от таланта «Удача» при проигрыше.
    Возвращает: (сумма_кэшбэка, текст_для_сообщения)
    """
    luck_bonus = get_user_bonuses(user_id, 'luck')
    if not luck_bonus:
        return 0, ''
    if random.randint(0, 100) < luck_bonus:
        cashback = round(bet_amount * 0.2)
        credit_balance(user_id, cashback)
        bonus_text = (
            f"🍀 @{username} повезло! Возвращено 20% "
            f"({spaced_num(cashback)} $miles) от ставки!"
        )
        return cashback, bonus_text
    return 0, ''


def _level_info_text(user_id: int, username: str) -> str:
    """Строка с уровнем и опытом для финального сообщения"""
    level_info = get_experience(user_id, username)
    current_level = level_info[0]
    current_xp = level_info[1]
    next_level_xp = next(
        (xp for lvl, xp in LEVELS if lvl == current_level + 1),
        float("inf")
    )
    return f"⭐️ Уровень: {current_level} ({current_xp}/{next_level_xp})"


# ======================= БАЗА ДАННЫХ =======================

def create_crash_game_if_needed(chat_id: int) -> None:
    """Создаёт запись активного раунда для чата, если её ещё нет"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "SELECT 1 FROM crash_games WHERE chat_id = %s AND is_active = TRUE",
            (chat_id,)
        )
        if cursor.fetchone():
            return  # Раунд уже есть

        now = datetime.now(timezone.utc)
        start_time = now + timedelta(seconds=GROUP_GAME_DURATION)
        deadline = start_time - timedelta(seconds=BETTING_DEADLINE_OFFSET)

        cursor.execute(
            """INSERT INTO crash_games (chat_id, start_time, betting_deadline)
               VALUES (%s, %s, %s)""",
            (chat_id, start_time, deadline)
        )
        conn.commit()


def get_mult_group(mult: float) -> str:
    if mult < 2.5:
        return "🧒🏻 Слабачки (<2.5)"
    elif mult < 10:
        return "🧑🏻 Пацаны (2.5<x<10)"
    elif mult < 25:
        return "👨🏻 Мужики (10<x<25)"
    elif mult < 50:
        return "💪🏻 Звери (25<x<50)"
    else:
        return "🙈 Лудоманы (50<x<100)"


def can_place_crash_bet(chat_id: int) -> Tuple[bool, Optional[str]]:
    """
    Проверяет, можно ли ещё принять ставку в текущем раунде.
    Возвращает: (можно_ставить, сообщение_об_ошибке)
    """
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "SELECT * FROM crash_games WHERE chat_id = %s AND is_active = TRUE",
            (chat_id,)
        )
        game = cursor.fetchone()

    if not game:
        return False, "⏳ Сейчас нет активного раунда."

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deadline = game['betting_deadline'].replace(tzinfo=None)

    if now >= deadline:
        return False, "❌ Ставки закрыты. Подождите следующего раунда."

    return True, None


def add_new_crash_bet(
        chat_id: int,
        user_id: int,
        username: str,
        target_multiplier: float,
        amount: int
) -> None:
    """
    Добавляет новую ставку игрока или увеличивает сумму текущей,
    если игрок повторно ставит на тот же самый множитель.
    """
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            """INSERT INTO crash_bets (chat_id, user_id, username, target_multiplier, amount)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   amount = amount + VALUES(amount)""",
            (chat_id, user_id, username, target_multiplier, amount)
        )
        conn.commit()


def get_crash_game_bets(chat_id: int) -> List[Dict]:
    """Возвращает все ставки текущего раунда для чата"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "SELECT * FROM crash_bets WHERE chat_id = %s",
            (chat_id,)
        )
        return cursor.fetchall()


def get_user_first_name(user_id: int) -> str:
    """Имя пользователя для вывода в результатах"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "SELECT first_name FROM users WHERE telegram_id = %s",
            (user_id,)
        )
        result = cursor.fetchone()
        return result['first_name'] if result else f"User{user_id}"


# ======================= КОМАНДА /crash =======================

async def crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /crash <авто_стоп> <ставка>

    Примеры:
        /crash 1.5 100k        — ставка 100k, выходим при 1.5x
        /crash 10 all          — ставка всего баланса, цель 10x
    """
    user = update.effective_user
    if not user or not update.message:
        return

    chat = update.effective_chat
    user_id = user.id
    username = user.username or f"id{user_id}"
    chat_id = chat.id
    is_private = chat.type == "private"

    ensure_user_exists(user)

    # ── Проверка аргументов ──────────────────────────────────────
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            MESSAGES["no_args"]["crash"],
            parse_mode="Markdown"
        )
        return

    # ── Парсинг коэффициента авто-стопа ─────────────────────────
    try:
        target_mult = round(float(context.args[0].replace(",", ".")), 2)
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный коэффициент. Пример: `1.5` или `10`",
            parse_mode="Markdown"
        )
        return

    if target_mult < CRASH["min_multiplier"]:
        await update.message.reply_text(
            f"❌ Минимальный авто-стоп: {CRASH["min_multiplier"]}x"
        )
        return

    if target_mult > CRASH["max_multiplier"]:
        await update.message.reply_text(
            f"❌ Максимальный авто-стоп: {CRASH["max_multiplier"]}x"
        )
        return

    # ── Парсинг ставки ──────────────────────────────────────────
    bet_amount = parse_bet_amount(context.args[1], user_id, username)
    if bet_amount is None:
        await update.message.reply_text(MESSAGES["invalid_bet"])
        return

    if bet_amount < MIN_BET:
        await update.message.reply_text(MESSAGES["min_bet_error"])
        return

    balance = get_balance(user_id, username)
    if bet_amount > balance:
        await update.message.reply_text(
            MESSAGES["insufficient_funds"].format(spaced_num(balance))
        )
        return

    # ── ЛИЧНАЯ ИГРА (ЛС) ────────────────────────────────────────
    if is_private:
        await play_solo_crash(update, user_id, username, target_mult, bet_amount)
        return

    # ── ГРУППОВАЯ ИГРА ───────────────────────────────────────────
    create_crash_game_if_needed(chat_id)

    can_bet, error_msg = can_place_crash_bet(chat_id)
    if not can_bet:
        await update.message.reply_text(error_msg)
        return

    # Атомарное списание (защита от гонки потоков)
    if not debit_balance(user_id, bet_amount):
        balance = get_balance(user_id, username)
        await update.message.reply_text(
            MESSAGES["insufficient_funds"].format(spaced_num(balance))
        )
        return

    add_new_crash_bet(chat_id, user_id, username, target_mult, bet_amount)

    await update.message.reply_text(
        f"✅ Ставка принята!\n"
        f"💰 Сумма: {spaced_num(bet_amount)} $miles\n"
        f"🎯 Авто-стоп: {target_mult}x"
    )


async def lobby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /lobby - показать текущую групповую игру и ставки"""
    chat_id = update.effective_chat.id

    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "SELECT * FROM crash_games WHERE chat_id = %s AND is_active = TRUE",
            (chat_id,)
        )
        game_info = cursor.fetchone()

    if not game_info:
        await update.message.reply_text("🎲 Сейчас нет активной игры.")
        return

    # Считаем оставшееся время
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seconds_left = int((game_info['start_time'] - now).total_seconds())

    # Получаем ставки
    bets = get_crash_game_bets(chat_id)

    if not bets:
        time_info = f"⏳ Игра начнётся через {seconds_left} сек." if seconds_left > 0 else "⏳ Игра сейчас начнётся..."
        await update.message.reply_text(f"📈 Краш\n\n{time_info}\n\n📭 Ставок пока нет.")
        return

    # Группируем ставки по типу
    grouped_bets: Dict[str, List[str]] = {}

    for bet in bets:
        group = get_mult_group(bet['target_multiplier'])
        if group not in grouped_bets:
            grouped_bets[group] = []

        display_name = f"@{bet['username']}" if bet['username'] else get_user_first_name(bet['user_id'])
        grouped_bets[group].append(
            f"{display_name} — {spaced_num(bet['amount'])} $miles — 🎯 {bet['target_multiplier']}x")

    # Формируем сообщение
    output = "📈 *Краш*\n🏦 *Ставки:*\n\n"

    for group, players in grouped_bets.items():
        output += f"{group}:\n" + "\n".join(players) + "\n——————————\n"

    time_info = f"⏳ Игра начнётся через {seconds_left} сек." if seconds_left > 0 else "⏳ Игра сейчас начнётся..."
    output += f"\n{time_info}"

    await update.message.reply_text(output, parse_mode="Markdown")


# ======================= ОДИНОЧНАЯ ИГРА =======================

async def play_solo_crash(
        update: Update,
        user_id: int,
        username: str,
        target_mult: float,
        bet_amount: int
) -> None:
    """Мгновенная игра в ЛС — без таблиц сессий"""

    # Атомарное списание
    if not debit_balance(user_id, bet_amount):
        balance = get_balance(user_id, username)
        await update.message.reply_text(
            MESSAGES["insufficient_funds"].format(spaced_num(balance))
        )
        return

    # Генерация краша
    crash_mult = generate_crash_multiplier()
    won = target_mult <= crash_mult

    result_text = (
        f"🚀 *Crash*\n\n"
        f"💥 Ракета упала на: *{crash_mult}x*\n"
        f"🎯 Твой авто-стоп: *{target_mult}x*\n\n"
    )

    if won:
        # Рассчитываем выигрыш по целевому коэффициенту игрока
        winnings = int(bet_amount * target_mult)
        win_bonus = get_user_business_bonuses(user_id).get("win_multiplier", 0)
        win_bonus_amount = int(winnings * win_bonus)
        bonus_line = f"❇️ Бонус: {spaced_num(win_bonus_amount)} $miles\n" if win_bonus_amount else ""

        mult = winnings / bet_amount
        _, gem_line = try_gem_drop(user_id, mult)
        gem_line.replace("\n", "")

        credit_balance(user_id, winnings + win_bonus_amount)
        result_text += (
                f"🏆 *Победа!*\n"
                f"💵 Выигрыш: {spaced_num(winnings)} $miles\n"
                + bonus_line + gem_line
        )
    else:
        result_text += f"💀 *Ракета упала раньше!*\n😢 Потеряно: {spaced_num(bet_amount)} $miles\n"
        cashback, cashback_text = apply_luck_cashback(user_id, username, bet_amount)
        if cashback_text:
            result_text += cashback_text + "\n"

    # Опыт
    exp_gained = calculate_crash_exp(won, bet_amount, user_id)
    update_experience(user_id, exp_gained)

    result_text += (
        f"\n✨ Получено: {exp_gained} EXP\n"
        f"{_level_info_text(user_id, username)}\n"
        f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
    )

    # Карточка результата
    card_path = get_crash_card_path(won, crash_mult)
    img = generate_crash_image(card_path, crash_mult)
    try:
        await update.message.reply_photo(
            photo=img,
            caption=result_text,
            parse_mode="Markdown"
        )
    except (FileNotFoundError, OSError):
        await update.message.reply_text(result_text, parse_mode="Markdown")
    finally:
        img.close()


# ======================= ЗАВЕРШЕНИЕ ГРУППОВОГО РАУНДА =======================

async def resolve_crash_for_chat(chat_id: int, bot: Bot) -> None:
    """
    Подводит итоги группового раунда:
      1. Атомарно переводит is_active = FALSE (защита от двойного вызова).
      2. Генерирует один crash_multiplier для чата.
      3. Начисляет выигрыши / фиксирует поражения.
      4. Отправляет общую карточку с итогами.
      5. Чистит crash_bets и crash_games.
    """
    # ── Атомарный захват раунда ──────────────────────────────────
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "UPDATE crash_games SET is_active = FALSE "
            "WHERE chat_id = %s AND is_active = TRUE",
            (chat_id,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            return  # Уже обрабатывается

    # ── Получаем ставки ──────────────────────────────────────────
    bets = get_crash_game_bets(chat_id)

    if not bets:
        with get_db_connection() as (cursor, conn):
            cursor.execute("DELETE FROM crash_games WHERE chat_id = %s", (chat_id,))
            conn.commit()
        await bot.send_message(chat_id, "⛔ Раунд завершён, но ставок не было.")
        return

    # ── Один общий краш для всего чата ─────────────────────────
    crash_mult = generate_crash_multiplier()

    result_text = (
        f"🚀 *Crash — итоги раунда!*\n"
        f"💥 Ракета упала на: *{crash_mult}x*\n\n"
    )

    win_log: List[str] = []
    lose_log: List[str] = []

    for bet in bets:
        u_id = bet['user_id']
        u_name = bet['username']
        amount = int(bet['amount'])
        t_mult = float(bet['target_multiplier'])

        display = f"@{u_name}" if u_name else get_user_first_name(u_id)
        won = t_mult <= crash_mult

        if won:
            winnings = int(amount * t_mult)
            win_bonus = get_user_business_bonuses(u_id).get("win_multiplier", 0)
            win_bonus_amount = int(winnings * win_bonus)
            bonus_line = f"\n  ❇️ Бонус: {spaced_num(win_bonus_amount)} $miles" if win_bonus_amount else ""

            credit_balance(u_id, winnings + win_bonus_amount)

            exp_gained = calculate_crash_exp(True, amount, u_id)
            update_experience(u_id, exp_gained)
            mult = winnings / amount
            _, gem_line = try_gem_drop(u_id, win_multiplier=mult)

            win_log.append(
                f"{display} (🎯 {t_mult}x) → +{spaced_num(winnings)} $miles "
                f"(✨ +{exp_gained} EXP){bonus_line}{gem_line}"
            )
        else:
            exp_gained = calculate_crash_exp(False, amount, u_id)
            update_experience(u_id, exp_gained)

            cashback, cb_text = apply_luck_cashback(u_id, u_name or "", amount)
            line = (
                f"{display} (🎯 {t_mult}x) → -{spaced_num(amount)} $miles "
                f"(✨ +{exp_gained} EXP)"
            )
            if cb_text:
                line += f"\n  {cb_text}"
            lose_log.append(line)

    if win_log:
        result_text += "🏆 *Победители:*\n" + "\n".join(win_log) + "\n\n"
    if lose_log:
        result_text += "💀 *Проигравшие:*\n" + "\n".join(lose_log)

    # ── Выбор карточки ───────────────────────────────────────────
    # Показываем карточку по реальному коэффициенту краша
    # (если хоть кто-то выиграл — берём уровень по crash_mult,
    #  иначе — поражение crash_lvl0)
    any_winner = bool(win_log)
    card_path = get_crash_card_path(any_winner, crash_mult)
    img = generate_crash_image(card_path, crash_mult)
    # ── Чистим БД ────────────────────────────────────────────────
    with get_db_connection() as (cursor, conn):
        cursor.execute("DELETE FROM crash_bets  WHERE chat_id = %s", (chat_id,))
        cursor.execute("DELETE FROM crash_games WHERE chat_id = %s", (chat_id,))
        conn.commit()

    # ── Отправляем итоги ─────────────────────────────────────────
    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=img,
            caption=result_text,
            parse_mode="Markdown"
        )
    except (FileNotFoundError, OSError):
        await bot.send_message(chat_id, result_text, parse_mode="Markdown")
    finally:
        img.close()


# ======================= ФОНОВАЯ ПРОВЕРКА =======================

async def check_all_crash_games(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Периодическая задача (job_queue): запускает resolve_crash_for_chat
    для всех чатов, у которых наступило start_time.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT * FROM crash_games WHERE is_active = TRUE")
        games = cursor.fetchall()

    for g in games:
        if g['start_time'].replace(tzinfo=None) <= now:
            await resolve_crash_for_chat(g['chat_id'], context.bot)
            await asyncio.sleep(0.1)


# ======================= ЭКСПОРТ =======================

__all__ = [
    'crash',
    'check_all_crash_games',
    'resolve_crash_for_chat',
    'lobby',
]
