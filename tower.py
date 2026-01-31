from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes)
from random import *
from typing import Tuple

from constants import MIN_BET, LEVELS, TOWER
from helpers import ensure_user_exists, parse_bet_amount, spaced_num, get_balance, set_balance, get_tower_session, \
    create_tower_session, delete_tower_session, get_experience, update_experience, get_user_bonuses, \
    calculate_exp_multiplier, safe_reply_text
from helpers import get_user_business_bonuses


# ======================= ИГРОВАЯ ЛОГИКА =======================

def build_tower_keyboard(user_id: int, field: list, open_cells: list, game_over: bool = False):
    keyboard = []

    for row in reversed(range(5)):
        row_buttons = []
        for col in range(5):
            text = "❓"
            callback = f"tower:{row}:{col}:{user_id}"
            try:
                if row+1 > len(open_cells):
                    if col == open_cells[row]:
                        if field[row][col] == 0:
                            text = "💀"
                        else:
                            text = "💎"
                        callback = "tower_opened"

                    else:
                        if game_over and field[row][col] == 0:
                            text = "🚫"
                            callback = "tower_opened"
                else:
                    if field[row][col] == 0:
                        text = "💀"
                    else:
                        text = "💎"
                    callback = "tower_opened"
            except IndexError:
                pass

            row_buttons.append(
                InlineKeyboardButton(text, callback_data=callback)
            )

        keyboard.append(row_buttons)

    # Кнопка забрать
    if not game_over and len(open_cells) > 0:
        keyboard.append([
            InlineKeyboardButton("💰 Забрать", callback_data=f"tower_cashout:{user_id}")
        ])

    return InlineKeyboardMarkup(keyboard)


def create_field(difficulty: int) -> list:
    """
    Создаёт минное поле
    :param difficulty: сложность
    :return: поле с 25 клетками
    """

    field = []
    difficulty = min(4, difficulty)
    for row in range(5):
        r = [0] * difficulty + [1] * (5-difficulty)
        shuffle(r)
        field.append(r)
    return field


def count_multiplier(step: int, difficulty: int) -> float:
    """
    Подсчёт множителя для Tower
    :param step: текущий пройденный ряд (1, 2, 3...)
    :param difficulty: сложность (1-4)
    :return: множитель
    """
    if step == 0:
        return 1.0

    prob_per_step = (5 - difficulty) / 5
    total_prob = prob_per_step ** step
    multiplier = (1 / total_prob)

    return round(multiplier, 2)


def is_defeat(row: int, cell: int, field: list) -> bool:
    """
    Возвращает True, если игрок попался на мину, и False, если попал на безопасную клетку
    :param row: номер ряда (начиная с 0)
    :param cell: номер клетки (начиная с 0)
    :param field: поле
    :return:
    """
    return not field[row][cell]


# ======================= КОМАНДЫ =======================


async def tower(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Команда /tower - начало игры в тавер """
    user = update.effective_user
    user_id = user.id
    username = user.username

    ensure_user_exists(user)

    # Проверка наличия активной сессии
    if get_tower_session(user_id):
        await update.message.reply_text(
            "❌ У тебя уже есть активная игра. Заверши её, чтобы начать новую."
        )
        await send_tower_state(update, context, user_id, False)
        return

    # Проверка наличия аргументов
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Укажи сумму ставки и сложность. Пример: /tower 3 50\n"
            "Также можешь использовать: /tower 3 all, /tower 3 1k, /tower 3 5kk"
        )
        return

    # Парсинг ставки
    bet = parse_bet_amount(context.args[1], user_id, username)
    try:
        difficulty = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Некорректная сложность (от 1 до 4)")
        return

    if bet is None:
        await update.message.reply_text("❌ Некорректная ставка")
        return

    if difficulty > 4 or difficulty < 1:
        await update.message.reply_text("❌ Некорректная сложность (от 1 до 4)")
        return

    # Проверка лимитов
    balance = get_balance(user_id, username)

    if bet < MIN_BET:
        await update.message.reply_text(f"❌ Минимальная ставка: {spaced_num(MIN_BET)} $miles")
        return

    if bet > balance:
        await update.message.reply_text(
            f"❌ Недостаточно средств.\n💰 Твой баланс: {spaced_num(balance)} $miles"
        )
        return

    # Снимаем ставку
    set_balance(user_id, balance - bet)

    # Создаем поле
    field = create_field(difficulty)

    # Создаем сессию
    create_tower_session(user_id, bet, field, [])

    await send_tower_state(update, context, user_id)


async def send_tower_state(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        is_callback: bool = False
):
    """Отправка текущего состояния игры"""
    session = get_tower_session(user_id)

    if not session:
        if is_callback:
            await update.callback_query.answer("⚠️ Сессия не найдена", show_alert=True)
        return

    field = session["field"]
    open_cells = session["open_cells"]
    bet = session["bet"]
    difficulty = field[0].count(0)

    next_multiplier = count_multiplier(len(open_cells) + 1, difficulty)
    current_multiplier = count_multiplier(len(open_cells), difficulty)
    # Формируем текст
    text = (
        f"🛕 *Tower*\n"
        f"💵 Ставка: {spaced_num(bet)} $miles\n"
        f"🔰 Сложность: {difficulty}\n"
        f"🤑 Следующий кэф: X{next_multiplier}\n"
    )

    if len(open_cells) > 0:
        text += f"\n✅ Можно забрать: {spaced_num(current_multiplier * bet)} $miles"

    # Кнопки действий
    keyboard = build_tower_keyboard(
        user_id=user_id,
        field=field,
        open_cells=open_cells,
        game_over=False
    )

    if is_callback:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )


async def handle_tower_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кликов по полю Mines"""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    username = user.username
    # Парсим callback_data
    parts = query.data.split(':')
    if parts[0] == "tower":
        action = "tower"
        row = int(parts[1])
        cell = int(parts[2])
        session_owner = parts[3]
    elif parts[0] == "tower_opened":
        return
    elif parts[0] == "tower_cashout":
        action = "cashout"
        session_owner = parts[1]
    else:
        await query.answer("⚠️ Некорректные данные", show_alert=True)
        return

    # Проверка владельца сессии
    if str(session_owner) != str(user_id):
        await query.answer("⚠️ Это не твоя сессия!", show_alert=True)
        return

    # Получаем сессию
    session = get_tower_session(user_id)
    if not session:
        await query.answer("⚠️ Сессия не найдена", show_alert=True)
        return

    field = session["field"]
    open_cells = session["open_cells"]
    bet = session["bet"]
    difficulty = field[0].count(0)

    await query.answer()

    # =================== КЛИК ПО КЛЕТКЕ ===================
    if action == "tower":

        # Уже открыта — просто игнор
        if row >= len(open_cells):
            if cell == open_cells[row]:
                return

        open_cells.append(cell)

        # 💥 ПОРАЖЕНИЕ
        if field[row][cell] == 0:
            steps = len(open_cells)
            exp_gained = calculate_exp_reward(steps, bet, user_id, "lose")
            update_experience(user_id, exp_gained)

            cashback, bonus_text = apply_luck_cashback(user_id, username, bet)

            level, xp, next_level_xp = get_experience(user_id, username)

            text = (
                f"☠️ *НЕУДАЧА!* Ты попался\n\n"
                f"🔰 Сложность: {difficulty}\n"
                f"❌ Проигрыш: {spaced_num(bet)} $miles\n"
                f"{bonus_text}"
                f"✨ Получено: {exp_gained} EXP\n"
                f"⭐️ Уровень: {level} ({xp}/{next_level_xp})\n"
                f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
            )

            delete_tower_session(user_id)

            await query.edit_message_text(
                text=text,
                reply_markup=build_tower_keyboard(
                    user_id, field, open_cells, game_over=True
                ),
                parse_mode="Markdown"
            )
            return

        # ✅ Безопасная клетка — просто обновляем поле
        else:
            if len(open_cells) == 5:
                steps = len(open_cells)
                multiplier = count_multiplier(steps, difficulty)
                win_amount = int(bet * multiplier)
                win_bonus = get_user_business_bonuses(user_id).get("win_multiplier", 0)
                win_bonus_amount = int(win_amount * win_bonus)
                bonus_text = f"❇️ Бонус: {spaced_num(win_bonus_amount)} $miles\n\n" if win_bonus_amount else "\n"
                current_balance = get_balance(user_id, username)
                set_balance(user_id, current_balance + win_amount + win_bonus_amount)

                exp_gained = calculate_exp_reward(multiplier, bet, user_id, "win")
                update_experience(user_id, exp_gained)

                level, xp, next_level_xp = get_experience(user_id, username)

                text = (
                    f"🏁 *Ты прошел всю башню!*\n\n"
                    f"🔰 Сложность: {difficulty}\n"
                    f"🟠 Коэффициент: x{multiplier}\n\n"
                    f"💵 Ставка: {spaced_num(bet)} $miles\n"
                    f"💰 Выигрыш: {spaced_num(win_amount)} $miles\n"
                    f"{bonus_text}"
                    f"✨ Получено: {exp_gained} EXP\n"
                    f"⭐️ Уровень: {level} ({xp}/{next_level_xp})\n"
                    f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
                )

                delete_tower_session(user_id)

                await query.edit_message_text(
                    text=text,
                    reply_markup=build_tower_keyboard(
                        user_id, field, open_cells, game_over=True
                    ),
                    parse_mode="Markdown"
                )
                return
            create_tower_session(user_id, bet, field, open_cells)
            await send_tower_state(update, context, user_id, True)

    # =================== CASHOUT ===================
    elif action == "cashout":
        steps = len(open_cells)
        multiplier = count_multiplier(steps, difficulty)
        win_amount = int(bet * multiplier)
        win_bonus = get_user_business_bonuses(user_id).get("win_multiplier", 0)
        win_bonus_amount = int(win_amount * win_bonus)
        bonus_text = f"❇️ Бонус: {spaced_num(win_bonus_amount)} $miles\n\n" if win_bonus_amount else "\n"

        current_balance = get_balance(user_id, username)
        set_balance(user_id, current_balance + win_amount + win_bonus_amount)

        exp_gained = calculate_exp_reward(multiplier, bet, user_id, "win")
        update_experience(user_id, exp_gained)

        level, xp, next_level_xp = get_experience(user_id, username)

        text = (
            f"🏁 *Ты забрал выигрыш!*\n\n"
            f"🔰 Сложность: {difficulty}\n"
            f"🟢 Открыто этажей: {steps}\n"
            f"🟠 Коэффициент: x{multiplier}\n\n"
            f"💵 Ставка: {spaced_num(bet)} $miles\n"
            f"💰 Выигрыш: {spaced_num(win_amount)} $miles\n"
            f"{bonus_text}"
            f"✨ Получено: {exp_gained} EXP\n"
            f"⭐️ Уровень: {level} ({xp}/{next_level_xp})\n"
            f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
        )

        delete_tower_session(user_id)

        await query.edit_message_text(
            text=text,
            reply_markup=build_tower_keyboard(
                user_id, field, open_cells, game_over=True
            ),
            parse_mode="Markdown"
        )


# ======================= РАСЧЁТ РЕЗУЛЬТАТА =======================

def calculate_exp_reward(result: float, bet: int, user_id: int, state: str) -> float:
    """Расчёт опыта за игру с учётом множителей"""

    # Бонусы от талантов и бизнесов
    mastery_bonus = get_user_bonuses(user_id, 'mastery')
    biz_bonuses = get_user_business_bonuses(user_id)
    business_bonus = biz_bonuses.get('game_mastery', 0)

    # Множитель от ставки
    exp_mult = calculate_exp_multiplier(bet, mastery_bonus, business_bonus)
    exp = min(5000, result * exp_mult * TOWER[f'exp_{state}'])
    return round(exp, 1)


def apply_luck_cashback(user_id: int, username: str, bet: int) -> Tuple[int, str]:
    """
    Проверка и применение кэшбэка от таланта "Удача"
    Возвращает: (cashback_amount, bonus_text)
    """
    luck_bonus = get_user_bonuses(user_id, 'luck')

    if not luck_bonus:
        return 0, ''

    # Проверка срабатывания (процент от luck_bonus)
    if randint(0, 100) < luck_bonus:
        cashback = round(bet * 0.2)
        current_balance = get_balance(user_id, username)
        set_balance(user_id, current_balance + cashback)

        bonus_text = f"\n🍀 Тебе повезло! Возвращено 20% ({spaced_num(cashback)} $miles) от ставки!"
        return cashback, bonus_text

    return 0, ''
