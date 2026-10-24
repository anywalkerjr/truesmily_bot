from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes

from helpers import get_experience, update_experience

PAYLOAD_PREFIX = "buy_xp_"
BASE_XP = 300
BASE_STARS = 5

async def show_donate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает 6 кнопок для выбора суммы доната"""
    keyboard = []
    # Генерируем 9 кнопок (от 1 до 6 пакетов)
    for i in range(1, 9):
        xp = i * BASE_XP + int(BASE_XP*0.1*i)
        stars = i * BASE_STARS
        # Красивый текст кнопки: 200 000 EXP — 5 ⭐
        btn_text = f"{xp} EXP | {stars} ⭐"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"stars_pack_{i}_{update.effective_user.id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💎 **Покупка EXP**\nВыберите подходящий пакет:",
                                   reply_markup=reply_markup, parse_mode="Markdown")

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия на кнопку пакета"""
    query = update.callback_query
    await query.answer()

    pack_idx = int(query.data.split("_")[2])
    user_id = int(query.data.split("_")[3])
    xp_to_buy = pack_idx * BASE_XP + int(BASE_XP*0.1*pack_idx)
    stars_price = pack_idx * BASE_STARS
    if user_id != update.effective_user.id:
        await query.answer(show_alert=True, text="⚠️ Это не ваша сессия!")
        return

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title="Покупка EXP",
        description=f"Покупка {xp_to_buy} EXP",
        payload=f"{PAYLOAD_PREFIX}{xp_to_buy}",
        provider_token="", # Для Stars всегда пусто
        currency="XTR",
        prices=[LabeledPrice(f"{xp_to_buy} EXP", stars_price)],
        start_parameter="smily_bot_shop"
    )

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обязательное подтверждение перед списанием звезд"""
    query = update.pre_checkout_query
    if query.invoice_payload.startswith(PAYLOAD_PREFIX):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Ошибка: неизвестный товар.")


async def success_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вызывается только после того, как Telegram подтвердил списание Stars"""
    payment = update.message.successful_payment
    payload = payment.invoice_payload  # Например: "buy_xp_400000"

    # Вытаскиваем количество миль из payload
    xp_amount = int(payload.replace(PAYLOAD_PREFIX, ""))
    user_id = update.effective_user.id

    # Логика начисления
    update_experience(user_id, xp_amount)
    current_lvl, current_xp, next_level_xp = get_experience(user_id, update.effective_user.username)
    await update.message.reply_text(
        f"✅ **Оплата прошла успешно!**\n"
        f"Вы получили: {xp_amount} EXP.\n"
        f"Ваш текущий уровень: {current_lvl} ({current_xp}/{next_level_xp})\n).",
        parse_mode="Markdown"
    )
