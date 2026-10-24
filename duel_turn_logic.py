from typing import Optional, Tuple, Dict
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from constants import DUELS
from helpers import (
    get_balance, spaced_num,
    get_user, get_db_connection, credit_balance
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
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "SELECT * FROM duels_sessions WHERE user_id = %s OR target_id = %s",
            (user_id, user_id)
        )
        return cursor.fetchone()

def has_duel_between(user1_id: int, user2_id: int) -> bool:
    """Проверяет, есть ли уже дуэль конкретно между двумя игроками user1 и user2"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("""
            SELECT 1 FROM duels_sessions 
            WHERE (user_id = %s AND target_id = %s) 
               OR (user_id = %s AND target_id = %s)
        """, (user1_id, user2_id, user2_id, user1_id))
        return cursor.fetchone() is not None
    
def get_duel_pair(user_id: int, target_id: int) -> Optional[Dict]:
    """Получение конкретной дуэли между двумя игроками"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "SELECT * FROM duels_sessions WHERE user_id = %s AND target_id = %s",
            (user_id, target_id)
        )
        return cursor.fetchone()

def get_duel_by_initiator(user_id: int) -> Optional[Dict]:
    """Получение дуэли по ID инициатора"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("SELECT * FROM duels_sessions WHERE user_id = %s", (user_id,))
        return cursor.fetchone()

def get_my_turn_duel(user_id: int) -> Optional[Dict]:
    """Ищет активную дуэль, в которой сейчас очередь ходить именно этому игроку"""
    with get_db_connection() as (cursor, conn):
        cursor.execute("""
            SELECT * FROM duels_sessions 
            WHERE round > 0 AND (
                (user_id = %s AND move IN ('', 'user')) OR 
                (target_id = %s AND move = 'target')
            )
            LIMIT 1
        """, (user_id, user_id))
        return cursor.fetchone()

# ======================= ОБНОВЛЕНИЕ СОСТОЯНИЯ =======================

def update_player_score(duel_user_id: int, duel_target_id: int, player_id: int, points: int) -> None:
    """
    Обновление счёта игрока и переключение хода

    Args:
        duel_user_id: ID инициатора дуэли (для поиска в БД)
        player_id: ID игрока, который сделал ход
        points: Количество очков
    """
    with get_db_connection() as (cursor, conn):
        if player_id == duel_user_id:
            # Ход инициатора дуэли
            cursor.execute("""
                UPDATE duels_sessions 
                SET user_score = user_score + %s, 
                    move = 'target', 
                    current_round = current_round + 1 
                WHERE user_id = %s AND target_id = %s
            """, (points, duel_user_id, duel_target_id))
        else:
            # Ход оппонента
            cursor.execute("""
                UPDATE duels_sessions 
                SET target_score = target_score + %s, 
                    move = 'user' 
                WHERE user_id = %s AND target_id = %s
            """, (points, duel_user_id, duel_target_id))

        conn.commit()


# ======================= ПРОВЕРКА ЗАВЕРШЕНИЯ =======================

def check_duel_completion(duel: Optional[Dict]) -> Tuple[bool, Optional[str]]:
    """
    Проверка завершения дуэли

    Args:
        duel: Словарь с данными дуэли

    Returns:
        (завершена, результат_текст)
    """
    if not duel:
        return False, None

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

    bet = duel['bet']

    # Ничья
    if user_score == target_score:
        credit_balance(int(duel['user_id']), bet)
        credit_balance(int(duel['target_id']), bet)
        result_text += "🤝 <b>Ничья!</b> Ставка возвращена обоим игрокам."
        return True, result_text

    # Победитель
    if user_score > target_score:
        winner_id = int(duel['user_id'])
        winner_name = user_name
    else:
        winner_id = int(duel['target_id'])
        winner_name = target_name

    # Ставки были заморожены у обоих при старте дуэли, победитель забирает весь банк (bet * 2)
    credit_balance(winner_id, bet * 2)

    result_text += (
        f"🏆 <b>Победитель: {winner_name}!</b>\n"
        f"💰 Выигрыш: {spaced_num(bet)} $miles\n"
        f"💵 Новый баланс: {spaced_num(get_balance(winner_id))} $miles"
    )

    return True, result_text


def delete_duel_session(user_id: int, target_id: int) -> None:
    """Удаление конкретной сессии дуэли между двумя игроками"""
    with get_db_connection() as (cursor, conn):
        cursor.execute(
            "DELETE FROM duels_sessions WHERE user_id = %s AND target_id = %s",
            (user_id, target_id)
        )
        conn.commit()


# ======================= ОБРАБОТЧИК ХОДА =======================

async def handle_duel_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /turn - сделать ход в дуэли"""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    # Получаем активную дуэль, где сейчас ход игрока
    duel = get_my_turn_duel(user_id)

    if not duel:
        # Если нашего хода нет, проверяем — может дуэль есть, но ход у соперника?
        if get_active_duel(user_id):
            await update.message.reply_text("⏳ Сейчас ход другого игрока.")
        else:
            await update.message.reply_text("❌ У тебя нет активной дуэли.")
        return

    # Получаем игру и эмодзи
    game = duel['game']
    emoji = GAME_ANIMATIONS.get(game, '🎲')
    game_display = GAME_NAMES.get(game, 'Игра')

    # Отправка анимированного броска
    game_msg = await update.message.reply_dice(emoji=emoji)
    result = game_msg.dice.value if game_msg and game_msg.dice else 1

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

    # Обновляем счёт (передаём и user_id, и target_id конкретной дуэли)
    update_player_score(duel['user_id'], duel['target_id'], user_id, result)

    # Проверяем завершение конкретной дуэли
    updated_duel = get_duel_pair(duel['user_id'], duel['target_id'])
    if not updated_duel:
        return

    is_completed, result_text = check_duel_completion(updated_duel)

    if is_completed and result_text:
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

        # Удаляем только эту сессию дуэли
        delete_duel_session(updated_duel['user_id'], updated_duel['target_id'])
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
    'delete_duel_session',
    "has_duel_between",
]
