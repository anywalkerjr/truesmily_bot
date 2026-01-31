from telegram import BotCommand, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, ContextTypes, MessageHandler, filters, PreCheckoutQueryHandler
)
from blackjack import blackjack, handle_blackjack_action
from buy_smiles import show_donate_menu, button_callback_handler, precheckout_handler, success_payment_handler
from constants import TOKEN
from roulette import roulette, game, check_all_games
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
    deposit, deposit_choice, claim_deposit, check_all_deposits, promo
)
from admin import (
    admin_panel, admin_give_money, admin_set_level,
    admin_set_talent, admin_give_business, admin_callback
)
from telegram.error import TimedOut, NetworkError
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
        BotCommand("exp_case", "🎁 Кейс опыта"),
        BotCommand("duel", "⚔️ Дуэль"),
        BotCommand("mines", "💣 Минки"),

        # Топы
        BotCommand("top", "🏆 Топ по балансу"),
        BotCommand("top_lvl", "⭐ Топ по уровню"),

        # Экономика
        BotCommand("shop", "🛒 Магазин"),
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

    await app.bot.set_my_commands(commands)


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
    app = ApplicationBuilder().token(token).build()

    # Установка команд меню
    app.post_init = set_commands

    # Установка логгера ошибок
    logger = logging.getLogger(__name__)

    async def on_error(update, context):
        err = context.error
        logger.exception("Update caused error", exc_info=err)

        # Таймауты/сеть — не считаем критикой, просто логируем
        if isinstance(err, (TimedOut, NetworkError)):
            return

    app.add_error_handler(on_error)
    # ===== ФОНОВЫЕ ЗАДАЧИ (job_queue) =====

    # Проверка вкладов каждую минуту
    app.job_queue.run_repeating(
        check_all_deposits,
        interval=60,
        first=10
    )

    # Проверка групповых игр рулетки каждые 3 секунды
    app.job_queue.run_repeating(
        check_all_games,
        interval=5,
        first=10
    )

    # Начисление пассивного дохода каждые 3 секунды
    app.job_queue.run_repeating(
        check_all_incomes,
        interval=60,
        first=10
    )

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

    # Колесо удачи
    app.add_handler(CommandHandler("lucky_wheel", lucky_wheel))
    app.add_handler(CommandHandler("exp_case", exp_case))

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

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        text_handler
    ))

    return app


# ======================= ЗАПУСК =====

if __name__ == "__main__":
    # ⚠️ ВНИМАНИЕ: Не храни токен в коде! Используй переменные окружения!
    # import os
    # TOKEN = os.getenv("BOT_TOKEN")

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
