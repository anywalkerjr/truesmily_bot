import io
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional
import random
from PIL import Image
from telegram import Bot, Update
from telegram.ext import ContextTypes

from constants import (
    ROULETTE, MIN_BET, LEVELS,
    GROUP_GAME_DURATION, BETTING_DEADLINE_OFFSET
)
from helpers import (
    get_balance, set_balance, spaced_num,
    get_experience, update_experience,
    get_user_bonuses, get_cursor, parse_bet_amount,
    calculate_exp_multiplier, ensure_user_exists
)
from helpers import get_user_business_bonuses

# Извлекаем константы из словаря
RED_NUMBERS = ROULETTE["red_numbers"]
BLACK_NUMBERS = ROULETTE["black_numbers"]
MULTIPLIERS = ROULETTE["multipliers"]
BASE_EXP = ROULETTE["base_exp"]
BET_NAMES = ROULETTE["bet_names"]
VALID_BET_TYPES = ROULETTE["valid_bet_types"]
NUMBERS_IMG_CACHE = {
    str(num): Image.open(f'roulette/{num}.png').convert("RGBA")
    for num in range(0, 37)
}
MAIN_IMG_CACHE = Image.open('roulette/roulette.jpg')


# ======================= ИГРОВАЯ ЛОГИКА =======================

def check_win(bet_type: str, number: int) -> bool:
    """Проверка выигрыша ставки"""
    # Ставка на конкретное число
    if bet_type.isdigit():
        return int(bet_type) == number

    # Чётность (0 не считается)
    if bet_type == "чет":
        return number != 0 and number % 2 == 0
    if bet_type == "нечет":
        return number % 2 == 1

    # Цвет
    if bet_type == "к":
        return number in RED_NUMBERS
    if bet_type == "ч":
        return number in BLACK_NUMBERS

    # Дюжины
    if bet_type == "п":
        return 1 <= number <= 12
    if bet_type == "в":
        return 13 <= number <= 24
    if bet_type == "т":
        return 25 <= number <= 36

    return False


def get_bet_category(bet_type: str) -> str:
    """Определение категории ставки для расчёта множителя и опыта"""
    if bet_type.isdigit():
        return 'number'
    if bet_type in ['к', 'ч']:
        return 'color'
    if bet_type in ['чет', 'нечет']:
        return 'parity'
    if bet_type in ['п', 'в', 'т']:
        return 'dozen'
    return 'unknown'


def calculate_roulette_exp(
        bet_type: str,
        won: bool,
        bet_amount: int,
        user_id: int
) -> float:
    """Расчёт опыта за игру в рулетку"""
    category = get_bet_category(bet_type)

    # Базовый опыт
    if won:
        base_exp = BASE_EXP.get(category, 0.5)
    else:
        base_exp = BASE_EXP['loss']

    # Бонусы
    mastery_bonus = get_user_bonuses(user_id, 'mastery')
    biz_bonuses = get_user_business_bonuses(user_id)
    business_bonus = biz_bonuses.get('game_mastery', 0)

    # Множитель от ставки
    exp_mult = calculate_exp_multiplier(bet_amount, mastery_bonus, business_bonus)

    return round(base_exp * exp_mult, 1)


def apply_luck_cashback(user_id: int, username: str, bet_amount: int) -> Tuple[int, str]:
    """
    Применение кэшбэка от таланта "Удача" при проигрыше
    Возвращает: (сумма_кэшбэка, текст_для_сообщения)
    """
    luck_bonus = get_user_bonuses(user_id, 'luck')

    if not luck_bonus:
        return 0, ''

    # Проверка срабатывания
    if random.randint(0, 100) < luck_bonus:
        cashback = round(bet_amount * 0.2)
        current_balance = get_balance(user_id, username)
        set_balance(user_id, current_balance + cashback)

        bonus_text = f"\n🍀 Тебе повезло! Возвращено 20% ({spaced_num(cashback)} $miles) от ставки!"
        return cashback, bonus_text

    return 0, ''


def format_bet_display(bet_type: str) -> str:
    """Форматирование названия ставки для отображения"""
    if bet_type.isdigit():
        return f"🔢 На число {bet_type}"
    return BET_NAMES.get(bet_type, f"❓ {bet_type}")


# ======================= БАЗА ДАННЫХ =======================

def create_game_if_needed(chat_id: int) -> None:
    """Создание игровой сессии для группы если её нет"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT * FROM roulette_games WHERE chat_id = %s AND is_active = TRUE",
        (chat_id,)
    )
    game = cursor.fetchone()

    if not game:
        now = datetime.now(timezone.utc)
        start_time = now + timedelta(seconds=GROUP_GAME_DURATION)
        deadline = start_time - timedelta(seconds=BETTING_DEADLINE_OFFSET)

        cursor.execute(
            "INSERT INTO roulette_games (chat_id, start_time, betting_deadline) VALUES (%s, %s, %s)",
            (chat_id, start_time, deadline)
        )
        conn.commit()


def can_place_bet(chat_id: int) -> Tuple[bool, Optional[str]]:
    """
    Проверка возможности сделать ставку в групповой игре
    Возвращает: (можно_ставить, сообщение_об_ошибке)
    """
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT * FROM roulette_games WHERE chat_id = %s AND is_active = TRUE",
        (chat_id,)
    )
    game = cursor.fetchone()

    if not game:
        return False, "⏳ Сейчас нет активной игры."

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deadline = game['betting_deadline'].replace(tzinfo=None)

    if now >= deadline:
        return False, "❌ Приём ставок окончен. Подождите следующую игру."

    return True, None


def add_or_update_bet(
        chat_id: int,
        user_id: int,
        username: str,
        bet_type: str,
        amount: int
) -> None:
    """Добавление или обновление ставки в групповой игре"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute("""
        INSERT INTO roulette_bets (chat_id, user_id, username, bet_type, amount)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE amount = amount + VALUES(amount)
    """, (chat_id, user_id, username, bet_type, amount))
    conn.commit()


def get_game_bets(chat_id: int) -> List[Dict]:
    """Получение всех ставок в текущей игре"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT * FROM roulette_bets WHERE chat_id = %s",
        (chat_id,)
    )
    return cursor.fetchall()


def get_user_first_name(user_id: int) -> str:
    """Получение имени пользователя для отображения"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT first_name FROM users WHERE telegram_id = %s",
        (user_id,)
    )
    result = cursor.fetchone()
    return result['first_name'] if result else f"User{user_id}"


# ======================= КОМАНДЫ =======================

async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /rt - игра в рулетку"""
    user = update.effective_user
    chat = update.effective_chat
    user_id = user.id
    username = user.username or f"id{user_id}"
    chat_id = chat.id
    is_private = chat.type == "private"

    ensure_user_exists(user)

    # Проверка аргументов
    if not context.args or len(context.args) < 2:
        help_text = (
            "❌ Укажи тип ставки и сумму. Пример: `/rt чет 1000`\n\n"
            "*Типы ставок:*\n"
            "• `к` — красное (x2)\n"
            "• `ч` — чёрное (x2)\n"
            "• `чет` — чётное (x2)\n"
            "• `нечет` — нечётное (x2)\n"
            "• `п` — первая дюжина 1-12 (x3)\n"
            "• `в` — вторая дюжина 13-24 (x3)\n"
            "• `т` — третья дюжина 25-36 (x3)\n"
            "• `0-36` — конкретное число (x36)\n\n"
            "*Примеры:*\n"
            "`/rt к 1000` — ставка $1000 на красное\n"
            "`/rt 7 500` — ставка $500 на число 7\n"
            "`/rt чет all` — ставка всех денег на чётное"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    bet_type = context.args[0].lower()

    # Валидация типа ставки
    if bet_type not in VALID_BET_TYPES:
        await update.message.reply_text("❌ Неверный тип ставки. Используй /rt без аргументов для справки.")
        return

    # Парсинг суммы ставки
    bet_amount = parse_bet_amount(context.args[1], user_id, username)

    if bet_amount is None:
        await update.message.reply_text("❌ Некорректная сумма ставки")
        return

    # Проверка баланса
    balance = get_balance(user_id, username)

    if bet_amount > balance:
        await update.message.reply_text(
            f"💸 Недостаточно средств.\n💰 Твой баланс: {spaced_num(balance)} $miles"
        )
        return

    if bet_amount < MIN_BET:
        await update.message.reply_text(f"💸 Минимальная ставка: {MIN_BET} $miles")
        return

    # ============= ЛИЧНАЯ ИГРА (приватный чат) =============
    if is_private:
        await play_solo_roulette(update, user_id, username, bet_type, bet_amount, balance)
        return

    # ============= ГРУППОВАЯ ИГРА =============
    create_game_if_needed(chat_id)

    can_bet, error_msg = can_place_bet(chat_id)
    if not can_bet:
        await update.message.reply_text(error_msg)
        return

    # Снимаем деньги и добавляем ставку
    set_balance(user_id, balance - bet_amount)
    add_or_update_bet(chat_id, user_id, username, bet_type, bet_amount)

    await update.message.reply_text(
        f"✅ Ставка {spaced_num(bet_amount)} $miles {format_bet_display(bet_type).lower()} принята."
    )


def generate_roulette_image(num: int) -> io.BytesIO:
    """Генерация изображения результата слотов"""

    num_img = NUMBERS_IMG_CACHE[str(num)]

    result = Image.new('RGB', (997, 562), (255, 255, 255))
    result.paste(MAIN_IMG_CACHE, (0, 0))

    result.paste(num_img, (373, 229), num_img)
    result = result.convert('RGB')
    bio = io.BytesIO()
    bio.name = f'temp_roulette_{random.randint(1000000, 9999999)}.jpeg'
    result.save(bio, 'JPEG', quality=30)
    bio.seek(0)
    return bio


async def play_solo_roulette(
        update: Update,
        user_id: int,
        username: str,
        bet_type: str,
        bet_amount: int,
        balance: int
):
    """Одиночная игра в рулетку (приватный чат)"""
    # Крутим рулетку
    number = random.randint(0, 36)

    # Проверяем выигрыш
    won = check_win(bet_type, number)
    category = get_bet_category(bet_type)

    # Снимаем ставку
    set_balance(user_id, balance - bet_amount)

    # Формируем результат
    result_text = f"🎲 Выпало число: *{number}*\n\n"

    if won:
        multiplier = MULTIPLIERS[category]
        winnings = bet_amount * multiplier

        set_balance(user_id, get_balance(user_id, username) + winnings)

        result_text += f"🎉 Ты выиграл {spaced_num(winnings)} $miles!\n"
    else:
        result_text += f"😢 Ты проиграл {spaced_num(bet_amount)} $miles.\n"

        # Шанс на кэшбэк
        cashback, bonus_text = apply_luck_cashback(user_id, username, bet_amount)
        result_text += bonus_text

    # Начисляем опыт
    exp_gained = calculate_roulette_exp(bet_type, won, bet_amount, user_id)
    update_experience(user_id, exp_gained)

    # Информация об уровне
    level_info = get_experience(user_id, username)
    current_level = level_info[0]
    current_xp = level_info[1]
    next_level_xp = next(
        (xp for lvl, xp in LEVELS if lvl == current_level + 1),
        float("inf")
    )

    result_text += (
        f"\n✨ Получено: {exp_gained} EXP\n"
        f"⭐️ Уровень: {current_level} ({current_xp}/{next_level_xp})\n"
        f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
    )
    image_stream = generate_roulette_image(number)
    # Отправляем с картинкой
    try:
        await update.message.reply_photo(
            photo=image_stream,
            caption=result_text,
            parse_mode="Markdown"
        )
        image_stream.close()
    except FileNotFoundError:
        await update.message.reply_text(result_text, parse_mode="Markdown")


async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /game - показать текущую групповую игру и ставки"""
    c = get_cursor()
    cursor, conn = c[0], c[1]
    chat_id = update.effective_chat.id

    cursor.execute(
        "SELECT * FROM roulette_games WHERE chat_id = %s AND is_active = TRUE",
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
    bets = get_game_bets(chat_id)

    if not bets:
        time_info = f"⏳ Игра начнётся через {seconds_left} сек." if seconds_left > 0 else "⏳ Игра сейчас начнётся..."
        await update.message.reply_text(f"🎱 Рулетка\n\n{time_info}\n\n📭 Ставок пока нет.")
        return

    # Группируем ставки по типу
    grouped_bets: Dict[str, List[str]] = {}

    for bet in bets:
        key = bet['bet_type']
        if key not in grouped_bets:
            grouped_bets[key] = []

        display_name = f"@{bet['username']}" if bet['username'] else get_user_first_name(bet['user_id'])
        grouped_bets[key].append(f"{display_name} — {spaced_num(bet['amount'])} $miles")

    # Формируем сообщение
    output = "🎱 *Рулетка*\n🏦 *Ставки:*\n\n"

    for bet_type, players in grouped_bets.items():
        title = format_bet_display(bet_type)
        output += f"{title}:\n" + "\n".join(players) + "\n——————————\n"

    time_info = f"⏳ Игра начнётся через {seconds_left} сек." if seconds_left > 0 else "⏳ Игра сейчас начнётся..."
    output += f"\n{time_info}"

    await update.message.reply_text(output, parse_mode="Markdown")


# ======================= ЗАВЕРШЕНИЕ ГРУППОВОЙ ИГРЫ =======================

async def start_roulette_for_chat(chat_id: int, bot: Bot):
    """Завершение групповой игры и подведение итогов"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    # Завершаем игру
    cursor.execute(
        "UPDATE roulette_games SET is_active = FALSE WHERE chat_id = %s",
        (chat_id,)
    )
    conn.commit()

    # Получаем ставки
    bets = get_game_bets(chat_id)

    if not bets:
        await bot.send_message(chat_id, "⛔ Игра завершена, но ставок не было.")
        return

    # Крутим рулетку
    number = random.randint(0, 36)
    # number = 0

    result_text = f"🎰 *Игра окончена!*\n🎲 Выпало число: *{number}*\n\n"

    win_log: List[str] = []
    lose_log: List[str] = []

    # Обрабатываем каждую ставку
    for bet in bets:
        user_id = bet['user_id']
        username = bet['username']
        amount = bet['amount']
        bet_type = bet['bet_type']

        display_name = f"@{username}" if username else get_user_first_name(user_id)

        # Проверяем выигрыш
        won = check_win(bet_type, number)
        category = get_bet_category(bet_type)

        if won:
            # Выигрыш
            multiplier = MULTIPLIERS[category]
            winnings = amount * multiplier

            set_balance(user_id, get_balance(user_id, username) + winnings)

            # Опыт
            exp_gained = calculate_roulette_exp(bet_type, True, amount, user_id)
            update_experience(user_id, exp_gained)

            win_log.append(
                f"{display_name} +{spaced_num(winnings)} $miles (✨ +{exp_gained} EXP)"
            )
        else:
            # Проигрыш
            exp_gained = calculate_roulette_exp(bet_type, False, amount, user_id)
            update_experience(user_id, exp_gained)

            # Проверка кэшбэка
            cashback, bonus_text = apply_luck_cashback(user_id, username, amount)

            lose_text = f"{display_name} -{spaced_num(amount)} $miles (✨ +{exp_gained} EXP)"
            if bonus_text:
                lose_text += f"\n  {bonus_text}"

            lose_log.append(lose_text)

    # Формируем итоговое сообщение
    if win_log:
        result_text += "🏆 *Победившие ставки:*\n" + "\n".join(win_log) + "\n\n"

    if lose_log:
        result_text += "🙈 *Проигравшие ставки:*\n" + "\n".join(lose_log)

    # Удаляем ставки и игру
    cursor.execute("DELETE FROM roulette_bets WHERE chat_id = %s", (chat_id,))
    cursor.execute("DELETE FROM roulette_games WHERE chat_id = %s", (chat_id,))
    conn.commit()

    # Отправляем результат
    image_stream = generate_roulette_image(number)
    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=image_stream,
            caption=result_text,
            parse_mode="Markdown"
        )
        image_stream.close()
    except FileNotFoundError:
        await bot.send_message(chat_id, result_text, parse_mode="Markdown")


async def check_all_games(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка готовности игр (вызывается из job_queue)"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    now = datetime.now(timezone.utc)

    cursor.execute("SELECT * FROM roulette_games WHERE is_active = TRUE")
    games = cursor.fetchall()

    for game in games:
        if game['start_time'].replace(tzinfo=None) <= now.replace(tzinfo=None):
            await start_roulette_for_chat(game['chat_id'], context.bot)


# ======================= ЭКСПОРТ =======================

__all__ = [
    'roulette',
    'game',
    'check_all_games',
    'start_roulette_for_chat'
]
