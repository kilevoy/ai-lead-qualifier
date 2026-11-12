"""Telegram notification builder with project direction tagging."""

import os
import html
import logging
from typing import Dict, Any, Optional
import httpx

from qualifier.models import LeadProfile, LeadStatus, SalesProject

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Отправка карточек лидов с маршрутизацией по направлениям продаж."""

    PROJECT_ICONS = {
        SalesProject.ANGARS: "🏭 <b>НАПРАВЛЕНИЕ: АНГАРЫ И ЗДАНИЯ</b>",
        SalesProject.FASADY_KROVLYA: "🏢 <b>НАПРАВЛЕНИЕ: КРОВЛИ И ФАСАДЫ</b>",
        SalesProject.GAZOBETON: "🧱 <b>НАПРАВЛЕНИЕ: АВТОКЛАВНЫЙ ГАЗОБЕТОН</b>",
        SalesProject.COMPLEX: "🏗 <b>КОМПЛЕКСНЫЙ ПРОЕКТ</b>",
        SalesProject.UNCERTAIN: "📋 <b>ОБЩАЯ ЗАЯВКА</b>",
    }

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
        """Форматирует карточку лида для Telegram с проектом и BANT-параметрами."""
        status_icons = {
            LeadStatus.HOT: "🔥 <b>ГОРЯЧИЙ ЛИД (75+)</b>",
            LeadStatus.WARM: "⚡️ <b>ТЁПЛЫЙ ЛИД</b>",
            LeadStatus.COLD: "❄️ <b>ХОЛОДНЫЙ ЛИД</b>",
            LeadStatus.JUNK: "🗑 <b>НЕЦЕЛЕВОЙ</b>",
        }
        status_header = status_icons.get(profile.scoring.status, "📋 <b>НОВЫЙ ЛИД</b>")
        project_header = self.PROJECT_ICONS.get(profile.project, "📋 <b>НАПРАВЛЕНИЕ НЕ ОПРЕДЕЛЕНО</b>")

        e = lambda v: html.escape(str(v))  # данные клиента — недоверенный ввод, а Telegram разбирает HTML
        phone = e(profile.phone or "не указан")
        client = e(profile.client_name or "Контакт не представился")
        company = f" ({e(profile.company_name)})" if profile.company_name else ""

        lines = [
            f"{status_header} | {project_header}",
            f"━━━━━━━━━━━━━━━━━━",
            f"👤 <b>Клиент:</b> {client}{company}",
            f"📞 <b>Телефон:</b> <code>{phone}</code>",
        ]
        if profile.email:
            lines.append(f"✉️ <b>Email:</b> <code>{e(profile.email)}</code>")

        lines.extend([
            f"",
            f"🎯 <b>Потребность:</b> {e(profile.bant.need or 'Уточняется')}",
        ])

        # Специфические технические метрики
        if profile.specs.area_sqm:
            lines.append(f"📐 <b>Площадь:</b> {profile.specs.area_sqm:.0f} м²")
        if profile.specs.volume_cbm:
            lines.append(f"📦 <b>Объём газобетона:</b> {profile.specs.volume_cbm:.0f} м³ (марка {profile.specs.density or 'D500'})")
        if profile.specs.cassette_type:
            lines.append(f"🧩 <b>Тип кассет:</b> {e(profile.specs.cassette_type)}")

        lines.extend([
            f"⏱ <b>Сроки:</b> {e(profile.bant.timeline or 'Не указаны')}",
            f"💰 <b>Бюджет:</b> {e(profile.bant.budget or 'По расчёту')}",
            f"👑 <b>ЛПР:</b> {e(profile.bant.authority or 'Представитель')}",
            f"",
            f"📊 <b>Скоринг:</b> <code>{profile.scoring.score}/100</code>",
            f"💡 <b>Саммари:</b> {e(profile.summary)}",
            f"👉 <b>Следующий шаг:</b> {e(profile.next_step)}",
        ])

        if deal_url:
            lines.extend(["", f"🔗 <a href='{deal_url}'>Открыть в CRM (целевая воронка направления)</a>"])

        return "\n".join(lines)

    async def send_lead_alert(self, profile: LeadProfile, deal_url: Optional[str] = None) -> Dict[str, Any]:
        """Отправляет уведомление в Telegram."""
        text = self.format_lead_card(profile, deal_url)

        if self.mock_mode:
            logger.info("TelegramNotifier [MOCK MODE]: Алерт направления сформирован успешно.")
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
