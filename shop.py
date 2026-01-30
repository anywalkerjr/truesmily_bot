import json
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from constants import BUSINESS_LIST
from helpers import (
    get_cursor, get_balance, set_balance, spaced_num,
    get_experience, ensure_user_exists, ensure_talent_exists,
    get_user_talents, get_user_business_profile, add_user_business, ensure_business_profile, calculate_total_income
)


# ======================= КОМАНДЫ =======================

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /shop - открыть магазин бизнесов"""
    context.user_data['shop_index'] = 0
    await send_shop_item(update, context, is_query=False)


async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок в магазине"""
    query = update.callback_query
    user = query.from_user

    # Парсинг данных
    data = query.data.split(':')
    owner_id = data[1]

    # Проверка владельца
    if str(owner_id) != str(user.id):
        await query.answer('⚠️ Это не твоя сессия!', show_alert=True)
        return

    index = context.user_data.get('shop_index', 0)

    # Навигация
    if data[0] == "shop_next":
        index = (index + 1) % len(BUSINESS_LIST)
        context.user_data['shop_index'] = index
        await send_shop_item(update, context, is_query=True)

    elif data[0] == "shop_prev":
        index = (index - 1) % len(BUSINESS_LIST)
        context.user_data['shop_index'] = index
        await send_shop_item(update, context, is_query=True)

    # Покупка
    elif data[0].startswith("shop_buy"):
        business_id = int(data[0].split('_')[-1])
        message = await handle_shop_purchase(user.id, user.username, business_id)
        context.user_data['shop_index'] = index+1
        keyboard = [[
            InlineKeyboardButton("◀️ Назад", callback_data=f"shop_prev:{user.id}"),
        ]]

        # Если покупка успешна - показываем новое сообщение
        if '✅' in message:
            await query.answer()
            await query.edit_message_text(message, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.answer(text=message, show_alert=True)


async def send_shop_item(update_or_query, context: ContextTypes.DEFAULT_TYPE, is_query=False):
    """Отправка карточки бизнеса"""
    index = context.user_data.get('shop_index', 0)
    biz = BUSINESS_LIST[index]

    user_id = update_or_query.effective_user.id
    username = update_or_query.effective_user.username

    ensure_user_exists(update_or_query.effective_user)
    ensure_talent_exists(user_id)
    ensure_business_profile(user_id)

    # Получаем данные пользователя
    user_lvl, user_experience, next_level_xp = get_experience(user_id, username)
    mastery_lvl = get_user_talents(user_id).get("mastery", 0)
    profile = get_user_business_profile(user_id)
    balance = get_balance(user_id, username)

    # Проверка доступности
    already_owned = biz["id"] in profile["businesses_ids"]
    requirements_met = user_lvl >= biz["lvl"] and mastery_lvl >= biz["mastery"]
    can_afford = balance >= biz["price"]
    available = requirements_met and not already_owned and can_afford

    # Формируем текст
    emoji = biz.get("emoji", "🏬")

    if already_owned:
        text = (
            f"{emoji} *{biz['name'].upper()}*\n\n"
            f"💸 Стоимость: {spaced_num(biz['price'])} $miles\n"
            f"🤑 Доход: {spaced_num(biz['income'])} $miles/час\n"
        )
        if biz['bonus']:
            text += f"🎁 Бонус: {biz['bonus']}\n"
        text += f"\n✅ *У вас в собственности*"
    else:
        text = (
            f"{emoji} *{biz['name'].upper()}*\n\n"
            f"💸 Стоимость: {spaced_num(biz['price'])} $miles\n"
            f"🤑 Доход: {spaced_num(biz['income'])} $miles/час\n"
        )
        if biz['bonus']:
            text += f"🎁 Бонус: {biz['bonus']}\n"

        text += f"\n🔒 *Требования:*\n"

        # Проверка уровня
        if user_lvl >= biz['lvl']:
            text += f"✅ Уровень: {biz['lvl']}\n"
        else:
            text += f"❌ Уровень: {biz['lvl']} (у вас {user_lvl})\n"

        # Проверка мастерства
        if mastery_lvl >= biz['mastery']:
            text += f"✅ Мастерство: {biz['mastery']}\n"
        else:
            text += f"❌ Мастерство: {biz['mastery']} (у вас {mastery_lvl})\n"

        # Проверка баланса
        if can_afford:
            text += f"✅ Баланс: {spaced_num(biz['price'])} $miles\n"
        else:
            text += f"❌ Баланс: {spaced_num(biz['price'])} $miles (у вас {spaced_num(balance)} $miles)\n"

    # Кнопки навигации
    keyboard = [[
        InlineKeyboardButton("◀️", callback_data=f"shop_prev:{user_id}"),
        InlineKeyboardButton(f"{index + 1}/{len(BUSINESS_LIST)}", callback_data="noop"),
        InlineKeyboardButton("▶️", callback_data=f"shop_next:{user_id}")
    ]]

    # Кнопка покупки
    if available:
        keyboard.insert(0, [InlineKeyboardButton("🛒 Купить", callback_data=f"shop_buy_{biz['id']}:{user_id}")])

    # Отправка
    if is_query:
        await update_or_query.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update_or_query.message.reply_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def handle_shop_purchase(user_id: int, username: str, business_id: int) -> str:
    """
    Обработка покупки бизнеса
    Возвращает: Сообщение о результате
    """
    profile = get_user_business_profile(user_id)

    # Проверка наличия
    if business_id in profile["businesses_ids"]:
        return "⚠️ У тебя уже есть этот бизнес."

    # Поиск бизнеса
    business = next((b for b in BUSINESS_LIST if b["id"] == business_id), None)
    if not business:
        return "❌ Бизнес не найден."

    # Проверка требований
    user_lvl, user_xp, next_level_xp = get_experience(user_id, username)
    mastery_lvl = get_user_talents(user_id).get("mastery", 0)
    balance = get_balance(user_id, username)

    if user_lvl < business['lvl']:
        return f"❌ Недостаточно уровня. Требуется: {business['lvl']}"

    if mastery_lvl < business['mastery']:
        return f"❌ Недостаточно мастерства. Требуется: {business['mastery']}"

    if balance < business['price']:
        return f"💸 Недостаточно средств. Требуется: {spaced_num(business['price'])} $miles"

    # Покупка
    success = add_user_business(user_id, business_id)

    if not success:
        return "⚠️ Ошибка при покупке."

    set_balance(user_id, balance - business['price'])

    emoji = business.get("emoji", "🏬")
    return (
        f"✅ *Поздравляем с покупкой!*\n\n"
        f"{emoji} *{business['name']}*\n"
        f"🤑 Доход: +{spaced_num(business['income'])} $miles/час\n"
        f"💰 Новый баланс: {spaced_num(get_balance(user_id, username))} $miles"
    )


async def my_biz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /my_biz - показать мои бизнесы"""
    user = update.effective_user
    profile = get_user_business_profile(user.id)

    if not profile['businesses_ids']:
        await update.message.reply_text(
            '⚠️ У тебя нет ни одного бизнеса\n'
            '▶️ Купи их в /shop',
            parse_mode="Markdown"
        )
        return

    # Формируем заголовок
    count = len(profile['businesses_ids'])
    if count == 1:
        message = f'<i>📍 У тебя есть {count} бизнес:</i>\n\n'
    elif 1 < count < 5:
        message = f'<i>📍 У тебя есть {count} бизнеса:</i>\n\n'
    else:
        message = f'<i>📍 У тебя есть {count} бизнесов:</i>\n\n'

    # Список бизнесов
    total_income = 0
    for biz_id in profile['businesses_ids']:
        biz = next((b for b in BUSINESS_LIST if b['id'] == biz_id), None)
        if not biz:
            continue

        emoji = biz.get("emoji", "🏬")
        message += f"<blockquote>{emoji} <b>{biz['name']}</b></blockquote>\n"
        message += f"   💸 Доход: {spaced_num(biz['income'])} $miles/час\n"

        if biz['bonus']:
            message += f"   🎁 Бонус: {biz['bonus']}\n"

        message += "\n"
        total_income += biz['income']

    # Итоговый доход с множителями
    final_income = calculate_total_income(user.id)

    if final_income > total_income:
        message += (
            f"🤑 <b>Базовый доход:</b> {spaced_num(total_income)} $miles/час\n"
            f"✨ <b>С бонусами:</b> {spaced_num(final_income)} $miles/час"
        )
    else:
        message += f"🤑 <b>Итого доход:</b> {spaced_num(final_income)} $miles/час"

    await update.message.reply_text(message, parse_mode="HTML")


# ======================= ПАССИВНЫЙ ДОХОД =======================

async def check_all_incomes(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка и начисление пассивного дохода"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    now = datetime.now()

    cursor.execute("SELECT user_id, acquired_at, businesses_ids FROM user_businesses")
    rows = cursor.fetchall()

    for row in rows:
        user_id = row['user_id']
        acquired_at = row['acquired_at']
        businesses = json.loads(row['businesses_ids'])
        # Проверка времени
        if not acquired_at or (now - acquired_at < timedelta(hours=1)):
            continue

        if len(businesses) == 0:
            continue

        # Расчёт дохода с бонусами
        income = calculate_total_income(user_id)

        # Начисление
        current_balance = get_balance(user_id, None)
        set_balance(user_id, current_balance + income)

        # Обновление времени
        cursor.execute(
            "UPDATE user_businesses SET acquired_at = %s WHERE user_id = %s",
            (now, user_id)
        )
        conn.commit()


# ======================= ЭКСПОРТ =======================

__all__ = [
    'shop',
    'shop_callback',
    'my_biz',
    'check_all_incomes'
]
