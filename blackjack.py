from typing import List, Tuple, Dict
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from constants import BLACKJACK, MIN_BET, LEVELS
from helpers import (
    get_balance, set_balance, spaced_num,
    get_experience, update_experience,
    get_user_bonuses, ensure_user_exists, parse_bet_amount,
    calculate_exp_multiplier, create_blackjack_session,
    get_blackjack_session, delete_blackjack_session
)
from helpers import get_user_business_bonuses

# Извлекаем константы из словаря
RANKS = BLACKJACK["ranks"]
CARD_VALUES = BLACKJACK["card_values"]
BLACKJACK_MULTIPLIER = BLACKJACK["blackjack_multiplier"]
WIN_MULTIPLIER = BLACKJACK["win_multiplier"]
PUSH_MULTIPLIER = BLACKJACK["push_multiplier"]
EXP_WIN = BLACKJACK["exp_win"]
EXP_LOSS = BLACKJACK["exp_loss"]
EXP_PUSH = BLACKJACK["exp_push"]
EXP_BLACKJACK_BONUS = BLACKJACK["exp_blackjack_bonus"]


# ======================= ИГРОВАЯ ЛОГИКА =======================

def deal_card() -> Tuple[str, int]:
    """Раздать случайную карту"""
    rank = random.choice(RANKS)
    return rank, CARD_VALUES[rank]


def calculate_score(cards: List[Tuple[str, int]]) -> int:
    """
    Подсчёт очков с учётом мягких/жёстких тузов
    Туз считается за 11, но становится 1 если сумма > 21
    """
    score = sum(card[1] for card in cards)
    aces = sum(1 for card in cards if card[0] == 'A')

    while score > 21 and aces > 0:
        score -= 10
        aces -= 1

    return score


def is_blackjack(cards: List[Tuple[str, int]]) -> bool:
    """Проверка на натуральный блэкджек (21 с двух карт: A + 10/J/Q/K)"""
    if len(cards) != 2:
        return False

    ranks = [card[0] for card in cards]
    return 'A' in ranks and any(rank in ['10', 'J', 'Q', 'K'] for rank in ranks)


def format_cards(cards: List[Tuple[str, int]]) -> str:
    """Форматирование карт для отображения"""
    return ', '.join(card[0] for card in cards)


# ======================= РАСЧЁТ РЕЗУЛЬТАТА =======================

def calculate_game_result(
        player_cards: List[Tuple[str, int]],
        dealer_cards: List[Tuple[str, int]],
        bet: int
) -> Dict:
    """
    Расчёт результата игры
    Возвращает: {'result': str, 'winnings': int, 'multiplier': float}
    """
    player_score = calculate_score(player_cards)
    dealer_score = calculate_score(dealer_cards)

    # Натуральный блэкджек игрока
    if is_blackjack(player_cards):
        return {
            'result': 'blackjack',
            'winnings': int(bet * BLACKJACK_MULTIPLIER),
            'multiplier': BLACKJACK_MULTIPLIER
        }

    # Перебор дилера или игрок набрал больше
    if dealer_score > 21 or player_score > dealer_score:
        return {
            'result': 'win',
            'winnings': int(bet * WIN_MULTIPLIER),
            'multiplier': WIN_MULTIPLIER
        }

    # Ничья
    if player_score == dealer_score:
        return {
            'result': 'push',
            'winnings': bet,
            'multiplier': PUSH_MULTIPLIER
        }

    # Проигрыш
    return {
        'result': 'loss',
        'winnings': 0,
        'multiplier': 0
    }


def calculate_exp_reward(result: str, bet: int, user_id: int) -> float:
    """Расчёт опыта за игру с учётом множителей"""
    # Базовый опыт от результата
    base_exp = {
        'blackjack': EXP_WIN * EXP_BLACKJACK_BONUS,  # Бонус за блэкджек
        'win': EXP_WIN,
        'push': EXP_PUSH,
        'loss': EXP_LOSS
    }.get(result, EXP_LOSS)

    # Бонусы от талантов и бизнесов
    mastery_bonus = get_user_bonuses(user_id, 'mastery')
    biz_bonuses = get_user_business_bonuses(user_id)
    business_bonus = biz_bonuses.get('game_mastery', 0)

    # Множитель от ставки
    exp_mult = calculate_exp_multiplier(bet, mastery_bonus, business_bonus)

    return round(base_exp * exp_mult, 1)


def apply_luck_cashback(user_id: int, username: str, bet: int) -> Tuple[int, str]:
    """
    Проверка и применение кэшбэка от таланта "Удача"
    Возвращает: (cashback_amount, bonus_text)
    """
    luck_bonus = get_user_bonuses(user_id, 'luck')

    if not luck_bonus:
        return 0, ''

    # Проверка срабатывания (процент от luck_bonus)
    if random.randint(0, 100) < luck_bonus:
        cashback = round(bet * 0.2)
        current_balance = get_balance(user_id, username)
        set_balance(user_id, current_balance + cashback)

        bonus_text = f"\n🍀 Тебе повезло! Возвращено 20% ({spaced_num(cashback)} $miles) от ставки!"
        return cashback, bonus_text

    return 0, ''


# ======================= КОМАНДЫ =======================

async def blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /bj - начало игры в блэкджек"""
    user = update.effective_user
    user_id = user.id
    username = user.username

    ensure_user_exists(user)

    # Проверка наличия активной сессии
    if get_blackjack_session(user_id):
        await update.message.reply_text(
            "❌ У тебя уже есть активная игра. Заверши её, чтобы начать новую."
        )
        await send_blackjack_state(update, context, user_id, False)
        return

    # Проверка наличия аргументов
    if not context.args:
        await update.message.reply_text(
            "❌ Укажи сумму ставки. Пример: /bj 50\n"
            "Также можешь использовать: /bj all, /bj 1k, /bj 5kk"
        )
        return

    # Парсинг ставки
    bet = parse_bet_amount(context.args[0], user_id, username)

    if bet is None:
        await update.message.reply_text("❌ Некорректная ставка")
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

    # Раздача карт
    player_cards = [deal_card(), deal_card()]
    dealer_cards = [deal_card(), deal_card()]

    # Создаём сессию
    create_blackjack_session(user_id, bet, player_cards, dealer_cards)

    # Отображаем начальное состояние
    await send_blackjack_state(update, context, user_id)


async def send_blackjack_state(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        is_callback: bool = False
):
    """Отправка текущего состояния игры"""
    session = get_blackjack_session(user_id)

    if not session:
        if is_callback:
            await update.callback_query.answer("⚠️ Сессия не найдена", show_alert=True)
        return

    player_cards = session["player"]
    dealer_cards = session["dealer"]
    bet = session["bet"]

    player_score = calculate_score(player_cards)

    # Формируем текст
    text = (
        f"🃏 *Blackjack*\n"
        f"💵 Ставка: {spaced_num(bet)} $miles\n\n"
        f"🤖 Дилер: {dealer_cards[0][0]}, ❓\n"
        f"👤 Ты: {format_cards(player_cards)} (Очки: {player_score})"
    )

    # Кнопки действий
    keyboard = [[
        InlineKeyboardButton("🃙 Ещё карту", callback_data=f"hit:{user_id}"),
        InlineKeyboardButton("🛑 Хватит", callback_data=f"stand:{user_id}")
    ]]

    if is_callback:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def handle_blackjack_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий в игре (Hit/Stand)"""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    username = user.username

    # Парсинг callback data
    try:
        action, session_owner = query.data.split(':')
    except ValueError:
        await query.answer("⚠️ Ошибка данных", show_alert=True)
        return

    # Проверка владельца сессии
    if str(session_owner) != str(user_id):
        await query.answer("⚠️ Это не твоя сессия!", show_alert=True)
        return

    # Получение сессии
    session = get_blackjack_session(user_id)

    if not session:
        await query.answer("⚠️ Сессия не найдена или завершена", show_alert=True)
        return

    await query.answer()

    player_cards = session["player"]
    dealer_cards = session["dealer"]
    bet = session["bet"]

    # ============= HIT - Взять карту =============
    if action == "hit":
        player_cards.append(deal_card())
        player_score = calculate_score(player_cards)

        # Проверка перебора
        if player_score > 21:
            # Игра окончена - перебор
            exp_gained = calculate_exp_reward('loss', bet, user_id)
            update_experience(user_id, exp_gained)

            # Кэшбэк от удачи
            cashback, bonus_text = apply_luck_cashback(user_id, username, bet)

            # Информация об уровне
            level_info = get_experience(user_id, username)
            current_level = level_info[0]
            current_xp = level_info[1]
            next_level_xp = level_info[2]

            text = (
                f"💥 *Перебор!* Очки: {player_score}\n"
                f"Карты: {format_cards(player_cards)}\n\n"
                f"❌ Ты проиграл {spaced_num(bet)}{bonus_text} $miles\n"
                f"✨ Получено: {exp_gained} EXP\n"
                f"⭐️ Уровень: {current_level} ({current_xp}/{next_level_xp})\n"
                f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
            )

            delete_blackjack_session(user_id)
            await query.edit_message_text(text, parse_mode="Markdown")
            return

        # Обновляем сессию и показываем состояние
        create_blackjack_session(user_id, bet, player_cards, dealer_cards)
        await send_blackjack_state(update, context, user_id, is_callback=True)

    # ============= STAND - Остановиться =============
    elif action == "stand":
        # Дилер добирает карты (правило: < 17)
        while calculate_score(dealer_cards) < 17:
            dealer_cards.append(deal_card())

        player_score = calculate_score(player_cards)
        dealer_score = calculate_score(dealer_cards)

        # Определяем результат
        game_result = calculate_game_result(player_cards, dealer_cards, bet)
        result = game_result['result']
        winnings = game_result['winnings']
        win_bonus_amount = 0
        # Начисляем выигрыш
        if winnings > 0:
            win_bonus = get_user_business_bonuses(user_id).get("win_multiplier", 0)
            win_bonus_amount = int(winnings * win_bonus)
            current_balance = get_balance(user_id, username)
            set_balance(user_id, current_balance + winnings + win_bonus_amount)

        bonus_text = f"\n❇️ Бонус: {spaced_num(win_bonus_amount)} $miles" if win_bonus_amount else ""
        # Начисляем опыт
        exp_gained = calculate_exp_reward(result, bet, user_id)
        update_experience(user_id, exp_gained)

        # Формируем сообщение о результате
        result_messages = {
            'blackjack': f"🎉 *BLACKJACK!* Ты выиграл {spaced_num(winnings)} $miles!"  + bonus_text,
            'win': f"🏆 *Победа!* Ты выиграл {spaced_num(winnings)} $miles!" + bonus_text,
            'push': f"🤝 *Ничья.* Ставка возвращена.",
            'loss': f"❌ *Проигрыш.* Ты потерял {spaced_num(bet)} $miles."
        }

        result_text = result_messages[result]

        # Кэшбэк от удачи (только при проигрыше)
        bonus_text = ''
        if result == 'loss':
            cashback, bonus_text = apply_luck_cashback(user_id, username, bet)

        # Информация об уровне
        level_info = get_experience(user_id, username)
        current_level = level_info[0]
        current_xp = level_info[1]
        next_level_xp = level_info[2]

        text = (
            f"{result_text}{bonus_text}\n\n"
            f"🤖 Дилер: {format_cards(dealer_cards)} (Очки: {dealer_score})\n"
            f"👤 Ты: {format_cards(player_cards)} (Очки: {player_score})\n\n"
            f"✨ Получено: {exp_gained} EXP\n"
            f"⭐️ Уровень: {current_level} ({current_xp}/{next_level_xp})\n"
            f"💰 Баланс: {spaced_num(get_balance(user_id, username))} $miles"
        )

        delete_blackjack_session(user_id)
        await query.edit_message_text(text, parse_mode="Markdown")


# ======================= ЭКСПОРТ =======================

__all__ = [
    'blackjack',
    'handle_blackjack_action',
    'send_blackjack_state'
]
