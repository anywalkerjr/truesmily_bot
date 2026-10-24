import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from constants import CASES, MESSAGES, EXP_CASE_COOLDOWN
from helpers import (
    get_balance, spaced_num, ensure_user_exists,
    debit_balance, credit_balance, update_experience,
    credit_gems, get_experience, get_gems,
    get_exp_case_cooldown_seconds, update_expcase_timestamp,
    format_cooldown_time
)


async def show_cases_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Главная функция отображения меню кейсов с пагинацией"""
    user = update.effective_user
    ensure_user_exists(user)

    cases_list = list(CASES.items())
    max_per_page = 6
    total_pages = (len(cases_list) - 1) // max_per_page + 1

    start_idx = page * max_per_page
    end_idx = start_idx + max_per_page
    current_cases = cases_list[start_idx:end_idx]

    text = "📦 *Магазин Кейсов*\n\nВыбери кейс для открытия:"
    keyboard = []

    # Кнопки кейсов текущей страницы
    for key, case in current_cases:
        keyboard.append([
            InlineKeyboardButton(
                f"{case['name']}",
                callback_data=f"case_info:{key}:{page}:{user.id}"
            )
        ])

    # Кнопки навигации (пагинация)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"cases_menu:{page - 1}:{user.id}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Далее ➡️", callback_data=f"cases_menu:{page + 1}:{user.id}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def cases_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /cases"""
    await show_cases_menu(update, context, page=0)


async def cases_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик перелистывания страниц магазина"""
    query = update.callback_query
    await query.answer()

    _, page_str, owner_id = query.data.split(":")

    if query.from_user.id != int(owner_id):
        await query.answer(MESSAGES.get("session_not_yours", "⚠️ Это не твоя сессия!"), show_alert=True)
        return

    await show_cases_menu(update, context, page=int(page_str))


async def case_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки конкретного кейса (окно информации)"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    case_id = parts[1]
    page = int(parts[2])
    owner_id = int(parts[3])

    if query.from_user.id != owner_id:
        await query.answer(MESSAGES.get("session_not_yours", "⚠️ Это не твоя сессия!"), show_alert=True)
        return

    case = CASES.get(case_id)
    if not case:
        await query.answer("❌ Кейс не найден!", show_alert=True)
        return

    # Формируем список лута
    loot_lines = []
    for drop in case['drops']:
        loot_lines.append(f"\t{drop['text']} — {drop['chance']}%")
    loot_text = "\n".join(loot_lines)

    # Специальная логика для бесплатного кейса опыта
    if case_id == "free_exp":
        remaining_secs = get_exp_case_cooldown_seconds(owner_id)

        if remaining_secs > 0:
            time_str = format_cooldown_time(remaining_secs)
            status_text = (
                f"⏳ *Открыть можно через:* `{time_str}`\n"
                f"⏰ *Кулдаун:* раз в {EXP_CASE_COOLDOWN} мин."
            )
            keyboard = [
                [InlineKeyboardButton(f"⏳ Доступен через {time_str}", callback_data=f"case_cooldown:{owner_id}")],
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data=f"case_info:{case_id}:{page}:{owner_id}"),
                    InlineKeyboardButton("⬅️ Назад", callback_data=f"cases_menu:{page}:{owner_id}")
                ]
            ]
        else:
            status_text = (
                f"✅ *Статус:* Готов к открытию!\n"
                f"⏰ *Кулдаун:* раз в {EXP_CASE_COOLDOWN} мин."
            )
            keyboard = [
                [InlineKeyboardButton("🎁 Открыть бесплатно", callback_data=f"buy_case:{case_id}:{page}:{owner_id}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=f"cases_menu:{page}:{owner_id}")]
            ]

        text = (
            f"*{case['name']}*\n\n"
            f"📝 *Описание:* {case['desc']}\n"
            f"💵 *Цена:* Бесплатно (Free)\n"
            f"{status_text}\n\n"
            f"🎁 *Возможный лут:*\n{loot_text}"
        )

    else:
        # Платные кейсы
        text = (
            f"*{case['name']}*\n\n"
            f"📝 *Описание:* {case['desc']}\n"
            f"💵 *Цена:* {spaced_num(case['price'])} $miles\n\n"
            f"🎁 *Лут:*\n{loot_text}"
        )

        keyboard = [
            [InlineKeyboardButton("💰 Купить", callback_data=f"buy_case:{case_id}:{page}:{owner_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"cases_menu:{page}:{owner_id}")]
        ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def case_cooldown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатия на кнопку кулдауна бесплатного кейса"""
    query = update.callback_query
    parts = query.data.split(":")
    owner_id = int(parts[1]) if len(parts) > 1 else query.from_user.id

    if query.from_user.id != owner_id:
        await query.answer(MESSAGES.get("session_not_yours", "⚠️ Это не твоя сессия!"), show_alert=True)
        return

    remaining_secs = get_exp_case_cooldown_seconds(owner_id)
    if remaining_secs > 0:
        time_str = format_cooldown_time(remaining_secs)
        await query.answer(f"⏳ Этот кейс можно будет открыть через {time_str}!", show_alert=True)
    else:
        await query.answer("✅ Кейс уже доступен! Нажми 'Обновить' или открой кейс.", show_alert=True)


async def handle_case_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка покупки и открытия кейса"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    case_id = parts[1]
    page = int(parts[2])
    owner_id = int(parts[3])

    if query.from_user.id != owner_id:
        await query.answer(MESSAGES.get("session_not_yours", "⚠️ Это не твоя сессия!"), show_alert=True)
        return

    case = CASES.get(case_id)
    if not case:
        await query.answer("❌ Кейс не найден!", show_alert=True)
        return

    username = query.from_user.username

    # Открытие бесплатного кейса опыта
    if case_id == "free_exp":
        remaining_secs = get_exp_case_cooldown_seconds(owner_id)
        if remaining_secs > 0:
            time_str = format_cooldown_time(remaining_secs)
            await query.answer(f"⏳ Кейс ещё не готов! Доступен через {time_str}.", show_alert=True)
            # Обновляем окно с актуальным таймером
            await case_info_handler(update, context)
            return

        # Обновляем таймштамп открытия
        update_expcase_timestamp(owner_id)

    else:
        # Списываем деньги за платный кейс
        if not debit_balance(owner_id, case["price"]):
            balance = get_balance(owner_id, username)
            await query.edit_message_text(
                f"❌ *Недостаточно средств!*\n\n"
                f"Стоимость: {spaced_num(case['price'])} $miles\n"
                f"Твой баланс: {spaced_num(balance)} $miles",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data=f"case_info:{case_id}:{page}:{owner_id}")
                ]]),
                parse_mode="Markdown"
            )
            return

    # Определяем дроп
    roll = random.uniform(0, 100)
    cumulative = 0
    won_drop = None

    for drop in case["drops"]:
        cumulative += drop["chance"]
        if roll <= cumulative:
            won_drop = drop
            break

    if not won_drop:
        won_drop = case["drops"][-1]

    # Выдача награды
    result_msg = f"📦 Ты открыл *{case['name']}*!\n\n"
    result_msg += f"🎁 Выпало: *{won_drop['text']}*\n"

    if case["type"] in ("exp", "free_exp"):
        update_experience(owner_id, won_drop["amount"])
        result_msg += f"✨ Получено: +{won_drop['amount']} EXP\n"

    elif case["type"] == "gems":
        credit_gems(owner_id, won_drop["amount"])
        result_msg += f"💎 Получено: +{won_drop['amount']} GEMS\n"

    elif case["type"] == "balance":
        if won_drop["amount"] > 0:
            credit_balance(owner_id, won_drop["amount"])
            result_msg += f"💰 Получено: +{spaced_num(won_drop['amount'])} $miles\n"
        else:
            result_msg += "💸 Ничего не выиграно.\n"

    # Добавляем информацию об аккаунте
    level_info = get_experience(owner_id, username)
    result_msg += f"\n⭐️ Уровень: {level_info[0]} ({level_info[1]})\n"
    result_msg += f"💰 Баланс: {spaced_num(get_balance(owner_id, username))} $miles\n"
    result_msg += f"💎 Гемы: {spaced_num(get_gems(owner_id, username))} GEMS\n"

    if case_id == "free_exp":
        result_msg += f"\n⏰ Следующий бесплатный кейс доступен через {EXP_CASE_COOLDOWN} минут!"
        keyboard = [
            [InlineKeyboardButton("🔙 К списку кейсов", callback_data=f"cases_menu:{page}:{owner_id}")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton(f"🔄 Открыть еще ({spaced_num(case['price'])})",
                                  callback_data=f"buy_case:{case_id}:{page}:{owner_id}")],
            [InlineKeyboardButton("🔙 К списку кейсов", callback_data=f"cases_menu:{page}:{owner_id}")]
        ]

    await query.edit_message_text(
        result_msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


__all__ = [
    'cases_command',
    'cases_menu_callback',
    'case_info_handler',
    'handle_case_purchase',
    'case_cooldown_callback'
]
