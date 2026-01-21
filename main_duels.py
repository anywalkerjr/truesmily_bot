from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from constants import DUELS, MIN_BET
from helpers import (
    get_balance, spaced_num,
    user_exists, get_cursor, parse_bet_amount,
    ensure_user_exists
)

# Извлекаем константы
GAME_NAMES = DUELS["games"]
DEFAULT_ROUNDS = DUELS["default_rounds"]


# ======================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =======================

def find_user_by_username(username: str) -> Optional[int]:
    """
    Поиск пользователя по username

    Args:
        username: Имя пользователя без @

    Returns:
        telegram_id или None
    """
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT telegram_id FROM users WHERE username = %s",
        (username,)
    )

    result = cursor.fetchone()
    return result['telegram_id'] if result else None


def create_duel_session(user_id: int, target_id: int, bet: int) -> bool:
    """
    Создание или обновление сессии дуэли

    Args:
        user_id: ID инициатора
        target_id: ID оппонента
        bet: Размер ставки

    Returns:
        True если успешно
    """
    c = get_cursor()
    cursor, conn = c[0], c[1]

    try:
        cursor.execute("""
            INSERT INTO duels_sessions 
            (user_id, target_id, bet, game, round, user_score, target_score, move, current_round)
            VALUES (%s, %s, %s, '', %s, 0, 0, '', 0)
            ON DUPLICATE KEY UPDATE bet = VALUES(bet)
        """, (user_id, target_id, bet, DEFAULT_ROUNDS))

        conn.commit()
        return True
    except Exception as e:
        print(f"Error creating duel session: {e}")
        return False


def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[tuple]:
    """
    Определение оппонента из аргументов команды или ответа

    Returns:
        (target_id, target_username) или None
    """
    # Способ 1: Ответ на сообщение
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        return target.id, target.username or f"id{target.id}"

    # Способ 2: Указан @username
    if len(context.args) >= 2 and context.args[0].startswith("@"):
        username = context.args[0][1:]  # Убираем @
        target_id = find_user_by_username(username)

        if target_id:
            return target_id, username

    return None


# ======================= КОМАНДА /duel =======================

async def duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /duel - вызов на дуэль

    Примеры использования:
    /duel @username 1000 - вызвать пользователя на ставку $1000
    /duel 5k (ответом на сообщение) - вызвать на ставку $5000
    /duel @username all - вызвать на весь баланс
    """
    user = update.effective_user
    user_id = user.id
    username = user.username

    ensure_user_exists(user)

    # Проверка аргументов
    if not context.args:
        await update.message.reply_text(
            "❌ Укажи ставку и соперника!\n\n"
            "*Примеры:*\n"
            "`/duel @username 1000` - вызвать на $1000\n"
            "`/duel 5k` (ответом) - вызвать на $5000\n"
            "`/duel @username all` - вызвать на весь баланс\n\n"
            "*Доступные ставки:*\n"
            "• Числа: `100`, `1000`, `50000`\n"
            "• С множителями: `1k`, `5kk`, `10kkk`\n"
            "• Весь баланс: `all`",
            parse_mode="Markdown"
        )
        return

    # Парсинг ставки (последний аргумент)
    bet = parse_bet_amount(context.args[-1], user_id, username)

    if bet is None:
        await update.message.reply_text("❌ Некорректная ставка")
        return

    # Проверка минимальной ставки
    if bet < MIN_BET:
        await update.message.reply_text(
            f"💸 Минимальная ставка: {spaced_num(MIN_BET)} $miles"
        )
        return

    # Определение оппонента
    target_data = get_target_user(update, context)

    if not target_data:
        await update.message.reply_text(
            "❌ Укажи соперника корректно:\n"
            "• Ответь на сообщение: `/duel 1000`\n"
            "• Упомяни пользователя: `/duel @username 1000`",
            parse_mode="Markdown"
        )
        return

    target_id, target_username = target_data

    # Проверка что не вызываешь сам себя
    if target_id == user_id:
        await update.message.reply_text("❌ Нельзя вызвать себя на дуэль!")
        return

    # Проверка существования оппонента
    if not user_exists(target_id):
        await update.message.reply_text(
            "❌ Этот пользователь ещё не играл в бота.\n"
            "Попроси его написать /start"
        )
        return

    # Проверка баланса инициатора
    user_balance = get_balance(user_id, username)

    if user_balance < bet:
        await update.message.reply_text(
            f"💸 Недостаточно средств.\n"
            f"💰 Твой баланс: {spaced_num(user_balance)} $miles\n"
            f"💵 Требуется: {spaced_num(bet)} $miles"
        )
        return

    # Проверка баланса оппонента
    target_balance = get_balance(target_id, target_username)

    if target_balance < bet:
        await update.message.reply_text(
            f"💸 У соперника недостаточно средств.\n"
            f"💰 Баланс @{target_username}: {spaced_num(target_balance)} $miles\n"
            f"💵 Требуется: {spaced_num(bet)} $miles"
        )
        return

    # Создаём сессию дуэли
    success = create_duel_session(user_id, target_id, bet)

    if not success:
        await update.message.reply_text("❌ Ошибка при создании дуэли. Попробуй позже.")
        return

    # Создаём кнопки выбора игры
    buttons = [
        [InlineKeyboardButton(
            name,
            callback_data=f'duel_game:{key}:{user_id}:{target_id}'
        )]
        for key, name in GAME_NAMES.items()
    ]

    await update.message.reply_text(
        f"⚔️ *Дуэль создана!*\n\n"
        f"💰 Ставка: {spaced_num(bet)} $miles\n"
        f"👤 Соперник: @{target_username}\n\n"
        f"🎮 Выбери игру:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )


# ======================= ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ =======================

async def my_duels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /my_duels - показать активные дуэли"""
    user_id = update.effective_user.id

    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute("""
        SELECT * FROM duels_sessions 
        WHERE user_id = %s OR target_id = %s
    """, (user_id, user_id))

    duels = cursor.fetchall()

    if not duels:
        await update.message.reply_text(
            "📭 У тебя нет активных дуэлей.\n"
            "Вызови кого-нибудь: /duel @username 1000"
        )
        return

    # Формируем список дуэлей
    message = "⚔️ *Твои активные дуэли:*\n\n"

    for i, duel in enumerate(duels, 1):
        game_display = GAME_NAMES.get(duel['game'], 'Выбор игры...')

        is_initiator = duel['user_id'] == user_id
        opponent_id = duel['target_id'] if is_initiator else duel['user_id']

        # Получаем имя оппонента
        cursor.execute(
            "SELECT username, first_name FROM users WHERE telegram_id = %s",
            (opponent_id,)
        )
        opp_data = cursor.fetchone()
        opponent_name = f"@{opp_data['username']}" if opp_data and opp_data['username'] else f"User{opponent_id}"

        # Статус дуэли
        if not duel['game']:
            status = "🔄 Выбор игры"
        elif duel['current_round'] == 0:
            status = "⏳ Ожидание старта"
        else:
            status = f"🎮 Раунд {duel['current_round']}/{duel['round']}"

        message += (
            f"*{i}.* {game_display}\n"
            f"   👤 Соперник: {opponent_name}\n"
            f"   💰 Ставка: {spaced_num(duel['bet'])} $miles\n"
            f"   📊 {status}\n\n"
        )

    await update.message.reply_text(message, parse_mode="Markdown")


# ======================= ЭКСПОРТ =======================

__all__ = [
    'duel',
    'my_duels',
    'create_duel_session',
    'find_user_by_username',
    'get_target_user'
]
