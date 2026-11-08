"""CRM integration client (amoCRM & Bitrix24) with full mock support."""

import os
import logging
from typing import Dict, Any, Optional
import httpx

from qualifier.models import LeadProfile, LeadStatus

logger = logging.getLogger(__name__)


class AmoCRMClient:
    """Клиент интеграции с amoCRM (Kommo)."""

    def __init__(
        self,
        subdomain: Optional[str] = None,
        access_token: Optional[str] = None,
        pipeline_id: Optional[int] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.subdomain = subdomain or os.getenv("AMOCRM_SUBDOMAIN", "")
        self.access_token = access_token or os.getenv("AMOCRM_ACCESS_TOKEN", "")
        self.pipeline_id = pipeline_id or int(os.getenv("AMOCRM_PIPELINE_ID", "1001"))
        
        env_mock = os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
        self.mock_mode = mock_mode if mock_mode is not None else (env_mock or not self.access_token)

    async def push_lead(self, profile: LeadProfile) -> Dict[str, Any]:
        """Создает сделку, контакт и задачу в amoCRM."""
        if self.mock_mode:
            return self._mock_push(profile)

        base_url = f"https://{self.subdomain}.amocrm.ru/api/v4"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        # 1. Формирование контакта
        contact_payload = [
            {
                "name": profile.client_name or "Новый клиент (AI-квалификация)",
                "custom_fields_values": [],
            }
        ]
        if profile.phone:
            contact_payload[0]["custom_fields_values"].append({
                "field_code": "PHONE",
                "values": [{"value": profile.phone, "enum_code": "WORK"}],
            })
        if profile.email:
            contact_payload[0]["custom_fields_values"].append({
                "field_code": "EMAIL",
                "values": [{"value": profile.email, "enum_code": "WORK"}],
            })

        async with httpx.AsyncClient(timeout=15.0) as client:
            contact_resp = await client.post(f"{base_url}/contacts", headers=headers, json=contact_payload)
            contact_resp.raise_for_status()
            contact_id = contact_resp.json()["_embedded"]["contacts"][0]["id"]

            # 2. Формирование сделки
            deal_name = f"{profile.bant.need or 'Заявка'} — {profile.client_name or 'Клиент'}"
            deal_payload = [
                {
                    "name": deal_name,
                    "price": int(profile.bant.budget_amount or 0),
                    "pipeline_id": self.pipeline_id,
                    "_embedded": {
                        "contacts": [{"id": contact_id}],
                    },
                    "custom_fields_values": [
                        {
                            "field_name": "AI Скоринг",
                            "values": [{"value": f"{profile.scoring.score}/100 ({profile.scoring.status.value})"}],
                        },
                        {
                            "field_name": "AI Саммари",
                            "values": [{"value": profile.summary}],
                        },
                        {
                            "field_name": "Сроки",
                            "values": [{"value": profile.bant.timeline or "Не указано"}],
                        },
                    ],
                }
            ]

            deal_resp = await client.post(f"{base_url}/leads", headers=headers, json=deal_payload)
            deal_resp.raise_for_status()
            deal_id = deal_resp.json()["_embedded"]["leads"][0]["id"]

            # 3. Постановка задачи менеджеру
            task_payload = [
                {
                    "task_type_id": 1,  # Связаться
                    "text": f"🔥 Обработать квалифицированный лид: {profile.next_step}",
                    "complete_till": 900,  # +15 минут
                    "entity_id": deal_id,
                    "entity_type": "leads",
                }
            ]
            await client.post(f"{base_url}/tasks", headers=headers, json=task_payload)

            return {
                "status": "success",
                "crm": "amoCRM",
                "deal_id": deal_id,
                "contact_id": contact_id,
                "deal_url": f"https://{self.subdomain}.amocrm.ru/leads/detail/{deal_id}",
            }

    def _mock_push(self, profile: LeadProfile) -> Dict[str, Any]:
        """Имитация успешной отправки в amoCRM для демонстраций и тестов."""
        mock_deal_id = 98745210
        mock_contact_id = 4512399
        subdomain = self.subdomain or "demo-b2b"

        return {
            "status": "success",
            "crm": "amoCRM (Mock Mode)",
            "deal_id": mock_deal_id,
            "contact_id": mock_contact_id,
            "deal_url": f"https://{subdomain}.amocrm.ru/leads/detail/{mock_deal_id}",
            "created_entities": {
                "deal_name": f"{profile.bant.need or 'Заявка'} — {profile.client_name or 'Клиент'}",
                "price": profile.bant.budget_amount or 0,
                "score_badge": f"{profile.scoring.score}/100 [{profile.scoring.status.value}]",
                "task": f"Связаться в течение 15 минут ({profile.next_step})",
            },
        }
