import json
import random
import asyncio
import os
from math import floor
from datetime import datetime
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from PIL import Image
from constants import (
    SLOTS, LUCKY_WHEEL, MIN_BET, LEVELS,
    DEPOSITS, STEAL, HACK,
    LUCKY_WHEEL_COOLDOWN, STEAL_COOLDOWN, BUSINESS_LIST, REF_SYSTEM, EXP_CASE_COOLDOWN, EXP_CASE
)
from helpers import (
    get_balance, set_balance, spaced_num, cropped_num,
    get_experience, update_experience, user_exists,
    ensure_user_exists, ensure_talent_exists, get_user_talents,
    get_user_bonuses, parse_bet_amount, calculate_exp_multiplier,
    check_lucky_wheel_availability, check_steal_availability,
    get_cursor, update_user, check_deposit_ready, update_bank_balance, claim_bank_balance, get_all_users_with_deposit,
    safe_reply_text, check_promocode, check_promocode_requirements, activate_promocode,
    get_user_by_username, try_activate_promocode, check_exp_case_availability, calculate_total_income
)
from helpers import get_user_business_profile, get_user_business_bonuses

# Извлекаем константы
SLOTS_SYMBOLS = SLOTS["symbols"]
SLOTS_EMOJI = SLOTS["emoji_to_filename"]
LUCKYWHEEL_PRIZES = LUCKY_WHEEL["prizes"]
EXP_CASE_PRIZES = EXP_CASE["prizes"]

# Константы вкладов
DEPOSIT_OPTIONS = DEPOSITS
# Кэширование изображений
SPRITES_CACHE = {
    symbol: Image.open(f'sprites/{SLOTS_EMOJI[symbol]}').convert("RGBA")
    for symbol in SLOTS_EMOJI
}
STATE_CACHE = {
    s: Image.open(f'sprites/{s}.jpg')
    for s in ["jackpot", "win", "lose"]
}
IMAGE_CACHE = {}
for imgs in os.listdir("images"):
    with open(os.path.join("images", imgs), 'rb') as f:
        name = imgs.replace(".jpg", "").upper() + "_IMG"
        IMAGE_CACHE[name] = f.read()


# ======================= START & HELP =======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - приветствие и реферальная система"""
    user = update.effective_user
    ref_id = update.message.text.split()[1] if len(update.message.text.split()) > 1 else None

    played_before = ensure_user_exists(user)

    # Обработка реферальной ссылки
    if ref_id and user_exists(int(ref_id)):
        if str(ref_id) != str(user.id):
            if not played_before:
                # Новый пользователь по реферальной ссылке
                set_balance(user.id, REF_SYSTEM["ref_get"]["balance"])
                update_experience(user.id, REF_SYSTEM["ref_get"]["xp"])

                await safe_reply_text(update.message,
                                      '✅ Добро пожаловать!\\n'
                                      '🎁 Бонус по реферальной ссылке:\n'
                                      f'💰 +{REF_SYSTEM["ref_get"]["balance"]} $miles\n'
                                      f'⭐️ +{REF_SYSTEM["ref_get"]["xp"]} EXP'
                                      )

                # Награда рефереру
                ref_balance = get_balance(int(ref_id), None)
                set_balance(int(ref_id), ref_balance + REF_SYSTEM["user_get"]["balance"])
                update_experience(int(ref_id), REF_SYSTEM["user_get"]["xp"])

                await context.bot.send_message(
                    chat_id=ref_id,
                    text=(
                        '✅ По твоей ссылке зарегистрировался новый игрок!\n'
                        '🎁 Награда:\n'
                        f'💰 +{REF_SYSTEM["user_get"]["balance"]} $miles\n'
                        f'⭐️ +{REF_SYSTEM["user_get"]["xp"]} EXP'
                    )
                )
            else:
                await safe_reply_text(update.message,
                                      '⚠️ *Реферальная ссылка проигнорирована.*\n'
                                      'Бонусы работают только для новых аккаунтов.',
                                      parse_mode='Markdown'
                                      )
        else:
            await safe_reply_text(update.message,
                                  '⚠️ *Нельзя использовать свою реферальную ссылку!*',
                                  parse_mode='Markdown'
                                  )

    # Приветственное сообщение
    balance = get_balance(user.id, user.username)
    player_level = get_experience(user.id, user.username)
    current_level = player_level[0]
    current_xp = player_level[1]
    next_level_xp = player_level[2]

    await update.message.reply_photo(photo=IMAGE_CACHE["START_IMG"],
                                     caption="🎰 <b>Добро пожаловать в Smily!</b>\n\n"
                                             f"💰 Твой баланс: {spaced_num(balance)} $miles\n"
                                             f"⭐️ Твой уровень: {current_level} ({current_xp}/{next_level_xp})\n\n"
                                             f"🎮 Используй /help для справки",
                                     parse_mode="HTML"
                                     )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - справка по боту"""
    u = update.callback_query or update.message

    text = (
        "📖 *Справка по Smily*\n\n"
        "🎰 *Игры*\n"
        "• `/spin <ставка>` — слоты\n"
        "• `/bj <ставка>` — блэкджек\n"
        "• `/rt <тип> <ставка>` — рулетка\n"
        "• `/lucky_wheel` — колесо удачи (раз в 30 мин)\n"
        "• `/exp_case` — кейс опыта (раз в 45 мин)\n"
        "• `/mines` — минки\n"
        "• `/duel @username <ставка>` — дуэль\n\n"
        "📊 *Статистика*\n"
        "• `/stats` — твоя статистика\n"
        "• `/check` — статистика игрока (ответом)\n"
        "• `/top` — топ по балансу\n"
        "• `/top_lvl` — топ по уровню\n\n"
        "🛒 *Экономика*\n"
        "• `/shop` — магазин бизнесов\n"
        "• `/my_biz` — мои бизнесы\n"
        "• `/talents` — прокачка талантов\n"
        "• `/give <сумма>` — передать деньги (ответом)\n"
        "• `/promo <промокод>` — активировать промокод\n"
        "• `/stars` — купить опыт за звёзды Telegram\n\n"
        "🏦 *Вклады*\n"
        "• `/deposit` — сделать вклад\n"
        "• `/claim` — забрать вклад\n\n"
        "🎲 *Действия*\n"
        "• `/steal` — украсть у игрока (ответом)\n"
        "• `/hack` — взломать банк\n"
        "• `/ref` — реферальная ссылка\n\n"
        "✳️ *Дополнительное*\n"
        "• `/my_duels` — открыть список своих дуэлей\n"
        "• `/game` — посмотреть ставки в рулетку на текущую игру (только в группе)\n\n"
        
        "✨ Удачи и крупных выигрышей! ✨"
    )

    keyboard = [[
        InlineKeyboardButton("📘 Примеры →", callback_data="help_examples")
    ]]

    if update.message:
        await update.message.reply_photo(
            photo=IMAGE_CACHE["HELP_IMG"],
            caption=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.callback_query.edit_message_caption(
            caption=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await update.callback_query.answer()


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок в справке"""
    query = update.callback_query
    await query.answer()

    if query.data == "help_examples":
        text = (
            "📘 *Примеры команд*\n\n"
            "🎰 *Слоты*\n"
            "`/spin 1000` — ставка $1000\n"
            "`/spin 5k` — ставка $5000\n"
            "`/spin all` — все деньги\n\n"
            "🃏 *Блэкджек*\n"
            "`/bj 500` — ставка $500\n\n"
            "🎲 *Рулетка*\n"
            "`/rt к 1000` — $1000 на красное\n"
            "`/rt чет 500` — $500 на чётное\n"
            "`/rt 7 1k` — $1000 на число 7\n\n"
            "*Типы ставок:*\n"
            "• `к` — красное (x2)\n"
            "• `ч` — чёрное (x2)\n"
            "• `чет` — чётное (x2)\n"
            "• `нечет` — нечётное (x2)\n"
            "• `п` — дюжина 1-12 (x3)\n"
            "• `в` — дюжина 13-24 (x3)\n"
            "• `т` — дюжина 25-36 (x3)\n"
            "• `0-36` — число (x36)\n\n"
            "💣 *Минки*\n"
            "`/mines 3 500` — 3 мины, ставка $500\n"
            "`/mines 2 1k` — 2 мины, ставка $1000\n"
            "`/mines 10 all` — 10 мин, все деньги\n"
            "__Чем больше мин, тем больше шанс на нее попасться, но больше коэффициент при победе__\n\n"
            "⚔️ *Дуэли*\n"
            "`/duel @username 1000` — вызов на $1000\n"
            "`/duel 5k` (ответом) — вызов на $5000\n"
            "`/turn` — сделать ход\n\n"
            "💸 *Действия*\n"
            "`/give 1000` (ответом) — передать $1000\n"
            "`/steal` (ответом) — украсть деньги\n"
        )

        keyboard = [[
            InlineKeyboardButton("← Назад", callback_data="help_main")
        ]]

        await query.edit_message_caption(
            caption=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "help_main":
        await help_command(update, context)


# ======================= СТАТИСТИКА =======================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats - моя статистика"""
    user = update.effective_user
    ensure_user_exists(user)
    ensure_talent_exists(user.id)

    bal = get_balance(user.id, user.username)
    player_level = get_experience(user.id, user.username)
    current_level = player_level[0]
    current_xp = player_level[1]

    # Таланты
    talents = get_user_talents(user.id)
    text_talents = (
        f"⛓️ Неприкасаемость: {talents['untouchable']} LVL\n"
        f"✳️ Ловкость: {talents['agility']} LVL\n"
        f"👨‍🎓 Мастерство: {talents['mastery']} LVL\n"
        f"🍀 Удача: {talents['luck']} LVL"
    )

    # Бизнесы
    profile = get_user_business_profile(user.id)

    if not profile['businesses_ids']:
        biz_text = "⚠️ У вас нет бизнесов"
    else:
        count = len(profile['businesses_ids'])
        if count == 1:
            biz_text = f"<blockquote>📍 У вас {count} бизнес:</blockquote>\n"
        elif 1 < count < 5:
            biz_text = f"<blockquote>📍 У вас {count} бизнеса:</blockquote>\n"
        else:
            biz_text = f"<blockquote>📍 У вас {count} бизнесов:</blockquote>\n"

        passive_income = calculate_total_income(user.id)
        for biz in BUSINESS_LIST:
            if biz["id"] in profile['businesses_ids']:
                biz_text += f"\t{biz['emoji']} {biz['name']}\n"

        biz_text += f"\n🤑 Пассивный доход: {spaced_num(passive_income)} $miles/час"

    next_level_xp = player_level[2]

    await safe_reply_text(update.message,
                          f"<blockquote>👤 {user.first_name}</blockquote>\n\n"
                          f"<blockquote>📊 Статистика</blockquote>\n"
                          f"💰 Баланс: {spaced_num(bal)} $miles\n"
                          f"⭐️ Уровень: {current_level} ({current_xp}/{next_level_xp})\n\n"
                          f"<blockquote>Таланты:</blockquote>\n{text_talents}\n\n"
                          f"{biz_text}",
                          parse_mode="HTML"
                          )


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /check - проверка игрока (ответом на сообщение или упоминанием @username)"""
    reply = update.message.reply_to_message
    ensure_user_exists(update.effective_user)

    if (not reply or reply.from_user.is_bot) and not context.args:
        await safe_reply_text(update.message,
                              "❌ Используй /check ответом на сообщение игрока или упоминанием @username"
                              )
        return

    if reply:
        target = reply.from_user
        ensure_user_exists(target)
        ensure_talent_exists(target.id)
    else:
        target = get_user_by_username(context.args[0])
        if target.id == -1:
            await safe_reply_text(update.message,
                                  "❌ Этот пользователь еще не зарегистрирован в боте"
                                  )
            return

    # Основная информация
    bal = get_balance(target.id, target.username)
    player_level = get_experience(target.id, target.username)
    current_level = player_level[0]
    current_xp = player_level[1]

    # Таланты
    talents = get_user_talents(target.id)
    text_talents = (
        f"⛓️ Неприкасаемость: {talents['untouchable']} LVL\n"
        f"✳️ Ловкость: {talents['agility']} LVL\n"
        f"👨‍🎓 Мастерство: {talents['mastery']} LVL\n"
        f"🍀 Удача: {talents['luck']} LVL"
    )

    # Бизнесы
    profile = get_user_business_profile(target.id)

    if not profile['businesses_ids']:
        biz_text = "⚠️ У игрока нет бизнесов"
    else:
        count = len(profile['businesses_ids'])
        if count == 1:
            biz_text = f"<blockquote>📍 У игрока {count} бизнес:</blockquote>\n"
        elif 1 < count < 5:
            biz_text = f"<blockquote>📍 У игрока {count} бизнеса:</blockquote>\n"
        else:
            biz_text = f"<blockquote>📍 У игрока {count} бизнесов:</blockquote>\n"

        passive_income = calculate_total_income(target.id)
        for biz in BUSINESS_LIST:
            if biz["id"] in profile['businesses_ids']:
                biz_text += f"\t{biz['emoji']} {biz['name']}\n"

        biz_text += f"\n🤑 Пассивный доход: {spaced_num(passive_income)} $miles/час"

    next_level_xp = player_level[2]

    await safe_reply_text(update.message,
                          f"<blockquote>👤 {target.first_name}</blockquote>\n\n"
                          f"<blockquote>📊 Статистика</blockquote>\n"
                          f"💰 Баланс: {spaced_num(bal)} $miles\n"
                          f"⭐️ Уровень: {current_level} ({current_xp}/{next_level_xp})\n\n"
                          f"<blockquote>Таланты:</blockquote>\n{text_talents}\n\n"
                          f"{biz_text}",
                          parse_mode="HTML"
                          )


# ======================= ТОПЫ =======================

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /top - топ 10 игроков по балансу"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT username, balance, first_name, telegram_id "
        "FROM users ORDER BY balance DESC"
    )
    players = cursor.fetchall()

    leaderboard_lines = []
    for i, p in enumerate(players[:10], 1):
        # HTML автоматически экранирует опасные символы
        if p['username']:
            name = f"<a href='tg://user?id=0'>{p['username']}</a>"
        else:
            name = f"<a href='tg://user?id=0'>{p['first_name']}</a>"

        balance_short = await cropped_num(p['balance'])
        leaderboard_lines.append(f"{i}. {name} | <i>{balance_short} $miles</i>")

    leaderboard = "\n".join(leaderboard_lines)
    user_place = next((i + 1 for i, p in enumerate(players) if p.get('telegram_id') == update.effective_user.id), None)
    if update.effective_user.username:
        user_name = update.effective_user.username
    else:
        user_name = update.effective_user.first_name
    await update.message.reply_photo(
        photo=IMAGE_CACHE["BALANCE_TOP_IMG"],
        caption=f"🏆 <b>Топ 10 игроков по балансу:</b>\n\n{leaderboard}\n\n<blockquote>{user_place}. {user_name} | <i>{await cropped_num(get_balance(update.effective_user.id))} $miles</i></blockquote>",
        parse_mode="HTML"
    )


async def top_lvl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /top_lvl - топ 100 игроков по уровню"""
    c = get_cursor()
    cursor, conn = c[0], c[1]

    cursor.execute(
        "SELECT username, experience, level, first_name, telegram_id "
        "FROM users ORDER BY experience DESC LIMIT 100"
    )
    players = cursor.fetchall()

    leaderboard_lines = []
    for i, p in enumerate(players, 1):
        if p['username']:
            name = f"@{p['username']}"
        else:
            name = p['first_name']

        leaderboard_lines.append(
            f"{i}. {name} — ⭐️{p['level']} ({p['experience']} EXP)"
        )

    leaderboard = "\n".join(leaderboard_lines)

    await update.message.reply_photo(
        photo=IMAGE_CACHE["XP_TOP_IMG"],
        caption=f"🏆 <b>Топ 100 игроков по уровню:</b>\n\n{leaderboard}",
        parse_mode="HTML"
    )


# ======================= РЕФЕРАЛЬНАЯ СИСТЕМА =======================

async def ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /ref - реферальная ссылка"""
    user = update.effective_user

    await safe_reply_text(update.message,
                          f"👥 *Реферальная программа*\n\n"
                          f"Приглашай друзей и получай:\n"
                          f"• 💰 $500 000\n"
                          f"• ✨ 300 EXP\n\n"
                          f"Твой друг получит:\n"
                          f"• 💰 $250 000\n"
                          f"• ⭐️ 3 LVL (136 EXP)\n\n"
                          f"*Твоя ссылка:*\n"
                          f"`t.me/truesmilybot?start={user.id}`",
                          parse_mode="Markdown"
                          )


# ======================= ПЕРЕДАЧА ДЕНЕГ =======================

async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /give - передать деньги игроку (ответом)"""
    ensure_user_exists(update.effective_user)

    if not context.args:
        await safe_reply_text(update.message,
                              "❌ Укажи сумму: `/give 1000`\n"
                              "Также: `/give 5k`, `/give all`",
                              parse_mode="Markdown"
                              )
        return

    reply = update.message.reply_to_message

    if not reply or not reply.from_user or reply.from_user.is_bot:
        await safe_reply_text(update.message,
                              "❌ Используй /give ответом на сообщение игрока"
                              )
        return

    user = update.effective_user
    target = reply.from_user

    if target.id == user.id:
        await safe_reply_text(update.message, "❌ Нельзя передать деньги самому себе")
        return

    # Парсинг суммы
    amount = parse_bet_amount(context.args[0], user.id, user.username)

    if amount is None or amount <= 0:
        await safe_reply_text(update.message, "❌ Некорректная сумма")
        return

    user_balance = get_balance(user.id, user.username)

    if amount > user_balance:
        await safe_reply_text(update.message,
                              f"❌ Недостаточно средств.\n"
                              f"💰 Твой баланс: {spaced_num(user_balance)} $miles",
                              parse_mode="Markdown"
                              )
        return

    # Передача денег
    target_balance = get_balance(target.id, target.username)

    set_balance(user.id, user_balance - amount)
    set_balance(target.id, target_balance + amount)

    await safe_reply_text(update.message,
                          f"✅ Передано {spaced_num(amount)} $miles → {target.full_name}\n"
                          f"💰 Твой баланс: {spaced_num(get_balance(user.id, user.username))} $miles",
                          parse_mode="Markdown"
                          )


# ======================= СЛОТЫ =======================

def generate_spin_image(reel: list, state: str) -> io.BytesIO:
    """Генерация изображения результата слотов"""

    images = [SPRITES_CACHE[symbol] for symbol in reel]
    main_img = STATE_CACHE[state]

    result = Image.new('RGB', (1350, 730), (255, 255, 255))
    result.paste(main_img, (0, 0))

    x_offset = 136
    for img in images:
        result.paste(img, (x_offset, 297), img)
        x_offset += 365
    bio = io.BytesIO()
    bio.name = 'temp_spin.jpeg'
    result.save(bio, 'JPEG', quality=50, optimize=False)
    bio.seek(0)
    return bio


async def spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /spin - игра в слоты"""
    user_id = update.effective_user.id
    username = update.effective_user.username

    ensure_user_exists(update.effective_user)

    # Проверка аргументов
    if not context.args:
        await safe_reply_text(update.message,
                              "❌ Укажи ставку: `/spin 100`\n"
                              "Также: `/spin 1k`, `/spin all`",
                              parse_mode="Markdown"
                              )
        return

    # Парсинг ставки
    bet = parse_bet_amount(context.args[0], user_id, username)

    if bet is None:
        await safe_reply_text(update.message, "❌ Некорректная ставка")
        return

    balance = get_balance(user_id, username)

    if bet < MIN_BET:
        await safe_reply_text(update.message, f"💸 Минимальная ставка: {spaced_num(MIN_BET)} $miles")
        return

    if bet > balance:
        await safe_reply_text(update.message,
                              f"💸 Недостаточно средств.\n💰 Баланс: {spaced_num(balance)} $miles"
                              )
        return

    # Снимаем ставку
    set_balance(user_id, balance - bet)

    # Получаем бонусы
    biz_bonuses = get_user_business_bonuses(user_id)

    # Крутим барабаны
    reel = [random.choice(SLOTS_SYMBOLS) for _ in range(3)]

    # Бонус на джекпот от завода слотов
    if biz_bonuses.get('jackpot_luck', 0):
        chance_jackpot = random.randint(0, 100)
        if chance_jackpot <= biz_bonuses['jackpot_luck']:
            reel = ['7', '7', '7']

    # Подсчёт выигрыша
    win = 0
    gained_exp = 0

    # Множитель опыта
    mastery_bonus = get_user_bonuses(user_id, 'mastery')
    business_bonus = biz_bonuses.get('game_mastery', 0)
    exp_mult = calculate_exp_multiplier(bet, mastery_bonus, business_bonus)
    state = "win"
    # Результаты
    if reel[0] == reel[1] == reel[2]:
        if reel[0] == '7':
            win = bet * 100
            gained_exp = round(2 * exp_mult, 1)
            msg = "💎 <b>ДЖЕКПОТ 100X!</b>"
            state = "jackpot"
        elif reel[0] == '🔔':
            win = bet * 25
            gained_exp = round(1.5 * exp_mult, 1)
            msg = "🔔 <b>Огромный выигрыш 25X!</b>"
        else:
            win = bet * 5
            gained_exp = round(1 * exp_mult, 1)
            msg = "🎉 <b>Большой выигрыш 5X!</b>"

    elif '7' not in reel and '🔔' not in reel:
        if any(reel.count(sym) == 2 for sym in ['🍒', '🍋', '🍉']):
            win = int(bet * 1.5)
            gained_exp = round(0.5 * exp_mult, 1)
            msg = "💪 <b>Выигрыш 1.5X!</b>"
        else:
            # Проигрыш
            gained_exp = round(0.1 * exp_mult, 1)
            msg = "🙈 <b>Проигрыш</b>"
            state = "lose"

            # Кэшбэк от удачи
            luck_bonus = get_user_bonuses(user_id, 'luck')
            if luck_bonus and random.randint(0, 100) < luck_bonus:
                cashback = round(bet * 0.2)
                win = cashback
                msg += f"\n🍀 Повезло! Возвращено 20% ({spaced_num(cashback)} $miles)"
    else:
        # Проигрыш
        gained_exp = round(0.1 * exp_mult, 1)
        msg = "🙈 <b>Проигрыш</b>"
        state = "lose"
        # Кэшбэк от удачи
        luck_bonus = get_user_bonuses(user_id, 'luck')
        if luck_bonus and random.randint(0, 100) < luck_bonus:
            cashback = round(bet * 0.2)
            win = cashback
            msg += f"\n🍀 Повезло! Возвращено 20% ({spaced_num(cashback)} $miles)"

    win_bonus = get_user_business_bonuses(user_id).get("win_multiplier", 0)
    win_bonus_amount = int(win * win_bonus)
    bonus_text = f"❇️ Бонус: {spaced_num(win_bonus_amount)} $miles\n" if win_bonus_amount else ""

    # Начисляем выигрыш и опыт
    set_balance(user_id, get_balance(user_id, username) + win + win_bonus_amount)
    update_experience(user_id, gained_exp)

    # Информация об уровне
    player_level = get_experience(user_id, username)
    current_level = player_level[0]
    current_xp = player_level[1]
    next_level_xp = player_level[2]

    result_text = " | ".join(reel)
    win_text = f"💵 Выигрыш: {spaced_num(win)} $miles\n"
    lose_text = f"☹️ Вы потеряли: {spaced_num(bet)} $miles\n"
    caption = (
        f"<blockquote> 🎰 СЛОТЫ </blockquote>\n"
        f"\t\t{result_text}\n\n"
        f"{msg}\n"
        f"{win_text if win > 0 else lose_text}"
        f"{bonus_text}"
        f"✨ Опыт: +{gained_exp} EXP\n"
        f"⭐️ Уровень: {current_level} ({current_xp}/{next_level_xp})\n"
        f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
    )

    # Отправка с картинкой
    try:
        image_stream = generate_spin_image(reel, state)
        await update.message.reply_photo(
            photo=image_stream,
            caption=caption,
            parse_mode="HTML"
        )
        image_stream.close()
    except Exception as e:
        print(f"Error generating spin image: {e}")
        await safe_reply_text(update.message, caption, parse_mode="Markdown")


# ======================= КОЛЕСО УДАЧИ =======================

async def lucky_wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /lucky_wheel - бесплатное колесо удачи (раз в 30 мин)"""
    user = update.effective_user
    ensure_user_exists(user)

    check = check_lucky_wheel_availability(user.id)
    if check:
        remaining = check  # количество минут до следующего спина
        await safe_reply_text(update.message,
                              f"⏳ Подожди ещё {remaining} минут.\n"
                              f"⏰ Колесо доступно раз в {LUCKY_WHEEL_COOLDOWN} минут."
                              )
        return

    # Крутим колесо
    win = random.choice(LUCKYWHEEL_PRIZES)
    win_sum = win[1]

    balance = get_balance(user.id, user.username)
    set_balance(user.id, balance + win_sum)

    text = (
        f"<blockquote>🎡 КОЛЕСО УДАЧИ</blockquote>\n\n"
        f"💵 Выигрыш: {spaced_num(win_sum)} $miles\n"
        f"💰 Баланс: {spaced_num(get_balance(user.id, user.username))} $miles\n\n"
        f"⏰ Возвращайся через {LUCKY_WHEEL_COOLDOWN} минут!"
    )

    await update.message.reply_text(
        text=text,
        parse_mode="HTML"
    )

async def exp_case(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /exp_case - бесплатный кейс с опытом (раз в 45 мин)"""
    user = update.effective_user
    ensure_user_exists(user)

    check = check_exp_case_availability(user.id)
    if check:
        remaining = check  # количество минут до следующего спина
        await safe_reply_text(update.message,
                              f"⏳ Подожди ещё {remaining} минут.\n"
                              f"⏰ Кейс доступен раз в {EXP_CASE_COOLDOWN} минут."
                              )
        return

    # Крутим колесо
    win = random.choice(EXP_CASE_PRIZES)
    win_exp = win[1]

    update_experience(user.id, win_exp)
    lvl, xp, next_xp = get_experience(user.id)

    text = (
        f"<blockquote>🎁 КЕЙС ОПЫТА</blockquote>\n\n"
        f"✨ Выигрыш: {win_exp} EXP\n"
        f"⭐️ Ваш уровень: {lvl} ({xp}/{next_xp} EXP)\n\n"
        f"⏰ Возвращайся через {EXP_CASE_COOLDOWN} минут!"
    )

    await update.message.reply_text(
        text=text,
        parse_mode="HTML"
    )

# ======================= КРАЖА И ВЗЛОМ =======================

async def steal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /steal - украсть у игрока (ответом)"""
    reply = update.message.reply_to_message
    ensure_user_exists(update.effective_user)

    if not reply or reply.from_user.is_bot:
        await safe_reply_text(update.message,
                              "❌ Используй /steal ответом на сообщение игрока"
                              )
        return

    user = update.effective_user
    target = reply.from_user

    if target.id == user.id:
        await safe_reply_text(update.message, "❌ Нельзя обокрасть самого себя!")
        return

    target_bal = get_balance(target.id, target.username)
    user_bal = get_balance(user.id, user.username)

    if target_bal < STEAL["min_target_balance"]:
        await safe_reply_text(update.message,
                              f"❌ У игрока меньше {STEAL['min_target_balance']}. $miles"
                              f"Не забирай последнее!"
                              )
        return

    # Проверка кулдауна
    availability = check_steal_availability(user.id)

    if availability != True:
        await safe_reply_text(update.message,
                              f"⏰ Попытка кражи доступна через {availability} мин.\n"
                              f"⏱️ Кулдаун: {STEAL_COOLDOWN} минут"
                              )
        return

    # Расчёт шансов с бонусами
    biz_bonuses_target = get_user_business_bonuses(target.id)
    biz_bonuses_user = get_user_business_bonuses(user.id)

    chance_bonus = biz_bonuses_target.get('steal_chance', 0)  # Защита
    chance_steal_bonus = biz_bonuses_user.get('steal_luck_chance', 0)  # Атака

    chance = random.randint(0, 100)

    # Джекпот (75% баланса)
    if chance == STEAL["jackpot_chance"]:
        steal_value = floor(target_bal * STEAL["jackpot_amount_percent"])
        set_balance(target.id, target_bal - steal_value)
        set_balance(user.id, user_bal + steal_value)

        msg = (
            f"💎 *ДЖЕКПОТ КРАЖИ!*\n"
            f"Обчистил {target.full_name} почти полностью!\n\n"
            f"💵 Украдено: {spaced_num(steal_value)} $miles\n"
            f"💰 Твой баланс: {spaced_num(user_bal + steal_value)} $miles\n"
            f"⏰ Следующая попытка через {STEAL_COOLDOWN} минут"
        )

    # Успех (1%)
    elif chance < (STEAL["success_chance_base"] + chance_bonus + chance_steal_bonus):
        steal_value = floor(target_bal * STEAL["steal_amount_percent"])

        # Учёт талантов
        untouchable_reduce = get_user_bonuses(target.id, 'untouchable')
        agility_bonus = get_user_bonuses(user.id, 'agility')

        steal_value = steal_value - round(untouchable_reduce * steal_value)
        steal_value = steal_value + round(agility_bonus * steal_value)

        set_balance(target.id, target_bal - steal_value)
        set_balance(user.id, user_bal + steal_value)

        msg = (
            f"✅ *Успех!*\n"
            f"💵 Украдено: {spaced_num(steal_value)} $miles\n"
            f"💰 Твой баланс: {spaced_num(user_bal + steal_value)} $miles\n"
            f"⏰ Следующая попытка через {STEAL_COOLDOWN} минут"
        )

    # Провал (штраф)
    else:
        penalty = floor(user_bal * STEAL["fail_penalty_percent"])
        set_balance(user.id, user_bal - penalty)

        msg = (
            f"👮‍♀️ *Поймали!*\n"
            f"💵 Штраф: {spaced_num(penalty)} $miles\n"
            f"💰 Твой баланс: {spaced_num(user_bal - penalty)} $miles\n"
            f"⏰ Следующая попытка через {STEAL_COOLDOWN} минут"
        )

    await safe_reply_text(update.message, msg, parse_mode="Markdown")


async def hack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /hack - взлом банка (только при балансе = 0)"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    balance = get_balance(user_id, username)

    ensure_user_exists(update.effective_user)

    if balance > 0:
        await safe_reply_text(update.message,
                              "❌ У тебя ещё есть деньги!\n"
                              "Сначала проиграй всё, потом взламывай банк 😈"
                              )
        return

    # Анимация взлома
    progress_msg = await safe_reply_text(update.message,
                                         "🧠 *Взлом банка...*\n"
                                         "Прогресс: [░░░░░░░░] 0%"
                                         )

    await asyncio.sleep(1.0)
    hack_luck_chance = get_user_business_bonuses(user_id).get("hack_luck_chance", 0)
    # Проверка успеха
    if random.randint(0, 100) >= HACK["success_chance"] - hack_luck_chance:
        await progress_msg.edit_text("❌ *Взлом не удался!*", parse_mode="Markdown")
        return

    # Успех - определяем сумму
    roll = random.randint(0, 100)
    stolen = 0
    for chance, min_amount, max_amount in HACK["tiers"]:
        if roll <= chance:
            stolen = random.randint(min_amount, max_amount)
            break

    set_balance(user_id, get_balance(user_id, username) + stolen)

    await progress_msg.edit_text(
        f"✅ *Взлом успешен!*\n"
        f"💵 Украдено: {spaced_num(stolen)} $miles\n"
        f"💰 Баланс: {spaced_num(stolen)} $miles",
        parse_mode="Markdown"
    )


# ======================= ВКЛАДЫ =======================

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /deposit - сделать вклад"""
    user_id = update.message.from_user.id

    # Проверка активного вклада
    check = check_deposit_ready(user_id)

    if check is True:
        await safe_reply_text(update.message,
                              "🏦 Твой вклад уже завершён!\n"
                              "Нажми /claim, чтобы забрать деньги 💸"
                              )
        return

    if isinstance(check, list):
        if len(check) == 2:
            time_left = f"{check[0]} ч. {check[1]} мин."
        else:
            time_left = f"{check[0]} мин."

        await safe_reply_text(update.message,
                              "<blockquote>⏳ У тебя уже есть активный вклад.\n"
                              f"Осталось до завершения: {time_left}\n\n"
                              "После этого сможешь открыть новый депозит 💰</blockquote>",
                              parse_mode="HTML"
                              )
        return

    # Кнопки выбора вклада
    keyboard = [[
        InlineKeyboardButton("1️⃣", callback_data=f"deposit_deposit_1:{user_id}"),
        InlineKeyboardButton("2️⃣", callback_data=f"deposit_deposit_2:{user_id}"),
        InlineKeyboardButton("3️⃣", callback_data=f"deposit_deposit_3:{user_id}"),
        InlineKeyboardButton("4️⃣", callback_data=f"deposit_deposit_4:{user_id}"),
        InlineKeyboardButton("5️⃣", callback_data=f"deposit_deposit_5:{user_id}"),
        InlineKeyboardButton("6️⃣", callback_data=f"deposit_deposit_6:{user_id}"),
        InlineKeyboardButton("7️⃣", callback_data=f"deposit_deposit_7:{user_id}"),
    ]]

    await safe_reply_text(update.message,
                          "🏦 *Банковские вклады*\n"
                          "Заложи часть баланса и получи гарантированный доход без риска.\n\n"
                          "1️⃣ $100 000 — 6 часов, *+20%*\n"
                          "2️⃣ $1 000 000 — 12 часов, *+30%*\n"
                          "3️⃣ $10 000 000 — 18 часа, *+40%*\n"
                          "4️⃣ $100 000 000 — 24 часов, *+50%*\n"
                          "5️⃣ $1 000 000 000 — 30 часов, *+60%*\n"
                          "5️⃣ $10 000 000 000 — 36 часов, *+70%*\n"
                          "5️⃣ $100 000 000 000 — 42 часов, *+80%*\n\n"
                          "Выбери номер вклада ниже 👇",
                          reply_markup=InlineKeyboardMarkup(keyboard),
                          parse_mode="Markdown"
                          )


async def deposit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора вклада"""
    query = update.callback_query
    user = query.from_user
    # Парсинг данных
    key, owner_id = query.data.split(':')

    if str(owner_id) != str(user.id):
        await query.answer("⚠️ Это не твоя сессия!", show_alert=True)
        return

    await query.answer()

    # Получаем параметры вклада
    amount, multiplier, hours = DEPOSIT_OPTIONS[key.replace("deposit_", "", 1)]

    user_bal = get_balance(user.id, user.username)

    if user_bal < amount:
        await query.edit_message_text("❌ Недостаточно средств.")
        return

    # Создаём вклад
    new_balance = user_bal - amount
    bank_balance = int(amount * multiplier)

    set_balance(user.id, new_balance)
    update_bank_balance(user.id, bank_balance, hours)

    hours_text = f"{hours} часа" if hours == 3 else f"{hours} часов"

    await query.edit_message_text(
        f"✅ Отлично! Ожидай {hours_text}...\n"
        f"💵 Выплата: {spaced_num(bank_balance)} $miles",
        parse_mode="Markdown"
    )


async def claim_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /claim - забрать вклад"""
    user = update.effective_user
    remaining = check_deposit_ready(user.id)

    if isinstance(remaining, list):
        if len(remaining) == 2:
            time_left = f"{remaining[0]} ч. {remaining[1]} мин."
        else:
            time_left = f"{remaining[0]} мин."

        await safe_reply_text(update.message,
                              f"⏳ Вклад ещё не готов.\n"
                              f"Осталось: {time_left}"
                              )
        return

    if not remaining:
        await safe_reply_text(update.message, "⚠️ У тебя нет вкладов!")
        return

    # Забираем вклад
    bank_bal = claim_bank_balance(user.id)

    await safe_reply_text(update.message,
                          f"💵 Забрано со вклада: {spaced_num(bank_bal)} $miles\n"
                          f"💰 Твой баланс: {spaced_num(get_balance(user.id, user.username))} $miles",
                          parse_mode="Markdown"
                          )


async def check_all_deposits(context: ContextTypes.DEFAULT_TYPE):
    """Фоновая проверка готовности вкладов"""
    now = datetime.now()
    users = get_all_users_with_deposit()

    if not users:
        return

    for user in users:
        if user["deposit_end"] and now >= user["deposit_end"]:
            chat_id = user["telegram_id"]

            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="🏦 Твой вклад завершён! Нажми /claim 💸"
                )
            except Exception as e:
                print(f"Failed to notify user {chat_id}: {e}")

            update_user(user["telegram_id"], {"deposit_end": None})


async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # 1️⃣ Проверка аргумента
    if not context.args:
        await update.message.reply_text(
            "❌ Введи промокод: `/promo <промокод>`",
            parse_mode="Markdown"
        )
        return

    promocode = context.args[0]

    # 2️⃣ Проверка существования и статуса промокода
    ok, msg = check_promocode(promocode, user_id)
    if not ok:
        await update.message.reply_text(
            f"❌ *{msg}*",
            parse_mode="Markdown"
        )
        return

    # 3️⃣ Проверка требований
    ok, msg = await check_promocode_requirements(user_id, promocode)
    if not ok:
        await update.message.reply_text(
            f"❌ <b>Ты не выполнил все условия</b>:\n{msg}",
            parse_mode="HTML"
        )
        return

    # 4️⃣ Активация промокода
    # Атомарная попытка активации
    if not try_activate_promocode(promocode, user_id):
        await update.message.reply_text(
            "❌ Промокод больше недоступен",
            parse_mode="Markdown"
        )
        return

    # Выдача наград
    award_text = activate_promocode(user_id, promocode)
    await update.message.reply_text(
        award_text,
        parse_mode="Markdown"
    )


# ======================= ЭКСПОРТ =======================

__all__ = [
    # Основные
    'start', 'help_command', 'help_callback',
    'stats', 'check', 'top', 'top_lvl', 'ref', 'give',

    # Игры
    'spin', 'lucky_wheel', 'exp_case',

    # Действия
    'steal', 'hack', 'promo',

    # Вклады
    'deposit', 'deposit_choice', 'claim_deposit', 'check_all_deposits'
]
