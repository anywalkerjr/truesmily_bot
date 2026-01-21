from typing import Optional, Dict
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from constants import DUELS
from helpers import get_user, get_cursor, spaced_num
from duel_turn_logic import delete_duel_session

# Извлекаем константы
GAME_NAMES = DUELS["games"]
MIN_ROUNDS = DUELS["min_rounds"]
MAX_ROUNDS = DUELS["max_rounds"]


# ======================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =======================

def get_duel_session(user_id: int, target_id: int) -> Optional[Dict]:
    """
    Получение сессии дуэли между двумя игроками

    Args:
        user_id: ID инициатора
        target_id: ID оппонента

    Returns:
        Словарь с данными дуэли или None
    """
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT * FROM duels_sessions WHERE user_id = %s AND target_id = %s",
        (user_id, target_id)
    )

    return cursor.fetchone()


def update_duel_game(user_id: int, target_id: int, game_key: str) -> None:
    """Обновление типа игры в сессии дуэли"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "UPDATE duels_sessions SET game = %s WHERE user_id = %s AND target_id = %s",
        (game_key, user_id, target_id)
    )
    conn.commit()


def update_duel_rounds(user_id: int, target_id: int, rounds: int) -> None:
    """Обновление количества раундов и начало игры"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute("""
        UPDATE duels_sessions 
        SET round = %s, move = 'target', current_round = 0
        WHERE user_id = %s AND target_id = %s
    """, (rounds, user_id, target_id))

    conn.commit()


# ======================= ОБРАБОТЧИК ВЫБОРА ИГРЫ =======================

async def handle_game_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа игры для дуэли"""
    query = update.callback_query
    clicker_id = query.from_user.id

    # Парсинг данных: duel_game:dice:123456:789012
    try:
        _, game_key, user_id, target_id = query.data.split(':')
        user_id = int(user_id)
        target_id = int(target_id)
    except (ValueError, IndexError):
        await query.answer("❌ Ошибка данных", show_alert=True)
        return

    # Проверка прав (только инициатор может выбрать игру)
    if clicker_id != user_id:
        await query.answer("⚠️ Это не твоя сессия!", show_alert=True)
        return

    # Проверка существования игры
    if game_key not in GAME_NAMES:
        await query.answer("❌ Неизвестная игра", show_alert=True)
        return

    await query.answer()

    # Обновляем тип игры
    update_duel_game(user_id, target_id, game_key)

    # Создаём кнопки выбора раундов (1-10)
    buttons = []
    row = []

    for i in range(MIN_ROUNDS, min(MAX_ROUNDS + 1, 11)):  # Максимум 10 раундов
        row.append(
            InlineKeyboardButton(
                f"{i} {'раунд' if i == 1 else 'раунда' if i < 5 else 'раундов'}",
                callback_data=f"rounds:{i}:{user_id}:{target_id}"
            )
        )

        # По 3 кнопки в ряд
        if len(row) == 3:
            buttons.append(row)
            row = []

    # Добавляем оставшиеся кнопки
    if row:
        buttons.append(row)

    game_display = GAME_NAMES[game_key]

    await query.edit_message_text(
        f"✅ Игра выбрана: {game_display}\n\n"
        f"🎯 Теперь выбери количество раундов:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ======================= ОБРАБОТЧИК ВЫБОРА РАУНДОВ =======================

async def handle_round_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора количества раундов и старт дуэли"""
    query = update.callback_query
    clicker_id = query.from_user.id

    # Парсинг данных: rounds:3:123456:789012
    try:
        _, rounds_str, user_id, target_id = query.data.split(':')
        rounds = int(rounds_str)
        user_id = int(user_id)
        target_id = int(target_id)
    except (ValueError, IndexError):
        await query.answer("❌ Ошибка данных", show_alert=True)
        return

    # Проверка прав (только инициатор выбирает раунды)
    if clicker_id != user_id:
        await query.answer("⚠️ Это не твой выбор!", show_alert=True)
        return

    # Валидация количества раундов
    if not (MIN_ROUNDS <= rounds <= MAX_ROUNDS):
        await query.answer(
            f"❌ Количество раундов должно быть от {MIN_ROUNDS} до {MAX_ROUNDS}",
            show_alert=True
        )
        return

    await query.answer()

    # Обновляем количество раундов
    update_duel_rounds(user_id, target_id, rounds)

    # Загружаем полную информацию о дуэли
    duel = get_duel_session(user_id, target_id)

    if not duel:
        await query.edit_message_text("❌ Сессия дуэли не найдена.")
        return

    # Формируем сообщение о начале
    game_display = GAME_NAMES.get(duel['game'], 'Игра')
    user_name = get_user(user_id=user_id, username=None)
    target_name = get_user(user_id=target_id, username=None)

    await query.edit_message_text(
        f"✅ Игра настроена!\n"
        f"🎮 {game_display}\n"
        f"🎯 Раундов: {rounds}\n\n"
        f"📢 Запускаем дуэль..."
    )

    # Формируем сообщение для обоих игроков
    duel_msg = (
        f"⚔️ <b>ДУЭЛЬ НАЧИНАЕТСЯ!</b>\n\n"
        f"🎮 Игра: {game_display}\n"
        f"🎯 Раундов: {rounds}\n"
        f"💰 Ставка: {spaced_num(duel['bet'])} $miles\n\n"
        f"👤 Игрок 1: {user_name}\n"
        f"👤 Игрок 2: {target_name}\n\n"
        f"👉 <b>Сейчас ходит {target_name}!</b>"
    )

    # Кнопка отказа (только для оппонента, только до первого хода)
    decline_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "❌ Отказаться",
            callback_data=f'decline:{target_id}:{user_id}'
        )
    ]])

    # Отправляем сообщения
    await context.bot.send_message(
        chat_id=user_id,
        text=duel_msg,
        parse_mode=ParseMode.HTML
    )

    await context.bot.send_message(
        chat_id=target_id,
        text=duel_msg + "\n\n👊 Напиши /turn, чтобы сделать ход",
        parse_mode=ParseMode.HTML,
        reply_markup=decline_keyboard
    )


# ======================= ОБРАБОТЧИК ОТКАЗА =======================

async def decline_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отклонение дуэли оппонентом"""
    query = update.callback_query
    user = query.from_user

    # Парсинг данных: decline:789012:123456
    try:
        _, target_id, user_id = query.data.split(':')
        target_id = int(target_id)
        user_id = int(user_id)
    except (ValueError, IndexError):
        await query.answer("❌ Ошибка данных", show_alert=True)
        return

    # Проверка прав (только оппонент может отказаться)
    if user.id != target_id:
        await query.answer("⚠️ Это не твоя дуэль!", show_alert=True)
        return

    # Получаем дуэль
    duel = get_duel_session(user_id, target_id)

    if not duel:
        await query.answer("⚠️ Дуэли больше нет!", show_alert=True)
        return

    # Проверка что игра ещё не началась
    current_round = duel.get('current_round', 0)
    current_move = duel.get('move', '')

    if current_round > 0 or current_move not in ('', 'target'):
        await query.answer("⚠️ Дуэль уже началась! Нельзя отказаться.", show_alert=True)
        return

    await query.answer()

    # Удаляем сессию
    delete_duel_session(user_id)

    # Уведомляем игроков
    user_name = get_user(user_id=user.id, username=None)
    game_display = GAME_NAMES.get(duel['game'], 'Игра')

    cancel_msg = (
        f"⚠️ <b>Дуэль отменена!</b>\n\n"
        f"🎮 {game_display}\n"
        f"💰 Ставка: {spaced_num(duel['bet'])} $miles\n\n"
        f"👤 {user_name} отказался от дуэли."
    )

    await context.bot.send_message(
        chat_id=user_id,
        text=cancel_msg,
        parse_mode=ParseMode.HTML
    )

    await query.edit_message_text(
        "⚠️ Ты отказался от дуэли.\n"
        "Ставка не снималась с баланса."
    )


# ======================= ЭКСПОРТ =======================

__all__ = [
    'handle_game_selection',
    'handle_round_selection',
    'decline_duel',
    'get_duel_session',
    'update_duel_game',
    'update_duel_rounds'
]
