CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    first_name VARCHAR(255),
    balance BIGINT DEFAULT 100,
    gems BIGINT DEFAULT 0,
    level INT DEFAULT 1,
    experience DOUBLE DEFAULT 0.0,
    bank_balance BIGINT DEFAULT 0,
    deposit_end DATETIME NULL,
    last_lucky_wheel DATETIME NULL,
    last_exp_case DATETIME NULL,
    last_steal DATETIME NULL,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS talents (
    user_id BIGINT PRIMARY KEY,
    untouchable INT DEFAULT 0,
    agility INT DEFAULT 0,
    mastery INT DEFAULT 0,
    luck INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_businesses (
    user_id BIGINT PRIMARY KEY,
    businesses_ids JSON,
    acquired_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blackjack_sessions (
    telegram_id BIGINT PRIMARY KEY,
    bet BIGINT NOT NULL,
    player_cards JSON NOT NULL,
    dealer_cards JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS mines_sessions (
    telegram_id BIGINT PRIMARY KEY,
    bet BIGINT NOT NULL,
    field JSON NOT NULL,
    open_cells JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS tower_sessions (
    telegram_id BIGINT PRIMARY KEY,
    bet BIGINT NOT NULL,
    field JSON NOT NULL,
    open_cells JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS duels_sessions (
    user_id BIGINT NOT NULL,
    target_id BIGINT NOT NULL,
    bet BIGINT NOT NULL,
    game VARCHAR(50) DEFAULT '',
    round INT DEFAULT 3,
    user_score INT DEFAULT 0,
    target_score INT DEFAULT 0,
    move VARCHAR(20) DEFAULT '',
    current_round INT DEFAULT 0,
    PRIMARY KEY (user_id, target_id)
);

CREATE TABLE IF NOT EXISTS roulette_games (
    chat_id BIGINT PRIMARY KEY,
    start_time DATETIME NOT NULL,
    betting_deadline DATETIME NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS roulette_bets (
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    username VARCHAR(255),
    bet_type VARCHAR(20) NOT NULL,
    amount BIGINT NOT NULL,
    PRIMARY KEY (chat_id, user_id, bet_type)
);

CREATE TABLE IF NOT EXISTS promocodes (
    promocode VARCHAR(100) PRIMARY KEY,
    max_activations INT DEFAULT -1,
    activations_remaining INT DEFAULT -1,
    expiration_date DATE NULL,
    requirements JSON,
    award JSON,
    users JSON,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS crash_games (
    chat_id BIGINT PRIMARY KEY,
    start_time DATETIME NOT NULL,
    betting_deadline DATETIME NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS crash_bets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    username VARCHAR(255),
    target_multiplier DECIMAL(6,2) NOT NULL,
    amount BIGINT NOT NULL,
    UNIQUE KEY unique_user_crash_bet (chat_id, user_id)
);