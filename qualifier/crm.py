"""CRM integration client with pipeline routing by project direction."""

import os
import logging
from typing import Dict, Any, Optional
import httpx

from qualifier.models import LeadProfile, SalesProject

logger = logging.getLogger(__name__)


class AmoCRMClient:
    """Клиент интеграции с amoCRM (Kommo) с автомаршрутизацией по направлениям продаж."""

    PIPELINE_MAP = {
        SalesProject.ANGARS: {"id": 101, "name": "Воронка: Проект «Ангары и Здания»"},
        SalesProject.FASADY_KROVLYA: {"id": 102, "name": "Воронка: Проект «Кровли и Фасады»"},
        SalesProject.GAZOBETON: {"id": 103, "name": "Воронка: Проект «Газобетон»"},
        SalesProject.COMPLEX: {"id": 104, "name": "Воронка: Комплексные объекты"},
        SalesProject.UNCERTAIN: {"id": 100, "name": "Общая воронка входящих лидов"},
    }

    def __init__(
        self,
        subdomain: Optional[str] = None,
        access_token: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.subdomain = subdomain or os.getenv("AMOCRM_SUBDOMAIN", "")
        self.access_token = access_token or os.getenv("AMOCRM_ACCESS_TOKEN", "")
        
        env_mock = os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
        self.mock_mode = mock_mode if mock_mode is not None else (env_mock or not self.access_token)

    async def push_lead(self, profile: LeadProfile) -> Dict[str, Any]:
        """Создает сделку, направляя её в соответствующую проектную воронку."""
        pipeline_info = self.PIPELINE_MAP.get(profile.project, self.PIPELINE_MAP[SalesProject.UNCERTAIN])

        if self.mock_mode:
            return self._mock_push(profile, pipeline_info)

        base_url = f"https://{self.subdomain}.amocrm.ru/api/v4"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        # 1. Создание контакта
        contact_payload = [
            {
                "name": profile.client_name or "Новый клиент",
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

            # 2. Создание сделки в целевой воронке направления
            deal_name = f"[{profile.project.value.split(':')[1].strip() if ':' in profile.project.value else profile.project.value}] {profile.bant.need}"
            deal_payload = [
                {
                    "name": deal_name,
                    "price": int(profile.bant.budget_amount or 0),
                    "pipeline_id": pipeline_info["id"],
                    "_embedded": {
                        "contacts": [{"id": contact_id}],
                    },
                    "custom_fields_values": [
                        {
                            "field_name": "Направление продаж",
                            "values": [{"value": profile.project.value}],
                        },
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

            # 3. Назначение задачи инженеру направления
            task_payload = [
                {
                    "task_type_id": 1,
                    "text": f"🔥 {profile.next_step} (Сделка: {deal_name})",
                    "complete_till": 900,  # 15 минут
                    "entity_id": deal_id,
                    "entity_type": "leads",
                }
            ]
            await client.post(f"{base_url}/tasks", headers=headers, json=task_payload)

            return {
                "status": "success",
                "crm": "amoCRM",
                "pipeline": pipeline_info["name"],
                "deal_id": deal_id,
                "contact_id": contact_id,
                "deal_url": f"https://{self.subdomain}.amocrm.ru/leads/detail/{deal_id}",
            }

    def _mock_push(self, profile: LeadProfile, pipeline_info: Dict[str, Any]) -> Dict[str, Any]:
        """Имитация автомаршрутизации сделки по проектным воронкам."""
        mock_deal_id = 98745210
        mock_contact_id = 4512399
        subdomain = self.subdomain or "demo-b2b"

        return {
            "status": "success",
            "crm": "amoCRM (Mock Mode)",
            "pipeline": pipeline_info["name"],
            "deal_id": mock_deal_id,
            "contact_id": mock_contact_id,
            "deal_url": f"https://{subdomain}.amocrm.ru/leads/detail/{mock_deal_id}",
            "created_entities": {
                "deal_name": f"[{profile.project.value}] {profile.bant.need}",
                "target_pipeline": pipeline_info["name"],
                "price": profile.bant.budget_amount or 0,
                "score_badge": f"{profile.scoring.score}/100 [{profile.scoring.status.value}]",
                "task": f"Связаться ведущему инженеру направления: {profile.next_step}",
            },
        }
