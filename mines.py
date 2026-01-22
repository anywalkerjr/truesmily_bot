from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes)
from random import *
from typing import Tuple

from constants import MIN_BET, LEVELS, MINES
from helpers import ensure_user_exists, parse_bet_amount, spaced_num, get_balance, set_balance, get_mines_session, \
    create_mines_session, delete_mines_session, get_experience, update_experience, get_user_bonuses, \
    calculate_exp_multiplier
from helpers import get_user_business_bonuses


# ======================= ИГРОВАЯ ЛОГИКА =======================

def build_mines_keyboard(user_id: int, field: list, open_cells: list, game_over: bool = False):
    keyboard = []

    for row in range(5):
        row_buttons = []
        for col in range(5):
            idx = row * 5 + col

            # Уже открытая клетка
            if idx in open_cells:
                if field[idx] == 0:
                    text = "💥"
                else:
                    text = "✅"

                callback = "opened"

            else:
                if game_over and field[idx] == 0:
                    text = "💣"
                    callback = "opened"
                else:
                    text = "❓"
                    callback = f"mine:{idx}:{user_id}"

            row_buttons.append(
                InlineKeyboardButton(text, callback_data=callback)
            )

        keyboard.append(row_buttons)

    # Кнопка забрать
    if not game_over and len(open_cells) > 0:
        keyboard.append([
            InlineKeyboardButton("💰 Забрать", callback_data=f"cashout:{user_id}")
        ])

    return InlineKeyboardMarkup(keyboard)


def create_field(mines_count: int) -> list:
    """
    Создаёт минное поле
    :param mines_count: количество мин
    :return: поле с 25 клетками
    """

    field = [0] * mines_count + [1] * (25 - mines_count)
    shuffle(field)
    return field


def count_multiplier(step: int, mines: int) -> float:
    """
    Подсчёт множителя ставки
    :param step: шаг
    :param mines: количество мин
    :return: множитель
    """

    total = 25
    prob = 0.95

    for i in range(step):
        prob *= (total - mines - i) / (total - i)

    return round(1 / prob, 2)


def is_defeat(cell: int, field: list) -> bool:
    """
    Возвращает True, если игрок попался на мину, и False, если попал на безопасную клетку
    :param cell: номер клетки (начиная с 0)
    :param field: поле
    :return:
    """
    return not field[cell]


# ======================= КОМАНДЫ =======================


async def mines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Команда /mines - начало игры в минки """
    user = update.effective_user
    user_id = user.id
    username = user.username

    ensure_user_exists(user)

    # Проверка наличия активной сессии
    if get_mines_session(user_id):
        await update.message.reply_text(
            "❌ У тебя уже есть активная игра. Заверши её, чтобы начать новую."
        )
        await send_mines_state(update, context, user_id, False)
        return

    # Проверка наличия аргументов
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Укажи сумму ставки и количество мин. Пример: /mines 3 50\n"
            "Также можешь использовать: /mines 3 all, /mines 3 1k, /mines 3 5kk"
        )
        return

    # Парсинг ставки
    bet = parse_bet_amount(context.args[1], user_id, username)
    try:
        mines = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Некорректное количество мин (от 1 до 24)")
        return

    if bet is None:
        await update.message.reply_text("❌ Некорректная ставка")
        return

    if mines > 24 or mines < 2:
        await update.message.reply_text("❌ Некорректное количество мин (от 2 до 24)")
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
    field = create_field(mines)

    # Создаем сессию
    create_mines_session(user_id, bet, field, [])

    await send_mines_state(update, context, user_id)


async def send_mines_state(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        is_callback: bool = False
):
    """Отправка текущего состояния игры"""
    session = get_mines_session(user_id)

    if not session:
        if is_callback:
            await update.callback_query.answer("⚠️ Сессия не найдена", show_alert=True)
        return

    field = session["field"]
    open_cells = session["open_cells"]
    bet = session["bet"]

    next_multiplier = count_multiplier(len(open_cells) + 1, field.count(0))
    current_multiplier = count_multiplier(len(open_cells), field.count(0))
    # Формируем текст
    text = (
        f"🃏 *Mines*\n"
        f"💵 Ставка: {spaced_num(bet)} $miles\n"
        f"💣 Количество мин: {field.count(0)}\n"
        f"🤑 Следующий кэф: X{next_multiplier}\n"
    )

    if len(open_cells) > 0:
        text += f"\n✅ Можно забрать: {spaced_num(current_multiplier * bet)} $miles"

    # Кнопки действий
    keyboard = build_mines_keyboard(
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


async def handle_mines_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кликов по полю Mines"""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    username = user.username
    # Парсим callback_data
    parts = query.data.split(':')
    if parts[0] == "mine":
        action = "mine"
        idx = int(parts[1])
        session_owner = parts[2]
    elif parts[0] == "opened":
        return
    elif parts[0] == "cashout":
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
    session = get_mines_session(user_id)
    if not session:
        await query.answer("⚠️ Сессия не найдена", show_alert=True)
        return

    field = session["field"]
    open_cells = session["open_cells"]
    bet = session["bet"]

    await query.answer()

    # =================== КЛИК ПО КЛЕТКЕ ===================
    if action == "mine":

        # Уже открыта — просто игнор
        if idx in open_cells:
            return

        open_cells.append(idx)

        # 💥 ПОРАЖЕНИЕ
        if field[idx] == 0:
            steps = len(open_cells)
            multiplier = count_multiplier(steps, field.count(0))
            exp_gained = calculate_exp_reward(multiplier, bet, user_id, "lose")
            update_experience(user_id, exp_gained)

            cashback, bonus_text = apply_luck_cashback(user_id, username, bet)

            level, xp, next_level_xp = get_experience(user_id, username)

            text = (
                f"💥 *ВЗРЫВ!* Ты попал на мину\n\n"
                f"💣 Количество мин: {field.count(0)}\n"
                f"❌ Проигрыш: {spaced_num(bet)} $miles\n"
                f"{bonus_text}"
                f"✨ Получено: {exp_gained} EXP\n"
                f"⭐️ Уровень: {level} ({xp}/{next_level_xp})\n"
                f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
            )

            delete_mines_session(user_id)

            await query.edit_message_text(
                text=text,
                reply_markup=build_mines_keyboard(
                    user_id, field, open_cells, game_over=True
                ),
                parse_mode="Markdown"
            )
            return

        # ✅ Безопасная клетка — просто обновляем поле
        else:
            if len(open_cells) == field.count(1):
                steps = len(open_cells)
                multiplier = count_multiplier(steps, field.count(0))
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
                    f"🏁 *Ты открыл все клетки!*\n\n"
                    f"💣 Всего мин: {field.count(0)}\n"
                    f"🟠 Коэффициент: x{multiplier}\n\n"
                    f"💵 Ставка: {spaced_num(bet)} $miles\n"
                    f"💰 Выигрыш: {spaced_num(win_amount)} $miles\n"
                    f"{bonus_text}"
                    f"✨ Получено: {exp_gained} EXP\n"
                    f"⭐️ Уровень: {level} ({xp}/{next_level_xp})\n"
                    f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
                )

                delete_mines_session(user_id)

                await query.edit_message_text(
                    text=text,
                    reply_markup=build_mines_keyboard(
                        user_id, field, open_cells, game_over=True
                    ),
                    parse_mode="Markdown"
                )
                return
            create_mines_session(user_id, bet, field, open_cells)
            await send_mines_state(update, context, user_id, True)

    # =================== CASHOUT ===================
    elif action == "cashout":
        steps = len(open_cells)
        multiplier = count_multiplier(steps, field.count(0))
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
            f"💣 Количество мин: {field.count(0)}\n"
            f"🟢 Открыто клеток: {steps}\n"
            f"🟠 Коэффициент: x{multiplier}\n\n"
            f"💵 Ставка: {spaced_num(bet)} $miles\n"
            f"💰 Выигрыш: {spaced_num(win_amount)} $miles\n"
            f"{bonus_text}"
            f"✨ Получено: {exp_gained} EXP\n"
            f"⭐️ Уровень: {level} ({xp}/{next_level_xp})\n"
            f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
        )

        delete_mines_session(user_id)

        await query.edit_message_text(
            text=text,
            reply_markup=build_mines_keyboard(
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

    return round(result * exp_mult * MINES['exp_factor'] * MINES[f'exp_{state}'], 1)


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
