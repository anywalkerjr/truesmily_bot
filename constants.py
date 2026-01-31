import os
from typing import List
from dotenv import load_dotenv

load_dotenv()
# ======================= БАЗА ДАННЫХ =======================

DB_CONFIG = {
    'host': os.getenv("DB_HOST"),
    'port': os.getenv("DB_PORT"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'database': os.getenv("DB_NAME"),
    'autocommit': True
}

# ======================= ОБЩИЕ ИГРОВЫЕ НАСТРОЙКИ =======================

MIN_BET = 1  # Минимальная ставка во всех играх

# ======================= СИСТЕМА ОПЫТА И УРОВНЕЙ =======================

BASE_XP = 23
XP_FACTOR = 1.1
MAX_LEVEL = 100

# Множители опыта от размера ставки
EXP_MULTIPLIERS_BY_BET = [
    (0, 1),  # < $1,000 → x1
    (1_000, 2),  # $1,000-$9,999 → x2
    (10_000, 3),  # $10,000-$99,999 → x3
    (100_000, 4),  # $100,000-$999,999 → x4
    (1_000_000, 5),  # $1,000,000-$99,999,999 → x5
    (100_000_000, 6),  # $100,000,000+ → x6
]

# ======================= ТАЛАНТЫ =======================

# Бонусы за уровень таланта
TALENT_BONUSES = {
    "untouchable": -0.25,  # -0.1% защита от кражи за уровень
    "agility": 0.5,  # +0.05% к краже за уровень
    "mastery": 0.1,  # было 0.2: +0.1 к множителю EXP за уровень (чтобы меньше разгонять EXP)
    "luck": 2  # +2% шанс на кэшбэк 20% за уровень
}

# Максимальные уровни талантов
TALENT_MAX_LEVELS = {
    "untouchable": 60,
    "agility": 30,
    "mastery": 60,
    "luck": 16
}

# Стоимость прокачки талантов
TALENT_COSTS = {
    "untouchable": {"base": 25_000, "multiplier": 1.4},
    "agility": {"base": 50_000, "multiplier": 1.2},
    "mastery": {"base": 50_000, "multiplier": 1.2},
    "luck": {"base": 200_000, "multiplier": 2.0}
}

# Требования к уровню игрока для талантов
TALENT_LEVEL_REQUIREMENTS = {
    "untouchable": {"base": 2, "step": 2},
    "agility": {"base": 2, "step": 1},
    "mastery": {"base": 1, "step": 1.2},
    "luck": {"base": 4, "step": 2}
}

# ======================= ТАЙМЕРЫ И КУЛДАУНЫ =======================

LUCKY_WHEEL_COOLDOWN = 30  # Минут между спинами колеса удачи
STEAL_COOLDOWN = 45  # Минут между попытками кражи
EXP_CASE_COOLDOWN = 45
# Групповые игры (рулетка)
GROUP_GAME_DURATION = 20  # Секунд до старта игры
BETTING_DEADLINE_OFFSET = 5  # За сколько секунд до старта закрывается приём ставок

# ======================= БЛЭКДЖЕК =======================

BLACKJACK = {
    # Множители выплат
    "blackjack_multiplier": 2.5,  # Натуральный блэкджек (A + 10/J/Q/K)
    "win_multiplier": 2.0,  # Обычная победа
    "push_multiplier": 1.0,  # Ничья

    # Опыт за игру
    "exp_win": 1.0,  # Базовый опыт за победу
    "exp_blackjack_bonus": 1.5,  # Бонус к опыту за натуральный блэкджек
    "exp_loss": 0.5,  # Опыт за проигрыш
    "exp_push": 0.5,  # Опыт за ничью

    # Карты
    "ranks": ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'],
    "card_values": {
        '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
        'J': 10, 'Q': 10, 'K': 10, 'A': 11
    }
}

# ======================= МИНЫ | ТАВЕР =======================

MINES = {
    # Опыт за игру
    "exp_win": 0.9,  # Базовый опыт за победу
    "exp_lose": 0.2,  # Опыт за проигрыш

}

TOWER = {
    # Опыт за игру
    "exp_win": 0.9,  # Базовый опыт за победу
    "exp_lose": 0.2,  # Опыт за проигрыш

}

# ======================= РУЛЕТКА =======================

ROULETTE = {
    "red_numbers": {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36},
    "black_numbers": {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35},

    # Множители выплат
    "multipliers": {
        'number': 36,  # Ставка на конкретное число
        'color': 2,  # Красное/чёрное
        'parity': 2,  # Чёт/нечет
        'dozen': 3  # Дюжина (1-12, 13-24, 25-36)
    },

    # Базовый опыт за разные типы ставок
    "base_exp": {
        'number': 5.0,  # За число (x36)
        'color': 0.5,  # За цвет (x2)
        'parity': 0.5,  # За чётность (x2)
        'dozen': 1.0,  # За дюжину (x3)
        'loss': 0.1  # За проигрыш
    },

    # Названия ставок для отображения
    "bet_names": {
        "чет": "🔸 На чётное",
        "нечет": "🔹 На нечётное",
        "п": "1️⃣ На первую дюжину (1-12)",
        "в": "2️⃣ На вторую дюжину (13-24)",
        "т": "3️⃣ На третью дюжину (25-36)",
        "к": "🟥 На красное",
        "ч": "⬛️ На чёрное"
    },

    # Допустимые типы ставок
    "valid_bet_types": {'к', 'ч', 'чет', 'нечет', 'п', 'в', 'т'}
}

# Добавляем числа 0-36 к допустимым ставкам
ROULETTE["valid_bet_types"].update({str(i) for i in range(37)})

# ======================= СЛОТЫ =======================

SLOTS = {
    # Символы и их вероятности (чем больше копий, тем выше шанс)
    "symbols": (
            ['7'] * 5 +  # Джекпот: шанс немного вырос (5 из 115)
            ['🔔'] * 12 +  # Колокол: средний выигрыш теперь чаще (12 из 115)
            ['🍉'] * 30 +  # Арбуз: высокая вероятность
            ['🍋'] * 33 +  # Лимон: высокая вероятность
            ['🍒'] * 35  # Вишня: самый частый символ (утешительный приз)
    ),

    # Спрайты для отображения
    "emoji_to_filename": {
        '7': 'seven.png',
        '🔔': 'bell.png',
        '🍋': 'lemon.png',
        '🍉': 'watermelon.png',
        '🍒': 'cherry.png'
    }
}

# ======================= КОЛЕСО УДАЧИ =======================

LUCKY_WHEEL = {
    # Призы: [сектор, сумма]
    "prizes": [
        [0, 100_000], [1, 250_000], [2, 500_000], [3, 1_000_000],
        [4, 100_000], [5, 250_000], [6, 250_000], [7, 100_000],
        [8, 250_000], [9, 100_000], [10, 250_000], [11, 100_000],
        [12, 500_000], [13, 100_000], [14, 1_000_000], [15, 500_000]
    ]
}
EXP_CASE = {
    # Призы: [сектор, сумма]
    "prizes": [
        [0, 30], [1, 60], [2, 100], [3, 150],
        [4, 30], [5, 60], [6, 60], [7, 30],
        [8, 60], [9, 30], [10, 60], [11, 30],
        [12, 100], [13, 30], [14, 150], [15, 100]
    ]
}

# ======================= ВКЛАДЫ =======================

DEPOSITS = {
    "deposit_1": (100_000, 1.20, 6),
    "deposit_2": (1_000_000, 1.30, 12),
    "deposit_3": (10_000_000, 1.40, 18),
    "deposit_4": (100_000_000, 1.50, 24),
    "deposit_5": (1_000_000_000, 1.60, 30),
    "deposit_6": (10_000_000_000, 1.70, 36),
    "deposit_7": (100_000_000_000, 1.80, 42),
}

# ======================= КРАЖА =======================

STEAL = {
    "min_target_balance": 10_000,  # Минимальный баланс жертвы
    "jackpot_chance": 0,  # Шанс (0%) украсть jackpot_amount_percent
    "success_chance_base": 28,  # было 31: базовый шанс успешной кражи (%)
    "steal_amount_percent": 0.005,  # было 0.01: процент кражи при успехе
    "fail_penalty_percent": 0.01,  # было 0.005: штраф при провале (доля от баланса вора)
    "jackpot_amount_percent": 0.75  # Процент при джекпоте (75%)
}

# ======================= ВЗЛОМ БАНКА =======================

HACK = {
    "success_chance": 60,  # Шанс успеха (40%)
    "min_amount": 1000,  # Минимальная сумма взлома
    "max_amount": 175000,  # Максимальная сумма взлома
    "tiers": [
        (15, 25000, 175000),  # 15% шанс: $25k-$175k
        (45, 5000, 25000),  # 30% шанс: $5k-$25k (45-15=30)
        (100, 1000, 5000)  # 55% шанс: $1k-$5k (100-45=55)
    ]
}

# ======================= ДУЭЛИ =======================

DUELS = {
    "games": {
        'dice': '🎲 Кубики',
        'basketball': '🏀 Баскетбол',
        'dart': '🎯 Дартс',
        'bowling': '🎳 Боулинг',
        'football': '⚽ Футбол'
    },
    "animations": {
        'dice': '🎲',
        'basketball': '🏀',
        'dart': '🎯',
        'bowling': '🎳',
        'football': '⚽'
    },
    "min_rounds": 1,
    "max_rounds": 10,
    "default_rounds": 3
}

# ======================= СООБЩЕНИЯ И ТЕКСТЫ =======================

MESSAGES = {
    "insufficient_funds": "💸 Недостаточно средств.\n💰 Твой баланс: ${balance}",
    "min_bet_error": "💸 Минимальная ставка: ${min_bet}",
    "invalid_bet": "❌ Некорректная ставка",
    "session_not_yours": "⚠️ Это не твоя сессия!",
    "session_not_found": "⚠️ Сессия не найдена или завершена",
    "already_have_session": "❌ У тебя уже есть активная игра. Заверши её, чтобы начать новую.",
}

# ======================= ЭМОДЗИ =======================

EMOJI = {
    "money": "💰",
    "balance": "💵",
    "level": "⭐️",
    "exp": "✨",
    "win": "🎉",
    "loss": "😢",
    "luck": "🍀",
    "warning": "⚠️",
    "error": "❌",
    "success": "✅",
    "timer": "⏳",
    "fire": "🔥",
    "diamond": "💎"
}


# ======================= ГЕНЕРАЦИЯ УРОВНЕЙ =======================

def generate_levels(base_xp: int = BASE_XP, factor: float = XP_FACTOR, max_lvl: int = MAX_LEVEL) -> List[List[int]]:
    """
    Генерация таблицы уровней с требуемым опытом
    Возвращает: [[уровень, общий_опыт], ...]
    """
    levels = [[1, 0]]
    total_xp = 0

    for lvl in range(2, max_lvl + 1):
        required = int(base_xp * (lvl ** factor))
        total_xp += required
        levels.append([lvl, total_xp])

    return levels


# Генерируем таблицу уровней при импорте
LEVELS = generate_levels()

# ======================= БИЗНЕСЫ =======================
BUSINESS_LIST = [
    {
        "id": 1,
        "name": "Прилавок с шаурмой",
        "emoji": "🌯",
        "price": 100_000,
        "income": 2_500,
        "lvl": 1,
        "mastery": 1,
        "bonus": None,
        "user_bonus": {}
    },
    {
        "id": 2,
        "name": "Таксопарк",
        "emoji": "🚕",
        "price": 500_000,
        "income": 12_150,
        "lvl": 2,
        "mastery": 3,
        "bonus": None,
        "user_bonus": {}
    },
    {
        "id": 3,
        "name": "Парк аттракционов",
        "emoji": "🎡",
        "price": 1_000_000,
        "income": 18_650,
        "lvl": 4,
        "mastery": 5,
        "bonus": None,
        "user_bonus": {}
    },
    {
        "id": 4,
        "name": "Ломбард",
        "emoji": "💍",
        "price": 2_000_000,
        "income": 22_500,
        "lvl": 5,
        "mastery": 8,
        "bonus": None,
        "user_bonus": {}
    },
    {
        "id": 5,
        "name": "Ночной клуб",
        "emoji": "🎉",
        "price": 5_000_000,
        "income": 55_250,
        "lvl": 7,
        "mastery": 10,
        "bonus": None,
        "user_bonus": {}
    },
    {
        "id": 6,
        "name": "Подпольное казино",
        "emoji": "🎰",
        "price": 10_000_000,
        "income": 82_500,
        "lvl": 9,
        "mastery": 12,
        "bonus": "+0.3 к множителю EXP для всех игр",
        "user_bonus": {"game_mastery": 0.3}
    },
    {
        "id": 7,
        "name": "Межпланетный курьер",
        "emoji": "🚀",
        "price": 25_000_000,
        "income": 206_250,
        "lvl": 12,
        "mastery": 18,
        "bonus": "+5% защита от /steal",
        "user_bonus": {"steal_chance": -5}
    },
    {
        "id": 8,
        "name": "Блокчейн-стартап",
        "emoji": "💎",
        "price": 50_000_000,
        "income": 412_500,
        "lvl": 15,
        "mastery": 24,
        "bonus": "+10% доходов от бизнесов",
        "user_bonus": {"income_multiplier": 0.1}
    },
    {
        "id": 9,
        "name": 'ЗАО "БЕЩЕКИ"',
        "emoji": "🏢",
        "price": 100_000_000,
        "income": 825_000,
        "lvl": 18,
        "mastery": 26,
        "bonus": "+10% шанс к /steal",
        "user_bonus": {"steal_luck_chance": 10}
    },
    {
        "id": 10,
        "name": "Завод по производству слотов",
        "emoji": "🏭",
        "price": 1_000_000_000,
        "income": 10_250_000,
        "lvl": 20,
        "mastery": 30,
        "bonus": "+2% шанс джекпота в /spin",
        "user_bonus": {"jackpot_luck": 2}
    },
    {
        "id": 11,
        "name": "Кальянная",
        "emoji": "💨",
        "price": 250_000,
        "income": 6750,
        "lvl": 2,
        "mastery": 5,
        "bonus": "+15% к шансу успеха /hack",
        "user_bonus": {"hack_luck_chance": 15}
    },
    {
        "id": 12,
        "name": "Кофейня 24/7",
        "emoji": "☕",
        "price": 750_000,
        "income": 12_500,
        "lvl": 3,
        "mastery": 4,
        "bonus": "+5% доходов от бизнесов",
        "user_bonus": {"income_multiplier": 0.05}
    },
    {
        "id": 13,
        "name": "Киберспортивная команда",
        "emoji": "🎮",
        "price": 3_500_000,
        "income": 37_500,
        "lvl": 6,
        "mastery": 9,
        "bonus": "+0.5 к множителю EXP для всех игр",
        "user_bonus": {"game_mastery": 0.5}
    },
    {
        "id": 14,
        "name": "Банк",
        "emoji": "🏦",
        "price": 15_000_000,
        "income": 135_000,
        "lvl": 10,
        "mastery": 14,
        "bonus": "+15% доходов от вкладов",
        "user_bonus": {"deposit_income_bonus": 0.15}
    },
    {
        "id": 15,
        "name": "Частная охранная корпорация",
        "emoji": "🛡️",
        "price": 40_000_000,
        "income": 350_000,
        "lvl": 14,
        "mastery": 20,
        "bonus": "+10% защита от /steal",
        "user_bonus": {"steal_chance": -10}
    },
    {
        "id": 16,
        "name": "Ферма ИИ",
        "emoji": "🤖",
        "price": 250_000_000,
        "income": 2_250_000,
        "lvl": 19,
        "mastery": 28,
        "bonus": "+10% к сумме выигрыша всех игр (кроме /duel, /lucky\_wheel, /exp\_case)",
        "user_bonus": {"win_multiplier": 0.1}
    },

]
BUSINESS_LIST.sort(key=lambda x: x["price"])

TOKEN = os.getenv("BOT_TOKEN")

REF_SYSTEM = {
    "ref_get": {
        "balance": 500_000,
        "xp": 136
    },
    "user_get": {
        "balance": 250_000,
        "xp": 300
    },
}

# ======================= ЭКСПОРТ =======================

__all__ = [
    # Конфиг
    'DB_CONFIG', 'TOKEN',

    # Общие
    'MIN_BET', 'BASE_XP', 'XP_FACTOR', 'MAX_LEVEL', 'LEVELS',
    'EXP_MULTIPLIERS_BY_BET', 'REF_SYSTEM',

    # Таланты
    'TALENT_BONUSES', 'TALENT_MAX_LEVELS', 'TALENT_COSTS', 'TALENT_LEVEL_REQUIREMENTS',

    # Таймеры
    'LUCKY_WHEEL_COOLDOWN', 'STEAL_COOLDOWN',
    'GROUP_GAME_DURATION', 'BETTING_DEADLINE_OFFSET',

    # Игры
    'BLACKJACK', 'ROULETTE', 'SLOTS', 'LUCKY_WHEEL', 'DUELS', 'MINES', 'TOWER',

    # Экономика
    'DEPOSITS', 'STEAL', 'HACK', 'BUSINESS_LIST',

    # UI
    'MESSAGES', 'EMOJI',

    # Функции
    'generate_levels'
]
