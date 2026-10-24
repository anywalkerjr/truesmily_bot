"""
Модуль локального анти-флуда для инлайн-кнопок (Button Debouncer / Throttler).

Защищает Telegram API от превышения лимитов при спам-кликах по кнопкам
(мины, блэкджек, башня, кейсы, магазин и т.д.):
  1. Первый клик по кнопке выполняется мгновенно (без задержки).
  2. Если пользователь спамит кнопку (кликает 50-100 раз за секунду):
     - Ровно один отложенный клик сохраняется и автоматически срабатывает
       после истечения кулдауна (1.0 сек), как и ожидают игроки.
     - Все лишние промежуточные клики немедленно гасятся через query.answer()
       и останавливаются через ApplicationHandlerStop, не нагружая БД и Telegram API.
  3. Кулдаун действует локально в рамках одной связки (пользователь, сообщение).
"""

import asyncio
import logging
from typing import Dict, Tuple, Any
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop

logger = logging.getLogger(__name__)


class ButtonAntiFlood:
    """
    Ограничитель частоты нажатий на инлайн-кнопки одного сообщения.
    """

    def __init__(self, cooldown: float = 1.0) -> None:
        self.cooldown = cooldown
        self._last_time: Dict[Tuple[int, int, Any], float] = {}
        self._has_pending: Dict[Tuple[int, int, Any], bool] = {}

    def _cleanup_old_keys(self, now: float) -> None:
        """Периодическая очистка устаревших ключей (старше 60 секунд) для экономии памяти."""
        if len(self._last_time) > 2000:
            stale_keys = [
                k for k, t in self._last_time.items()
                if (now - t) > 60.0 and not self._has_pending.get(k, False)
            ]
            for k in stale_keys:
                self._last_time.pop(k, None)
                self._has_pending.pop(k, None)

    async def check_and_throttle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Проверяет и ограничивает клики по кнопкам.
        Вызывается в CallbackQueryHandler с group=-1.
        """
        query = update.callback_query
        if not query:
            return

        user_id = query.from_user.id if query.from_user else (
            update.effective_user.id if update.effective_user else 0
        )

        # Извлекаем message_id и chat_id для точечной привязки к конкретному сообщению
        if query.message:
            message_id = query.message.message_id
            chat_id = query.message.chat_id
        else:
            message_id = query.inline_message_id or 0
            chat_id = update.effective_chat.id if update.effective_chat else 0

        key = (user_id, chat_id, message_id)

        loop = asyncio.get_running_loop()
        now = loop.time()

        self._cleanup_old_keys(now)

        last_time = self._last_time.get(key, 0.0)
        time_since = now - last_time

        # 1. Если кулдаун прошёл — пропускаем клик сразу
        if time_since >= self.cooldown:
            self._last_time[key] = now
            return

        # 2. Если кулдаун ещё не прошёл:
        # Проверяем, есть ли уже ожидающий клик в очереди
        if self._has_pending.get(key, False):
            # Лишний спам-клик во время кулдауна — тихо гасим крутилку Telegram и отменяем обработку
            try:
                await query.answer()
            except Exception:
                pass
            raise ApplicationHandlerStop

        # 3. Первый клик в период кулдауна — планируем его выполнение на момент окончания кулдауна
        self._has_pending[key] = True
        remaining = (last_time + self.cooldown) - now

        try:
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_time[key] = loop.time()
        finally:
            self._has_pending[key] = False

        # Клик "нажимается сам после блокировки" и передаётся дальше в group=0


button_anti_flood = ButtonAntiFlood(cooldown=1.0)


async def button_anti_flood_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Middleware для CallbackQueryHandler(group=-1)."""
    await button_anti_flood.check_and_throttle(update, context)


__all__ = ["ButtonAntiFlood", "button_anti_flood", "button_anti_flood_middleware"]
