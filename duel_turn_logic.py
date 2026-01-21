from typing import Optional, Tuple, Dict
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from constants import DUELS
from helpers import (
    set_balance, get_balance, spaced_num,
    get_user, get_cursor
)

# Извлекаем константы
GAME_ANIMATIONS = DUELS["animations"]
GAME_NAMES = DUELS["games"]


# ======================= ПОЛУЧЕНИЕ ДАННЫХ ДУЭЛИ =======================

def get_active_duel(user_id: int) -> Optional[Dict]:
    """
    Получение активной дуэли пользователя

    Args:
        user_id: ID пользователя

    Returns:
        Словарь с данными дуэли или None
    """
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT * FROM duels_sessions WHERE user_id = %s OR target_id = %s",
        (user_id, user_id)
    )

    return cursor.fetchone()


def get_duel_by_initiator(user_id: int) -> Optional[Dict]:
    """Получение дуэли по ID инициатора"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute("SELECT * FROM duels_sessions WHERE user_id = %s", (user_id,))
    return cursor.fetchone()


# ======================= ОБНОВЛЕНИЕ СОСТОЯНИЯ =======================

def update_player_score(duel_user_id: int, player_id: int, points: int) -> None:
    """
    Обновление счёта игрока и переключение хода

    Args:
        duel_user_id: ID инициатора дуэли (для поиска в БД)
        player_id: ID игрока, который сделал ход
        points: Количество очков
    """
    c = get_cursor()
    cursor, conn = c[0], c[1]

    # Определяем какой игрок ходил
    duel = get_duel_by_initiator(duel_user_id)

    if player_id == duel['user_id']:
        # Ход инициатора дуэли
        cursor.execute("""
            UPDATE duels_sessions 
            SET user_score = user_score + %s, 
                move = 'target', 
                current_round = current_round + 1 
            WHERE user_id = %s
        """, (points, duel_user_id))
    else:
        # Ход оппонента
        cursor.execute("""
            UPDATE duels_sessions 
            SET target_score = target_score + %s, 
                move = 'user' 
            WHERE user_id = %s
        """, (points, duel_user_id))

    conn.commit()


# ======================= ПРОВЕРКА ЗАВЕРШЕНИЯ =======================

def check_duel_completion(duel: Dict) -> Tuple[bool, Optional[str]]:
    """
    Проверка завершения дуэли

    Args:
        duel: Словарь с данными дуэли

    Returns:
        (завершена, результат_текст)
    """
    total_rounds = duel['round']
    current_round = duel['current_round']

    # Дуэль не завершена
    if current_round < total_rounds:
        return False, None

    # Определяем победителя
    user_score = duel['user_score']
    target_score = duel['target_score']

    user_name = get_user(user_id=int(duel['user_id']), username=None)
    target_name = get_user(user_id=int(duel['target_id']), username=None)
    game_display = GAME_NAMES.get(duel['game'], 'Игра')

    # Формируем базовый текст
    result_text = (
        f"🏁 <b>Дуэль завершена!</b>\n"
        f"🎮 Игра: {game_display}\n\n"
        f"👤 <b>{user_name}:</b> {user_score} очков\n"
        f"👤 <b>{target_name}:</b> {target_score} очков\n\n"
    )

    # Победитель
    if user_score > target_score:
        winner_id = duel['user_id']
        loser_id = duel['target_id']
        winner_name = user_name
    elif target_score > user_score:
        winner_id = duel['target_id']
        loser_id = duel['user_id']
        winner_name = target_name
    else:
        # Ничья
        result_text += "🤝 <b>Ничья!</b> Ставка возвращена обоим игрокам."
        return True, result_text

    # Обработка выигрыша
    bet = duel['bet']

    winner_balance = get_balance(winner_id)
    loser_balance = get_balance(loser_id)

    set_balance(winner_id, winner_balance + bet)
    set_balance(loser_id, loser_balance - bet)

    result_text += (
        f"🏆 <b>Победитель: {winner_name}!</b>\n"
        f"💰 Выигрыш: {spaced_num(bet)} $miles\n"
        f"💵 Новый баланс: {spaced_num(get_balance(winner_id))} $miles"
    )

    return True, result_text


def delete_duel_session(user_id: int) -> None:
    """Удаление сессии дуэли"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute("DELETE FROM duels_sessions WHERE user_id = %s", (user_id,))
    conn.commit()


# ======================= ОБРАБОТЧИК ХОДА =======================

async def handle_duel_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /turn - сделать ход в дуэли"""
    user_id = update.effective_user.id

    # Получаем активную дуэль
    duel = get_active_duel(user_id)

    if not duel:
        await update.message.reply_text("❌ У тебя нет активной дуэли.")
        return

    # Проверка очереди хода
    current_move = duel['move']
    expected_id = duel['user_id'] if current_move in ('', 'user') else duel['target_id']


    if user_id != expected_id:
        await update.message.reply_text("⏳ Сейчас ход другого игрока.")
        return
    if user_id == expected_id and get_balance(duel['target_id']) < duel['bet'] and duel['current_round'] == 0:
        await update.message.reply_text("❌ У тебя недостаточно денег на балансе. Дуэль отменена.")
        delete_duel_session(duel['user_id'])
        return
    elif user_id == expected_id and get_balance(duel['user_id']) < duel['bet'] and duel['current_round'] == 0:
        await update.message.reply_text("❌ У оппонента недостаточно денег на балансе. Дуэль отменена.")
        delete_duel_session(duel['user_id'])
        return
    # Получаем игру и эмодзи
    game = duel['game']
    emoji = GAME_ANIMATIONS.get(game, '🎲')
    game_display = GAME_NAMES.get(game, 'Игра')

    # Отправка анимированного броска
    game_msg = await update.message.reply_dice(emoji=emoji)
    result = game_msg.dice.value

    # Формируем сообщение о ходе
    player_name = get_user(user_id=int(user_id), username=None)
    msg = (
        f"{emoji} <b>{player_name}</b> сделал ход!\n"
        f"🎯 Очки: <b>{result}</b>"
    )

    # Уведомляем обоих игроков
    await context.bot.send_message(
        chat_id=duel['user_id'],
        text=msg,
        parse_mode=ParseMode.HTML
    )
    await context.bot.send_message(
        chat_id=duel['target_id'],
        text=msg,
        parse_mode=ParseMode.HTML
    )

    # Обновляем счёт
    update_player_score(duel['user_id'], user_id, result)

    # Проверяем завершение
    updated_duel = get_duel_by_initiator(duel['user_id'])
    is_completed, result_text = check_duel_completion(updated_duel)

    if is_completed:
        # Отправляем результаты
        await context.bot.send_message(
            chat_id=updated_duel['user_id'],
            text=result_text,
            parse_mode=ParseMode.HTML
        )
        await context.bot.send_message(
            chat_id=updated_duel['target_id'],
            text=result_text,
            parse_mode=ParseMode.HTML
        )

        # Удаляем сессию
        delete_duel_session(updated_duel['user_id'])
    else:
        # Уведомляем следующего игрока
        next_player_id = (
            updated_duel['target_id']
            if user_id == updated_duel['user_id']
            else updated_duel['user_id']
        )

        current_round = updated_duel['current_round']
        total_rounds = updated_duel['round']

        await context.bot.send_message(
            chat_id=next_player_id,
            text=(
                f"👊 Твой ход!\n"
                f"📊 Раунд {current_round}/{total_rounds}\n"
                f"💬 Напиши /turn"
            )
        )


# ======================= ЭКСПОРТ =======================

__all__ = [
    'handle_duel_turn',
    'get_active_duel',
    'get_duel_by_initiator',
    'update_player_score',
    'check_duel_completion',
    'delete_duel_session'
]
