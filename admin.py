"""
Модуль админ-панели
Доступ только для @desenk02
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from helpers import *
from constants import LEVELS

# ID администратора
ADMIN_ID = [
    877936040,
    1716028797
]


# Декоратор проверки прав
def admin_only(func):
    """Декоратор - только для админа"""

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user or update.callback_query.from_user
        user_id = user.id

        if not (user_id in ADMIN_ID):
            if update.message:
                await update.message.reply_text("🚫 У тебя нет прав администратора!")
            else:
                await update.callback_query.answer("🚫 У тебя нет прав администратора!", show_alert=True)
            return

        return await func(update, context)

    return wrapper


# ======================= ГЛАВНАЯ ПАНЕЛЬ =======================

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главная админ-панель"""
    keyboard = [
        [
            InlineKeyboardButton("💰 Деньги", callback_data="admin_help_money"),
            InlineKeyboardButton("⭐ Уровень", callback_data="admin_help_level")
        ],
        [
            InlineKeyboardButton("✨ Таланты", callback_data="admin_help_talents"),
            InlineKeyboardButton("🏢 Бизнесы", callback_data="admin_help_business")
        ],
        [
            InlineKeyboardButton("📊 Все команды", callback_data="admin_help_all")
        ]
    ]

    text = (
        "🔧 *АДМИН-ПАНЕЛЬ*\n\n"
        "Нажми на кнопку для справки по команде\n"
        "или используй команды напрямую:\n\n"
        "💰 `/admin_money` - деньги\n"
        "⭐ `/admin_level` - уровень\n"
        "✨ `/admin_talent` - таланты\n"
        "🏢 `/admin_biz` - бизнесы"
    )

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
        await update.callback_query.answer()


# ======================= ОБРАБОТЧИКИ КНОПОК =======================

@admin_only
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()

    action = query.data

    keyboard = [[InlineKeyboardButton("← Назад", callback_data="admin_main")]]

    if action == "admin_help_money":
        text = (
            "💰 *Управление деньгами*\n\n"
            "*Команда:* `/admin_money`\n\n"
            "*Примеры:*\n"
            "• `/admin_money @username 1000000` - выдать $1кк\n"
            "• `/admin_money 5kk` (ответом) - выдать $5кк\n"
            "• `/admin_money @username -1000` - забрать $1000\n"
            "• `/admin_money all` (ответом) - выдать весь баланс\n\n"
            "*Форматы сумм:*\n"
            "• `1000` - тысяча\n"
            "• `1k` или `1к` - 1 000\n"
            "• `5kk` или `5кк` - 5 000 000\n"
            "• `1kkk` или `1ккк` - 1 000 000 000\n"
            "• `all` - весь баланс игрока"
        )

    elif action == "admin_help_level":
        text = (
            "⭐ *Управление уровнем*\n\n"
            "*Команда:* `/admin_level`\n\n"
            "*Примеры:*\n"
            "• `/admin_level @username 50` - установить 50 lvl\n"
            "• `/admin_level 100` (ответом) - установить 100 lvl\n\n"
            "*Примечание:*\n"
            "Уровень устанавливается через опыт.\n"
            f"Максимальный уровень: {max(lvl for lvl, _ in LEVELS)}"
        )

    elif action == "admin_help_talents":
        text = (
            "✨ *Управление талантами*\n\n"
            "*Команда:* `/admin_talent`\n\n"
            "*Примеры:*\n"
            "• `/admin_talent @username luck 10` - удача 10\n"
            "• `/admin_talent agility 5` (ответом) - ловкость 5\n\n"
            "*Доступные таланты:*\n"
            "• `untouchable` - Неприкасаемость ⛓️\n"
            "• `agility` - Ловкость ✳️\n"
            "• `mastery` - Мастерство 👨‍🎓\n"
            "• `luck` - Удача 🍀"
        )

    elif action == "admin_help_business":
        from constants import BUSINESS_LIST

        biz_list = "\n".join([
            f"`{i + 1}` - {biz['name']}"
            for i, biz in enumerate(BUSINESS_LIST[:10])  # Первые 10
        ])

        text = (
                "🏢 *Управление бизнесами*\n\n"
                "*Команда:* `/admin_biz`\n\n"
                "*Примеры:*\n"
                "• `/admin_biz @username 1` - выдать 1-й бизнес\n"
                "• `/admin_biz 5` (ответом) - выдать 5-й бизнес\n\n"
                "*Первые 10 бизнесов:*\n" + biz_list + "\n\n"
                                                         "Используй `/admin_biz` без аргументов для полного списка"
        )

    elif action == "admin_help_all":
        text = (
            "📊 *Все админ-команды*\n\n"
            "💰 `/admin_money <кому> <сумма>`\n"
            "Выдать или забрать деньги\n\n"
            "⭐ `/admin_level <кому> <уровень>`\n"
            "Установить уровень\n\n"
            "✨ `/admin_talent <кому> <талант> <lvl>`\n"
            "Установить уровень таланта\n\n"
            "🏢 `/admin_biz <кому> <id>`\n"
            "Выдать бизнес\n\n"
            "*Указать игрока:*\n"
            "• `@username` - по имени\n"
            "• Ответ на сообщение - по контексту"
        )

    elif action == "admin_main":
        await admin_panel(update, context)
        return

    else:
        text = "❓ Неизвестная команда"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ======================= КОМАНДЫ =======================

@admin_only
async def admin_give_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_money @username 1000000
    /admin_money (ответом) 1kk
    """
    if not context.args:
        await update.message.reply_text(
            "💰 *Выдать деньги*\n\n"
            "*Использование:*\n"
            "`/admin_money @username 1000000`\n"
            "`/admin_money 5kk` (ответом)\n"
            "`/admin_money @username -1000` (забрать)",
            parse_mode="Markdown"
        )
        return

    # Определяем цель
    reply = update.message.reply_to_message

    if reply and not reply.from_user.is_bot:
        target_id = reply.from_user.id
        target_name = reply.from_user.full_name
        amount = parse_bet_amount(context.args[0], target_id, None)
    elif context.args[0].startswith("@"):
        username = context.args[0][1:]
        target_id = find_user_by_username(username)

        if not target_id:
            await update.message.reply_text("❌ Пользователь не найден")
            return

        target_name = username
        amount = parse_bet_amount(context.args[1], target_id, None) if len(context.args) > 1 else None
    else:
        await update.message.reply_text("❌ Укажи пользователя (@username или ответом)")
        return

    if amount is None:
        await update.message.reply_text("❌ Некорректная сумма")
        return

    # Выдаём/забираем деньги
    current_balance = get_balance(target_id, None)
    new_balance = current_balance + amount

    set_balance(target_id, new_balance)

    action = "выдано" if amount > 0 else "забрано"

    await update.message.reply_text(
        f"✅ *Готово!*\n\n"
        f"👤 Игрок: {target_name}\n"
        f"💵 {action.capitalize()}: {spaced_num(abs(amount))} $miles\n"
        f"💰 Новый баланс: {spaced_num(new_balance)} $miles",
        parse_mode="Markdown"
    )


@admin_only
async def admin_set_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_level @username 50
    /admin_level (ответом) 100
    """
    if not context.args:
        await update.message.reply_text(
            "⭐ *Установить уровень*\n\n"
            "*Использование:*\n"
            "`/admin_level @username 50`\n"
            "`/admin_level 100` (ответом)",
            parse_mode="Markdown"
        )
        return

    # Определяем цель
    reply = update.message.reply_to_message

    if reply and not reply.from_user.is_bot:
        target_id = reply.from_user.id
        target_name = reply.from_user.full_name
        try:
            level = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Некорректный уровень")
            return
    elif context.args[0].startswith("@"):
        username = context.args[0][1:]
        target_id = find_user_by_username(username)

        if not target_id:
            await update.message.reply_text("❌ Пользователь не найден")
            return

        target_name = username
        try:
            level = int(context.args[1]) if len(context.args) > 1 else 0
        except ValueError:
            await update.message.reply_text("❌ Некорректный уровень")
            return
    else:
        await update.message.reply_text("❌ Укажи пользователя")
        return

    # Находим опыт для этого уровня
    target_exp = next((exp for lvl, exp in LEVELS if lvl == level), None)

    if target_exp is None:
        await update.message.reply_text(f"❌ Уровень {level} не существует (макс {max(lvl for lvl, _ in LEVELS)})")
        return

    # Устанавливаем опыт
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "UPDATE users SET experience = %s, level = %s WHERE telegram_id = %s",
        (target_exp, level, target_id)
    )
    conn.commit()

    await update.message.reply_text(
        f"✅ *Готово!*\n\n"
        f"👤 Игрок: {target_name}\n"
        f"⭐ Новый уровень: {level}\n"
        f"✨ Опыт: {target_exp} EXP",
        parse_mode="Markdown"
    )


@admin_only
async def admin_set_talent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_talent @username untouchable 10
    /admin_talent (ответом) luck 5
    """
    talents_map = {
        'untouchable': 'Неприкасаемость',
        'agility': 'Ловкость',
        'mastery': 'Мастерство',
        'luck': 'Удача'
    }

    if not context.args:
        await update.message.reply_text(
            "✨ *Установить талант*\n\n"
            "*Использование:*\n"
            "`/admin_talent @username untouchable 10`\n"
            "`/admin_talent luck 5` (ответом)\n\n"
            "*Таланты:*\n"
            "• `untouchable` - Неприкасаемость\n"
            "• `agility` - Ловкость\n"
            "• `mastery` - Мастерство\n"
            "• `luck` - Удача",
            parse_mode="Markdown"
        )
        return

    # Определяем цель
    reply = update.message.reply_to_message

    if reply and not reply.from_user.is_bot:
        target_id = reply.from_user.id
        target_name = reply.from_user.full_name

        if len(context.args) < 2:
            await update.message.reply_text("❌ Укажи талант и уровень")
            return

        talent = context.args[0].lower()
        try:
            level = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Некорректный уровень")
            return
    elif context.args[0].startswith("@"):
        username = context.args[0][1:]
        target_id = find_user_by_username(username)

        if not target_id:
            await update.message.reply_text("❌ Пользователь не найден")
            return

        target_name = username

        if len(context.args) < 3:
            await update.message.reply_text("❌ Укажи талант и уровень")
            return

        talent = context.args[1].lower()
        try:
            level = int(context.args[2])
        except ValueError:
            await update.message.reply_text("❌ Некорректный уровень")
            return
    else:
        await update.message.reply_text("❌ Укажи пользователя")
        return

    if talent not in talents_map:
        await update.message.reply_text(
            f"❌ Неизвестный талант: {talent}\n"
            f"Доступны: untouchable, agility, mastery, luck"
        )
        return

    # Устанавливаем талант
    ensure_talent_exists(target_id)

    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        f"UPDATE talents SET {talent} = %s WHERE user_id = %s",
        (level, target_id)
    )
    conn.commit()

    await update.message.reply_text(
        f"✅ *Готово!*\n\n"
        f"👤 Игрок: {target_name}\n"
        f"✨ Талант: {talents_map[talent]}\n"
        f"📊 Уровень: {level}",
        parse_mode="Markdown"
    )


@admin_only
async def admin_give_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin_biz @username 1
    /admin_biz (ответом) 5
    """
    from constants import BUSINESS_LIST
    from helpers import add_user_business

    if not context.args:
        # Показываем список бизнесов
        biz_list = "\n".join([
            f"`{i + 1}` - {biz['name']}"
            for i, biz in enumerate(BUSINESS_LIST)
        ])

        await update.message.reply_text(
            "🏢 *Выдать бизнес*\n\n"
            "*Использование:*\n"
            "`/admin_biz @username 1`\n"
            "`/admin_biz 5` (ответом)\n\n"
            "*Список бизнесов:*\n" + biz_list,
            parse_mode="Markdown"
        )
        return

    # Определяем цель
    reply = update.message.reply_to_message

    if reply and not reply.from_user.is_bot:
        target_id = reply.from_user.id
        target_name = reply.from_user.full_name
        try:
            biz_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Некорректный ID бизнеса")
            return
    elif context.args[0].startswith("@"):
        username = context.args[0][1:]
        target_id = find_user_by_username(username)

        if not target_id:
            await update.message.reply_text("❌ Пользователь не найден")
            return

        target_name = username
        try:
            biz_id = int(context.args[1]) if len(context.args) > 1 else 0
        except ValueError:
            await update.message.reply_text("❌ Некорректный ID бизнеса")
            return
    else:
        await update.message.reply_text("❌ Укажи пользователя")
        return

    if biz_id < 1 or biz_id > len(BUSINESS_LIST):
        await update.message.reply_text(
            f"❌ Бизнес #{biz_id} не существует\n"
            f"Доступны: 1-{len(BUSINESS_LIST)}"
        )
        return

    # Выдаём бизнес
    success = add_user_business(target_id, biz_id)

    if not success:
        await update.message.reply_text("❌ У игрока уже есть этот бизнес")
        return

    biz = BUSINESS_LIST[biz_id - 1]

    await update.message.reply_text(
        f"✅ *Готово!*\n\n"
        f"👤 Игрок: {target_name}\n"
        f"🏢 Выдан бизнес: {biz['name']}\n"
        f"💵 Доход: {spaced_num(biz['income'])} $miles/час",
        parse_mode="Markdown"
    )


# ======================= ВСПОМОГАТЕЛЬНЫЕ =======================

def find_user_by_username(username: str) -> int:
    """Поиск ID по username"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT telegram_id FROM users WHERE username = %s",
        (username,)
    )

    result = cursor.fetchone()
    return result['telegram_id'] if result else None


# ======================= ЭКСПОРТ =======================

__all__ = [
    'admin_panel',
    'admin_callback',
    'admin_give_money',
    'admin_set_level',
    'admin_set_talent',
    'admin_give_business'
]
