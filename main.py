from telegram import BotCommand, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, ContextTypes, MessageHandler, filters, PreCheckoutQueryHandler
)
from blackjack import blackjack, handle_blackjack_action
from buy_smiles import show_donate_menu, button_callback_handler, precheckout_handler, success_payment_handler
from cases import (
    handle_case_purchase, cases_command, cases_menu_callback,
    case_info_handler, case_cooldown_callback
)
from constants import TOKEN, PROXY_URL
from roulette import roulette, game, check_all_games
from crash import crash, check_all_crash_games, lobby
from talents import talents, talent_info, upgrade_talent
from shop import shop, shop_callback, my_biz, check_all_incomes
from main_duels import duel, my_duels
from duel_handlers import handle_game_selection, handle_round_selection, decline_duel
from duel_turn_logic import handle_duel_turn
from mines import mines, handle_mines_action
from tower import tower, handle_tower_action

# Импорт команд (создадим отдельный файл)
from commands import (
    start, help_command, help_callback, stats, top, top_lvl,
    check, give, ref, spin, lucky_wheel, exp_case, hack, steal,
    deposit, deposit_choice, claim_deposit, check_all_deposits, promo, handle_text
)
from admin import (
    admin_panel, admin_give_money, admin_set_level,
    admin_set_talent, admin_give_business, admin_callback,
    admin_create_promocode
)
from telegram.error import TimedOut, NetworkError, RetryAfter, BadRequest
from rate_limiter import FloodControlLimiter
from button_debouncer import button_anti_flood_middleware
import logging


# ======================= НАСТРОЙКА КОМАНД БОТА =======================

async def set_commands(app):
    """Регистрация команд в меню бота"""
    commands = [
        BotCommand("start", "🚀 Начать игру"),
        BotCommand("help", "❓ Справка"),
        BotCommand("stats", "📊 Моя статистика"),
        BotCommand("check", "👤 Проверить игрока"),

        # Игры
        BotCommand("spin", "🎰 Слоты"),
        BotCommand("bj", "🃏 Блэкджек"),
        BotCommand("rt", "🎲 Рулетка"),
        BotCommand("lucky_wheel", "🎡 Колесо удачи"),
        BotCommand("duel", "⚔️ Дуэль"),
        BotCommand("mines", "💣 Минки"),
        BotCommand("tower", "🛕 Башня"),

        # Топы
        BotCommand("top", "🏆 Топ по балансу"),
        BotCommand("top_lvl", "⭐ Топ по уровню"),

        # Экономика
        BotCommand("shop", "🛒 Магазин"),
        BotCommand("cases", "📦 Магазин кейсов"),
        BotCommand("my_biz", "🏢 Мои бизнесы"),
        BotCommand("talents", "✨ Таланты"),
        BotCommand("give", "💸 Передать деньги"),
        BotCommand("promo", "🆕 Активировать промокод"),
        BotCommand("stars", "⭐ Купить опыт за звёзды"),
        # Вклады
        BotCommand("deposit", "🏦 Сделать вклад"),
        BotCommand("claim", "💵 Забрать вклад"),

        # Действия
        BotCommand("steal", "🕵️ Украсть у игрока"),
        BotCommand("hack", "💻 Взлом банка"),
        BotCommand("ref", "👥 Реферальная ссылка"),
    ]

    try:
        await app.bot.set_my_commands(commands)
    except (TimedOut, NetworkError) as e:
        # Не роняем запуск бота из-за сетевого сбоя на этапе установки меню команд.
        logging.getLogger(__name__).warning("set_my_commands failed: %s", e)


# ======================= ОБРАБОТЧИК ТЕКСТА (КНОПКИ) =======================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок клавиатуры"""
    if update.effective_chat.type != "private":
        return
    text = update.message.text

    # Маппинг кнопок на команды
    button_mapping = {
        "🎰 Слоты": "Используй /spin <ставка>",
        "🎲 Рулетка": "Используй /rt <тип> <ставка>",
        "🏆 Топ": "Смотри /top или /top_lvl",
        "📊 Статистика": "Твоя статистика в /stats",
        "🛒 Магазин": "Открываю /shop",
        "✨ Таланты": "Открываю /talents",
        "🏦 Вклад": "Используй /deposit или /claim",
        "💻 Взлом банка": "Используй /hack",
        "🎡 Колесо удачи": "Используй /lucky_wheel",
        "🕵️ Украсть": "Ответь на сообщение и используй /steal"
    }

    response = button_mapping.get(text, "❓ Неизвестная команда. Используй /help")
    await update.message.reply_text(response)


# ======================= ПОСТРОЕНИЕ БОТА =======================

def build_bot(token: str):
    """
    Построение и настройка бота

    Args:
        token: Токен бота от BotFather

    Returns:
        Настроенное приложение
    """
    builder = ApplicationBuilder().token(token)
    # Защита от флуда и RetryAfter для всех типов сообщений и вызовов API
    builder = builder.rate_limiter(FloodControlLimiter())
    proxy_url = (PROXY_URL or "").strip()

    if proxy_url:
        builder = builder.proxy(proxy_url).get_updates_proxy(proxy_url)
        print(f"🌐 Telegram proxy enabled: {proxy_url}")
    else:
        print("🌐 Telegram proxy disabled")

    app = builder.build()

    # Установка команд меню
    app.post_init = set_commands

    # Установка логгера ошибок
    logger = logging.getLogger(__name__)

    async def on_error(update, context):
        err = context.error
        # Таймауты, сеть и флуд-контроль — логируем без падения
        if isinstance(err, RetryAfter):
            logger.warning("Flood control exceeded (RetryAfter): %s", err)
            return
        if isinstance(err, BadRequest):
            msg = str(err).lower()
            if "message is not modified" in msg or "query is too old" in msg:
                # Штатные ситуации при быстрых кликах инлайн-кнопок
                return
        if isinstance(err, (TimedOut, NetworkError)):
            logger.warning("Network issue: %s", err)
            return

        logger.exception("Update caused error", exc_info=err)

    app.add_error_handler(on_error)
    # ===== ФОНОВЫЕ ЗАДАЧИ (job_queue) =====

    # Проверка вкладов каждую минуту
    app.job_queue.run_repeating(
        check_all_deposits,
        interval=60,
        first=10
    )

    # Проверка групповых игр рулетки каждые 5 секунд
    app.job_queue.run_repeating(
        check_all_games,
        interval=5,
        first=10
    )

    # Проверка групповых раундов Crash каждые 3 секунды
    app.job_queue.run_repeating(
        check_all_crash_games,
        interval=3,
        first=10
    )

    # Начисление пассивного дохода каждые 3 секунды
    app.job_queue.run_repeating(
        check_all_incomes,
        interval=60,
        first=10
    )

    # ===== ЗАЩИТА ОТ ФЛУДА НА КНОПКАХ (group=-1 перехватывает клики до всех остальных хэндлеров) =====
    app.add_handler(CallbackQueryHandler(button_anti_flood_middleware), group=-1)

    # ===== ОСНОВНЫЕ КОМАНДЫ =====

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("ref", ref))
    app.add_handler(CommandHandler("promo", promo))

    # ===== АДМИН-ПАНЕЛЬ (только для @desenk02) =====

    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("admin_money", admin_give_money))
    app.add_handler(CommandHandler("admin_level", admin_set_level))
    app.add_handler(CommandHandler("admin_talent", admin_set_talent))
    app.add_handler(CommandHandler("admin_biz", admin_give_business))
    app.add_handler(CommandHandler("admin_promo", admin_create_promocode))

    app.add_handler(CallbackQueryHandler(
        admin_callback,
        pattern=r"^admin_(help_|main)"
    ))
    # ===== ТОПЫ =====

    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("top_lvl", top_lvl))

    # ===== ИГРЫ =====

    # Слоты
    app.add_handler(CommandHandler("spin", spin))

    # Блэкджек
    app.add_handler(CommandHandler("bj", blackjack))
    app.add_handler(CallbackQueryHandler(
        handle_blackjack_action,
        pattern=r"^(hit|stand):"
    ))

    app.add_handler(CommandHandler("mines", mines))
    app.add_handler(CallbackQueryHandler(
        handle_mines_action,
        pattern=r"^(mine:|mine_cashout:|mine_opened)"
    ))
    app.add_handler(CommandHandler("tower", tower))
    app.add_handler(CallbackQueryHandler(
        handle_tower_action,  # Лучше сделать отдельную функцию
        pattern=r"^(tower:|tower_cashout:|tower_opened)"
    ))

    # Рулетка
    app.add_handler(CommandHandler("rt", roulette))
    app.add_handler(CommandHandler("game", game))

    # Crash
    app.add_handler(CommandHandler("crash", crash))
    app.add_handler(CommandHandler("lobby", lobby))

    # Колесо удачи
    app.add_handler(CommandHandler("lucky_wheel", lucky_wheel))
    app.add_handler(CommandHandler("exp_case", exp_case))
    # Cases
    app.add_handler(CommandHandler("cases", cases_command))
    app.add_handler(CallbackQueryHandler(cases_menu_callback, pattern=r"^cases_menu:"))
    app.add_handler(CallbackQueryHandler(case_info_handler, pattern=r"^case_info:"))
    app.add_handler(CallbackQueryHandler(handle_case_purchase, pattern=r"^buy_case:"))
    app.add_handler(CallbackQueryHandler(case_cooldown_callback, pattern=r"^case_cooldown:"))

    # Дуэли
    app.add_handler(CommandHandler("duel", duel))
    app.add_handler(CommandHandler("my_duels", my_duels))
    app.add_handler(CommandHandler("turn", handle_duel_turn))
    app.add_handler(CallbackQueryHandler(
        handle_game_selection,
        pattern=r"^duel_game:"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_round_selection,
        pattern=r"^rounds:"
    ))
    app.add_handler(CallbackQueryHandler(
        decline_duel,
        pattern=r"^decline:"
    ))

    # ===== ТАЛАНТЫ =====

    app.add_handler(CommandHandler("talents", talents))
    app.add_handler(CallbackQueryHandler(
        talent_info,
        pattern=r"^talent_(untouchable|agility|mastery|luck):"
    ))
    app.add_handler(CallbackQueryHandler(
        upgrade_talent,
        pattern=r"^upgrade_(untouchable|agility|mastery|luck):"
    ))
    app.add_handler(CallbackQueryHandler(
        talents,
        pattern=r"^talents:"
    ))

    # ===== МАГАЗИН =====

    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("my_biz", my_biz))
    app.add_handler(CallbackQueryHandler(
        shop_callback,
        pattern=r"^shop_(prev|next|buy_\d+):"
    ))

    # ===== ВКЛАДЫ =====

    app.add_handler(CommandHandler("deposit", deposit))
    app.add_handler(CommandHandler("claim", claim_deposit))
    app.add_handler(CallbackQueryHandler(
        deposit_choice,
        pattern=r"^deposit_deposit_\d+:"
    ))
    app.add_handler(CallbackQueryHandler(
        deposit,
        pattern=r"^deposit"
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # ===== ДЕЙСТВИЯ =====

    app.add_handler(CommandHandler("steal", steal))
    app.add_handler(CommandHandler("hack", hack))

    # ===== СПРАВКА =====

    app.add_handler(CallbackQueryHandler(
        help_callback,
        pattern="^help_examples"
    ))
    app.add_handler(CallbackQueryHandler(
        help_command,
        pattern="^help_main"
    ))

    app.add_handler(CommandHandler("stars", show_donate_menu))
    # 2. Обработка нажатия на кнопки меню
    app.add_handler(CallbackQueryHandler(button_callback_handler, pattern="^stars_pack_"))
    # 3. Подтверждение платежа
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    # 4. Финальное начисление при успехе
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, success_payment_handler))

    # ===== ОБРАБОТЧИК ТЕКСТОВЫХ КНОПОК =====

    # app.add_handler(MessageHandler(
    #     filters.TEXT & ~filters.COMMAND,
    #     text_handler
    # ))

    return app


# ======================= ЗАПУСК =====

if __name__ == "__main__":
    app = build_bot(TOKEN)

    print("✅ Smily запущен!")
    print("📊 Активные модули:")
    print("   • Блэкджек")
    print("   • Рулетка")
    print("   • Слоты")
    print("   • Колесо удачи")
    print("   • Дуэли")
    print("   • Магазин")
    print("   • Таланты")
    print("   • Вклады")
    print("\n🔄 Фоновые задачи:")
    print("   • Проверка вкладов (каждую минуту)")
    print("   • Проверка рулетки (каждые 3 сек)")
    print("   • Пассивный доход (каждую минуту)")

    app.run_polling(drop_pending_updates=True)
