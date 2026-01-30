from typing import Dict
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import RetryAfter

from constants import (
    TALENT_BONUSES, TALENT_MAX_LEVELS,
    TALENT_COSTS, TALENT_LEVEL_REQUIREMENTS
)
from helpers import (
    get_cursor, get_balance, set_balance, spaced_num,
    get_experience, ensure_user_exists, ensure_talent_exists,
    get_user_talents
)

# ======================= КОНСТАНТЫ ТАЛАНТОВ =======================

# Названия талантов для отображения
TALENT_NAMES = {
    "untouchable": "НЕПРИКАСАЕМОСТЬ",
    "agility": "ЛОВКОСТЬ",
    "mastery": "МАСТЕРСТВО",
    "luck": "УДАЧА"
}

# Эмодзи для талантов
TALENT_EMOJI = {
    "untouchable": "⛓️",
    "agility": "✳️",
    "mastery": "👨‍🎓",
    "luck": "🍀"
}


# ======================= РАСЧЁТ ТРЕБОВАНИЙ =======================

def get_required_level(talent: str, current_talent_lvl: int) -> int:
    """
    Получение требуемого уровня игрока для прокачки таланта

    Args:
        talent: Название таланта (untouchable, agility, mastery, luck)
        current_talent_lvl: Текущий уровень таланта

    Returns:
        Требуемый уровень игрока
    """
    rule = TALENT_LEVEL_REQUIREMENTS[talent]
    return rule["base"] + round(current_talent_lvl * rule["step"] + 0.1)


def get_upgrade_cost(talent: str, current_talent_lvl: int) -> int:
    """
    Расчёт стоимости прокачки таланта на следующий уровень

    Args:
        talent: Название таланта
        current_talent_lvl: Текущий уровень таланта

    Returns:
        Стоимость в игровой валюте
    """
    cost_data = TALENT_COSTS[talent]
    return int(cost_data["base"] * (cost_data["multiplier"] ** current_talent_lvl))


def get_talent_effect_description(talent: str, level: int) -> str:
    """
    Получение описания эффекта таланта

    Args:
        talent: Название таланта
        level: Уровень таланта

    Returns:
        Текстовое описание эффекта
    """
    bonus_value = abs(level * TALENT_BONUSES[talent])

    descriptions = {
        "untouchable": f"-{round(bonus_value, 1)}% защита от кражи",
        "agility": f"+{round(bonus_value, 2)}% к краже",
        "mastery": f"+{round(bonus_value, 1)} к множителю EXP",
        "luck": f"+{round(bonus_value, 1)}% шанс на кэшбэк 20%"
    }

    return descriptions.get(talent, "")


# ======================= ДАННЫЕ ТАЛАНТА =======================

def get_talent_data(user_lvl: int, talent_name: str, current_talent_lvl: int, user_balance: int) -> Dict:
    """
    Получение полной информации о таланте

    Args:
        user_lvl: Уровень игрока
        talent_name: Название таланта
        current_talent_lvl: Текущий уровень таланта
        user_balance: Баланс игрока

    Returns:
        Словарь с данными таланта
    """
    max_lvl = TALENT_MAX_LEVELS[talent_name]
    next_lvl = current_talent_lvl + 1

    # Проверка достижения максимума
    if current_talent_lvl >= max_lvl:
        return {
            "title": TALENT_NAMES[talent_name],
            "emoji": TALENT_EMOJI[talent_name],
            "lvl": current_talent_lvl,
            "max_lvl": max_lvl,
            "effect": get_talent_effect_description(talent_name, current_talent_lvl),
            "next_effect": None,
            "next_price": None,
            "next_req_lvl": None,
            "available": False,
            "is_maxed": True
        }

    # Расчёт требований
    price = get_upgrade_cost(talent_name, current_talent_lvl)
    req_lvl = get_required_level(talent_name, current_talent_lvl)
    available = user_lvl >= req_lvl and user_balance >= price

    return {
        "title": TALENT_NAMES[talent_name],
        "emoji": TALENT_EMOJI[talent_name],
        "lvl": current_talent_lvl,
        "max_lvl": max_lvl,
        "effect": get_talent_effect_description(talent_name, current_talent_lvl),
        "next_effect": get_talent_effect_description(talent_name, next_lvl),
        "next_price": price,
        "next_req_lvl": req_lvl,
        "available": available,
        "is_maxed": False
    }


def get_max_upgrade_possible(user_lvl: int, talent_name: str, current_talent_lvl: int, user_balance: int) -> int:
    """
    Вычисляет, на сколько уровней можно прокачать талант прямо сейчас.
    """
    max_lvl_limit = TALENT_MAX_LEVELS[talent_name]
    upgrades_possible = 0
    temp_balance = user_balance
    temp_talent_lvl = current_talent_lvl

    # Цикл идет до тех пор, пока уровень таланта меньше максимального
    while temp_talent_lvl < max_lvl_limit:
        # Получаем требования для СЛЕДУЮЩЕГО уровня
        price = get_upgrade_cost(talent_name, temp_talent_lvl)
        req_lvl = get_required_level(talent_name, temp_talent_lvl)

        # Проверяем, хватает ли уровня игрока и денег
        if user_lvl >= req_lvl and temp_balance >= price:
            upgrades_possible += 1
            temp_balance -= price
            temp_talent_lvl += 1
        else:
            # Если на очередной уровень не хватает ресурсов, останавливаемся
            break

    return upgrades_possible
# ======================= КОМАНДЫ =======================

async def talents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /talents - показать меню талантов"""
    user = update.effective_user

    # Проверка вызова через callback
    if update.callback_query:
        query = update.callback_query
        owner_id = query.data.split(':')[1]

        if str(owner_id) != str(user.id):
            await query.answer(text="⚠️ Это не твоя сессия!", show_alert=True)
            return

        await query.answer()

    ensure_user_exists(user)
    ensure_talent_exists(user.id)

    user_lvl = get_experience(user.id, user.username)[0]
    talents_data = get_user_talents(user.id)

    # Формируем кнопки талантов
    keyboard = [
        [
            InlineKeyboardButton(
                f"{TALENT_EMOJI['untouchable']} Неприкасаемость ({talents_data['untouchable']} LVL)",
                callback_data=f"talent_untouchable:{user.id}"
            ),
            InlineKeyboardButton(
                f"{TALENT_EMOJI['agility']} Ловкость ({talents_data['agility']} LVL)",
                callback_data=f"talent_agility:{user.id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{TALENT_EMOJI['mastery']} Мастерство ({talents_data['mastery']} LVL)",
                callback_data=f"talent_mastery:{user.id}"
            ),
            InlineKeyboardButton(
                f"{TALENT_EMOJI['luck']} Удача ({talents_data['luck']} LVL)",
                callback_data=f"talent_luck:{user.id}"
            )
        ]
    ]

    text = (
        f"✨ *ТАЛАНТЫ*\n\n"
        f"⭐️ Твой уровень: {user_lvl}\n"
        f"💰 Баланс: {spaced_num(get_balance(user.id, user.username))} $miles\n\n"
        f"Выбери талант для прокачки:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def talent_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать детальную информацию о таланте"""
    query = update.callback_query
    user = query.from_user

    # Проверка владельца
    owner_id = query.data.split(':')[1]
    if str(owner_id) != str(user.id):
        await query.answer(text="⚠️ Это не твоя сессия!", show_alert=True)
        return

    await query.answer()

    ensure_user_exists(user)
    ensure_talent_exists(user.id)

    # Парсим название таланта
    talent_name = query.data.split(':')[0].split("_")[1]

    user_lvl = get_experience(user.id, user.username)[0]
    talents_data = get_user_talents(user.id)
    current_lvl = talents_data.get(talent_name, 0)
    user_balance = get_balance(user.id, user.username)

    # Получаем данные таланта
    data = get_talent_data(user_lvl, talent_name, current_lvl, user_balance)

    # Формируем текст
    if data['is_maxed']:
        text = (
            f"━ {data['emoji']} {data['title']} ━\n\n"
            f"⭐️ Уровень: {data['lvl']} / {data['max_lvl']} (МАКС)\n"
            f"✨ Эффект: {data['effect']}\n\n"
            f"🏆 Талант прокачан до максимума!"
        )

        keyboard = [[
            InlineKeyboardButton("⬅️ Назад", callback_data=f"talents:{user.id}")
        ]]
    else:
        availability = (
            "✅ Доступно"
            if data['available']
            else f"❌ Требуется {data['next_req_lvl']} LVL (у вас {user_lvl} LVL) и {spaced_num(data['next_price'])} $miles (у вас {spaced_num(user_balance)} $miles)"
        )


        text = (
            f"━ {data['emoji']} {data['title']} ━\n\n"
            f"⭐️ Текущий уровень: {data['lvl']} / {data['max_lvl']}\n"
            f"✨ Текущий эффект: {data['effect']}\n\n"
            f"🔼 Прокачка до {data['lvl'] + 1} LVL:\n"
            f"💵 Стоимость: {spaced_num(data['next_price'])} $miles\n"
            f"✨ Новый эффект: {data['next_effect']}\n"
            f"🔒 Доступность: {availability}"
        )
        max_upgrade = get_max_upgrade_possible(user_lvl, talent_name, current_lvl, user_balance)
        if max_upgrade > 1:
            keyboard = [
                [InlineKeyboardButton("⬆️ Улучшить", callback_data=f"upgrade_{talent_name}:{user.id}")],
                [InlineKeyboardButton(f"⬆️ Улучшить на {max_upgrade}", callback_data=f"upgrade_{talent_name}:{user.id}:{max_upgrade}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=f"talents:{user.id}")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("⬆️ Улучшить", callback_data=f"upgrade_{talent_name}:{user.id}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=f"talents:{user.id}")]
            ]


    try:
        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def upgrade_talent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прокачать талант на один или несколько уровней"""
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username

    # 1. Проверка владельца
    query_parts = query.data.split(':')
    owner_id = query_parts[1]
    if str(owner_id) != str(user_id):
        await query.answer(text="⚠️ Это не твоя сессия!", show_alert=True)
        return

    ensure_user_exists(query.from_user)
    ensure_talent_exists(user_id)

    # 2. Парсим данные
    talent_name = query_parts[0].split("_")[1]
    # Если в callback_data передано 'max', качаем сколько влезет, иначе на 1
    upgrade_mode = query_parts[2] if len(query_parts) == 3 else "1"

    # 3. Получаем текущие данные
    talent_levels = get_user_talents(user_id)
    current_lvl = talent_levels[talent_name]
    user_lvl = get_experience(user_id, username)[0]
    balance = get_balance(user_id, username)
    max_lvl_limit = TALENT_MAX_LEVELS[talent_name]

    if current_lvl >= max_lvl_limit:
        await query.answer("⚠️ Максимальный уровень уже достигнут.", show_alert=True)
        return

    # 4. РАСЧЕТ ПРОКАЧКИ
    total_cost = 0
    levels_to_add = 0
    temp_lvl = current_lvl
    temp_balance = balance

    # Определяем лимит итераций (для режима 'max' ставим разницу до капа)
    limit = (max_lvl_limit - current_lvl) if upgrade_mode == "max" else int(upgrade_mode)

    for _ in range(limit):
        price = get_upgrade_cost(talent_name, temp_lvl)
        req_lvl = get_required_level(talent_name, temp_lvl)

        if user_lvl >= req_lvl and temp_balance >= price:
            temp_balance -= price
            total_cost += price
            temp_lvl += 1
            levels_to_add += 1
        else:
            break

    # 5. Если не удалось прокачать даже на 1 уровень
    if levels_to_add == 0:
        price_first = get_upgrade_cost(talent_name, current_lvl)
        req_lvl_first = get_required_level(talent_name, current_lvl)

        if user_lvl < req_lvl_first:
            msg = f"🔒 Требуется {req_lvl_first} LVL"
        else:
            msg = f"💸 Нужно {spaced_num(price_first)} $miles"
        await query.answer(msg, show_alert=True)
        return

    # 6. СОХРАНЕНИЕ В БД (Один раз за всю операцию)
    c = get_cursor()
    cursor, conn = c[0], c[1]

    new_balance = balance - total_cost
    set_balance(user_id, new_balance)  # Обновляем баланс

    # Обновляем уровень таланта в БД
    cursor.execute(
        f"UPDATE talents SET {talent_name} = {talent_name} + %s WHERE user_id = %s",
        (levels_to_add, user_id)
    )
    conn.commit()

    await query.answer(f"Прокачано на +{levels_to_add} ур.!")

    # 7. ФОРМИРОВАНИЕ ОТВЕТА
    new_lvl = current_lvl + levels_to_add
    text = (
        f"✅ *Талант улучшен!*\n\n"
        f"{TALENT_EMOJI[talent_name]} *{TALENT_NAMES[talent_name]}* → {new_lvl} LVL\n"
        f"⏫ Повышено уровней: {levels_to_add}\n"
        f"✨ Эффект: {get_talent_effect_description(talent_name, new_lvl)}\n\n"
        f"💰 Списано: {spaced_num(total_cost)} $miles\n"
        f"💳 Баланс: {spaced_num(new_balance)} $miles"
    )

    keyboard = [[
        InlineKeyboardButton("⬅️ Назад", callback_data=f"talent_{talent_name}:{user_id}")
    ]]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ======================= ЭКСПОРТ =======================

__all__ = [
    'talents',
    'talent_info',
    'upgrade_talent',
    'get_talent_data',
    'get_required_level',
    'get_upgrade_cost'
]
