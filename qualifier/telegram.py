"""Telegram notification builder and dispatcher for qualified leads."""

import os
import logging
from typing import Dict, Any, Optional
import httpx

from qualifier.models import LeadProfile, LeadStatus

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Отправка мгновенных карточек лидов в закрытые каналы / чаты менеджеров."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        
        env_mock = os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
        self.mock_mode = mock_mode if mock_mode is not None else (env_mock or not self.bot_token)

    def format_lead_card(self, profile: LeadProfile, deal_url: Optional[str] = None) -> str:
        """Форматирует красивую карточку лида для Telegram."""
        status_icons = {
            LeadStatus.HOT: "🔥 <b>ГОРЯЧИЙ ЛИД (BANT 75+)</b>",
            LeadStatus.WARM: "⚡️ <b>ТЁПЛЫЙ ЛИД</b>",
            LeadStatus.COLD: "❄️ <b>ХОЛОДНЫЙ ЛИД</b>",
            LeadStatus.JUNK: "🗑 <b>НЕЦЕЛЕВОЙ ЗАПРОС</b>",
        }
        status_header = status_icons.get(profile.scoring.status, "📋 <b>НОВЫЙ ЛИД</b>")

        phone = profile.phone or "не указан"
        client = profile.client_name or "Контакт не представился"
        company = f" ({profile.company_name})" if profile.company_name else ""

        lines = [
            f"{status_header}",
            f"━━━━━━━━━━━━━━━━━━",
            f"👤 <b>Клиент:</b> {client}{company}",
            f"📞 <b>Телефон:</b> <code>{phone}</code>",
        ]
        if profile.email:
            lines.append(f"✉️ <b>Email:</b> <code>{profile.email}</code>")

        lines.extend([
            f"",
            f"🎯 <b>Потребность (Need):</b> {profile.bant.need or 'Уточняется'}",
            f"⏱ <b>Сроки (Timeline):</b> {profile.bant.timeline or 'Не указаны'}",
            f"💰 <b>Бюджет (Budget):</b> {profile.bant.budget or 'Не обсуждался'}",
            f"👑 <b>Роль (Authority):</b> {profile.bant.authority or 'Представитель'}",
            f"",
            f"📊 <b>Скоринг:</b> <code>{profile.scoring.score}/100</code>",
            f"💡 <b>Саммари:</b> {profile.summary}",
            f"👉 <b>Следующий шаг:</b> {profile.next_step}",
        ])

        if deal_url:
            lines.extend(["", f"🔗 <a href='{deal_url}'>Открыть сделку в amoCRM</a>"])

        return "\n".join(lines)

    async def send_lead_alert(self, profile: LeadProfile, deal_url: Optional[str] = None) -> Dict[str, Any]:
        """Отправляет уведомление в Telegram."""
        text = self.format_lead_card(profile, deal_url)

        if self.mock_mode:
            logger.info("TelegramNotifier [MOCK MODE]: Уведомление сформировано успешно.")
            return {"status": "success", "mode": "mock", "formatted_card": text}

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return {"status": "success", "mode": "live", "telegram_response": resp.json()}

