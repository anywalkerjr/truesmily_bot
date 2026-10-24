"""
Модуль защиты от флуда и ограничения частоты запросов к Telegram Bot API (Flood Control & Rate Limiting).

Реализует BaseRateLimiter для python-telegram-bot (v20+).
Автоматически перехватывает запросы приложения к Telegram API.

Функционал:
  1. Защита от RetryAfter: автоматический перехват ошибки Flood control exceeded,
     извлечение retry_after, ожидание и автоматический повтор запроса (до max_retries раз).
  2. Превентивное сглаживание частоты (Throttling):
     - Глобальный лимит (макс. 25 запросов/сек, при лимите Telegram 30/сек).
     - Лимит на новые сообщения в группах (sendMessage, sendPhoto и т.д. не более 18 в минуту).
     - Инлайн-кнопки (editMessageText, answerCallbackQuery) НЕ искусственно задерживаются,
       чтобы не тормозить игры с кнопками (мины, блэкджек, башня, кейсы).
  3. Ошибки валидации (BadRequest: Message is not modified, Query is too old и т.д.)
     НЕ перехватываются как сетевые ошибки и НЕ повторяются повторно.
"""

import asyncio
import logging
from collections import deque
from datetime import timedelta
from typing import Any, Callable, Coroutine, Dict, Optional, Union

from telegram.error import RetryAfter
from telegram.ext import BaseRateLimiter

logger = logging.getLogger(__name__)

# Эндпоинты отправки новых сообщений в чат (на них действуют лимиты Telegram для групп)
NEW_MESSAGE_ENDPOINTS = {
    "sendMessage",
    "sendPhoto",
    "sendVideo",
    "sendAnimation",
    "sendAudio",
    "sendDocument",
    "sendVoice",
    "sendDice",
    "sendSticker",
    "sendMediaGroup",
}


def extract_retry_after(error: RetryAfter) -> float:
    """Извлекает количество секунд ожидания из RetryAfter (поддерживает timedelta и float/int)."""
    if isinstance(error.retry_after, timedelta):
        return error.retry_after.total_seconds()
    try:
        return float(error.retry_after)
    except (TypeError, ValueError):
        return 5.0


class FloodControlLimiter(BaseRateLimiter[int]):
    """
    Кастомный ограничитель частоты запросов с защитой от флуда и автоматическим retry.
    """

    def __init__(
        self,
        overall_max_rate: int = 25,
        overall_period: float = 1.0,
        group_max_rate: int = 18,
        group_period: float = 60.0,
        private_min_spacing: float = 0.05,
        group_min_spacing: float = 0.3,
        max_retries: int = 5,
    ) -> None:
        self.overall_max_rate = overall_max_rate
        self.overall_period = overall_period
        self.group_max_rate = group_max_rate
        self.group_period = group_period
        self.private_min_spacing = private_min_spacing
        self.group_min_spacing = group_min_spacing
        self.max_retries = max_retries

        self._global_timestamps: deque = deque()
        self._global_lock: Optional[asyncio.Lock] = None
        self._chat_last_time: Dict[Any, float] = {}
        self._chat_timestamps: Dict[Any, deque] = {}
        self._chat_flood_until: Dict[Any, float] = {}
        self._global_flood_until: float = 0.0

    async def initialize(self) -> None:
        """Инициализация ресурсов при старте бота."""
        self._global_lock = asyncio.Lock()

    async def shutdown(self) -> None:
        """Очистка ресурсов при остановке бота."""
        self._chat_last_time.clear()
        self._chat_timestamps.clear()
        self._chat_flood_until.clear()
        self._global_timestamps.clear()

    async def _throttle(self, chat_id: Any, endpoint: str) -> None:
        """
        Превентивное сглаживание частоты запросов перед отправкой в Telegram.
        """
        loop = asyncio.get_running_loop()

        # 1. Проверяем, действует ли глобальный флуд-бан Telegram
        now = loop.time()
        if self._global_flood_until > now:
            wait_time = min(self._global_flood_until - now, 2.0)
            await asyncio.sleep(wait_time)

        # 2. Проверяем, действует ли флуд-бан Telegram для конкретного чата
        if chat_id is not None:
            chat_flood = self._chat_flood_until.get(chat_id, 0.0)
            now = loop.time()
            if chat_flood > now:
                wait_time = min(chat_flood - now, 2.0)
                await asyncio.sleep(wait_time)

        # 3. Глобальный скользящий лимит (не более overall_max_rate в overall_period)
        if self._global_lock is not None:
            async with self._global_lock:
                now = loop.time()
                while (
                    self._global_timestamps
                    and self._global_timestamps[0] <= now - self.overall_period
                ):
                    self._global_timestamps.popleft()

                if len(self._global_timestamps) >= self.overall_max_rate:
                    oldest = self._global_timestamps[0]
                    sleep_time = (oldest + self.overall_period) - now
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                self._global_timestamps.append(loop.time())

        # 4. Початовое сглаживание: ТОЛЬКО для отправки НОВЫХ сообщений в чат (sendMessage, sendPhoto и т.д.)
        # Редактирование сообщений и ответы на кнопки (editMessageText, answerCallbackQuery)
        # не спамят чат и должны выполняться без искусственных задержек!
        if chat_id is not None and endpoint in NEW_MESSAGE_ENDPOINTS:
            is_group = isinstance(chat_id, int) and chat_id < 0

            if is_group:
                if chat_id not in self._chat_timestamps:
                    self._chat_timestamps[chat_id] = deque()
                now = loop.time()
                deq = self._chat_timestamps[chat_id]
                while deq and deq[0] <= now - self.group_period:
                    deq.popleft()

                if len(deq) >= self.group_max_rate:
                    oldest = deq[0]
                    sleep_time = (oldest + self.group_period) - now
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                deq.append(loop.time())

                min_spacing = self.group_min_spacing
            else:
                min_spacing = self.private_min_spacing

            last_time = self._chat_last_time.get(chat_id, 0.0)
            now = loop.time()
            diff = now - last_time
            if diff < min_spacing:
                await asyncio.sleep(min_spacing - diff)
            self._chat_last_time[chat_id] = loop.time()

    async def _execute_with_retry(
        self,
        callback: Callable[..., Coroutine[Any, Any, Any]],
        args: Any,
        kwargs: Dict[str, Any],
        endpoint: str,
        chat_id: Any,
    ) -> Any:
        """
        Выполняет запрос. Перехватывает и повторяет ТОЛЬКО RetryAfter!
        Ошибки BadRequest (например, 'Message is not modified', 'Query is too old')
        НЕ повторяются и возвращаются вызывающему коду сразу без задержек.
        """
        for attempt in range(self.max_retries + 1):
            await self._throttle(chat_id, endpoint)
            try:
                return await callback(*args, **kwargs)
            except RetryAfter as e:
                delay = extract_retry_after(e)
                # Если Telegram требует ждать больше 2.0 секунд (например, 28 секунд флуд-бана):
                # НЕ усыпляем бота и НЕ блокируем очередь запросов!
                # Сразу логируем и прерываем запрос, чтобы бот не уходил в долгий фриз.
                if delay > 2.0:
                    logger.warning(
                        "[FloodControl] RetryAfter на %s (chat_id=%s): задержка слишком велика (%.1f сек), запрос отклонён во избежание блокировки",
                        endpoint,
                        chat_id,
                        delay,
                    )
                    raise

                wait_time = delay + 0.1
                loop = asyncio.get_running_loop()

                if chat_id is not None:
                    self._chat_flood_until[chat_id] = loop.time() + wait_time

                logger.warning(
                    "[FloodControl] Короткий RetryAfter на %s (chat_id=%s): ожидание %.2f сек (попытка %d/%d)",
                    endpoint,
                    chat_id,
                    delay,
                    attempt + 1,
                    self.max_retries,
                )

                if attempt >= self.max_retries:
                    logger.error(
                        "[FloodControl] Исчерпаны попытки (%d) для %s (chat_id=%s)",
                        self.max_retries,
                        endpoint,
                        chat_id,
                    )
                    raise

                await asyncio.sleep(wait_time)

    async def process_request(
        self,
        callback: Callable[..., Coroutine[Any, Any, Union[bool, Dict[str, Any], list]]],
        args: Any,
        kwargs: Dict[str, Any],
        endpoint: str,
        data: Dict[str, Any],
        rate_limit_args: Optional[int],
    ) -> Union[bool, Dict[str, Any], list]:
        """
        Точка входа python-telegram-bot для каждого запроса к Bot API.
        """
        chat_id = None
        if isinstance(data, dict):
            chat_id = data.get("chat_id") or data.get("inline_message_id")

        return await self._execute_with_retry(
            callback, args, kwargs, endpoint, chat_id
        )


__all__ = ["FloodControlLimiter", "extract_retry_after"]
