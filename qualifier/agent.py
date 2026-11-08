"""Core Agent logic: conversation management, LLM interfacing, and entity extraction."""

import os
import re
import json
import logging
from typing import Optional, Dict, Any, Tuple
import httpx

from qualifier.models import (
    DialogState,
    ChatMessage,
    LeadProfile,
    BANTCriteria,
    LeadScoring,
    LeadStatus,
)
from qualifier.prompts import SYSTEM_QUALIFIER_PROMPT, EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


class LeadQualifierAgent:
    """Интеллектуальный агент для квалификации B2B-лидов и подготовки сделок в CRM."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
        
        # Если ключ не задан или явно включен MOCK_MODE, работаем в автономном эвристическом режиме
        env_mock = os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
        self.mock_mode = mock_mode if mock_mode is not None else (env_mock or not self.api_key)

    async def generate_reply(self, session: DialogState, user_input: str) -> str:
        """Генерация следующей реплики диалога."""
        session.messages.append(ChatMessage(role="user", content=user_input))
        session.turn_count += 1

        if self.mock_mode:
            reply = self._mock_generate_reply(session, user_input)
        else:
            try:
                reply = await self._llm_chat(session)
            except Exception as e:
                logger.warning(f"Ошибка вызова LLM: {e}. Переключаюсь на эвристический ответ.")
                reply = self._mock_generate_reply(session, user_input)

        session.messages.append(ChatMessage(role="assistant", content=reply))
        return reply

    async def extract_profile(self, session: DialogState) -> LeadProfile:
        """Извлечение BANT-параметров и скоринга из истории диалога."""
        if self.mock_mode:
            return self._heuristic_extract_profile(session)

        try:
            profile = await self._llm_extract_profile(session)
            return profile
        except Exception as e:
            logger.warning(f"Ошибка LLM-экстракции: {e}. Применяю эвристический парсер.")
            return self._heuristic_extract_profile(session)

    async def process_turn(self, session: DialogState, user_input: str) -> Tuple[str, LeadProfile]:
        """Обработка одного хода диалога: ответ + актуализация профиля."""
        reply = await self.generate_reply(session, user_input)
        profile = await self.extract_profile(session)
        session.profile = profile
        return reply, profile

    # -------------------------------------------------------------------------
    # LLM Interaction
    # -------------------------------------------------------------------------
    async def _llm_chat(self, session: DialogState) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = [{"role": "system", "content": SYSTEM_QUALIFIER_PROMPT}]
        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 400,
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    async def _llm_extract_profile(self, session: DialogState) -> LeadProfile:
        dialog_history = "\n".join([f"{m.role.upper()}: {m.content}" for m in session.messages])
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": f"ИСТОРИЯ ДИАЛОГА:\n{dialog_history}"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            raw_text = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(raw_text)

        bant_dict = parsed.get("bant", {})
        bant = BANTCriteria(
            budget=bant_dict.get("budget"),
            budget_amount=bant_dict.get("budget_amount"),
            authority=bant_dict.get("authority"),
            need=bant_dict.get("need"),
            timeline=bant_dict.get("timeline"),
        )
        scoring = LeadScoring(
            score=parsed.get("score", 50),
            status=LeadStatus(parsed.get("status", "WARM")),
            confidence=float(parsed.get("confidence", 0.8)),
            reasons=parsed.get("reasons", []),
        )

        return LeadProfile(
            client_name=parsed.get("client_name"),
            company_name=parsed.get("company_name"),
            phone=parsed.get("phone"),
            email=parsed.get("email"),
            bant=bant,
            scoring=scoring,
            summary=parsed.get("summary", ""),
            next_step=parsed.get("next_step", "Связаться с клиентом"),
        )

    # -------------------------------------------------------------------------
    # Автономный эвристический режим (без API-ключей для тестов и оффлайн-демо)
    # -------------------------------------------------------------------------
    def _mock_generate_reply(self, session: DialogState, user_input: str) -> str:
        text = user_input.lower()
        turn = session.turn_count

        if turn == 1:
            return (
                "Добрый день! Спасибо за обращение. Подскажите, пожалуйста, какой объект или задачу "
                "вы планируете реализовать и в каком регионе?"
            )
        elif turn == 2:
            return (
                "Отлично, задачу зафиксировал. Подскажите ориентировочные сроки: когда планируете поставку "
                "или монтаж, и есть ли уже готовый проект или спецификация?"
            )
        elif turn == 3:
            return (
                "Принято. Для корректного предварительного расчёта и подготовки коммерческого предложения, "
                "уточните, пожалуйста, выделен ли ориентировочный бюджет и как к вам обращаться (имя и телефон/Telegram)?"
            )
        else:
            return (
                "Благодарю за подробную информацию! Все данные внесены в систему. Наш ведущий специалист "
                "подготовит расчёт с учётом ваших параметров и свяжется с вами в течение 15 минут."
            )

    def _heuristic_extract_profile(self, session: DialogState) -> LeadProfile:
        full_text = " ".join([m.content for m in session.messages])
        
        # Поиск контактов через regex
        phone_match = re.search(r"(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", full_text)
        email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", full_text)
        
        # Определение потребности
        need = None
        lower = full_text.lower()
        if "каркас" in lower or "металл" in lower or "лстк" in lower:
            need = "Металлоконструкции / ЛСТК"
        elif "фасад" in lower or "кассет" in lower:
            need = "Навесная фасадная система"
        elif "септик" in lower or "очистн" in lower:
            need = "Локальные очистные сооружения / септик"
        elif "компрессор" in lower or "турбин" in lower or "ремонт" in lower:
            need = "Ремонт и модернизация промышленного оборудования"
        else:
            need = "Поставка и монтаж продукции"

        # Определение сроков
        timeline = "В течение 1-2 месяцев"
        if "срочно" in lower or "недел" in lower or "горит" in lower:
            timeline = "Срочно (до 2 недель)"
        elif "весна" in lower or "лето" in lower or "квартал" in lower:
            timeline = "Плановый срок (1-3 месяца)"

        # Определение бюджета
        budget = "Требуется предварительный расчёт"
        budget_amt = None
        amt_match = re.search(r"(\d+([.,]\d+)?)\s*(млн|тыс|руб)", lower)
        if amt_match:
            raw_val = amt_match.group(1).replace(",", ".")
            unit = amt_match.group(3)
            budget = f"{raw_val} {unit}"
            val = float(raw_val)
            if unit == "млн":
                budget_amt = val * 1_000_000
            elif unit == "тыс":
                budget_amt = val * 1_000
            else:
                budget_amt = val

        # Определение роли
        authority = "Представитель заказчика"
        if "директор" in lower or "гендир" in lower or "собственник" in lower:
            authority = "Генеральный директор / Собственник (ЛПР)"
        elif "снабжен" in lower or "закуп" in lower:
            authority = "Служба снабжения"
        elif "инженер" in lower or "прораб" in lower:
            authority = "Технический специалист / Прораб"

        # Расчет баллов
        score = 30
        reasons = ["Зафиксирована конкретная потребность"]
        if phone_match or email_match:
            score += 25
            reasons.append("Оставлены прямые контактные данные")
        if "срочно" in lower or "недел" in lower:
            score += 25
            reasons.append("Высокая срочность реализации сделки")
        if budget_amt or "млн" in lower:
            score += 20
            reasons.append("Подтвержден достаточный бюджет")

        status = LeadStatus.HOT if score >= 75 else (LeadStatus.WARM if score >= 45 else LeadStatus.COLD)

        return LeadProfile(
            client_name="Клиент из формы/диалога",
            phone=phone_match.group(0) if phone_match else None,
            email=email_match.group(0) if email_match else None,
            bant=BANTCriteria(
                need=need,
                timeline=timeline,
                budget=budget,
                budget_amount=budget_amt,
                authority=authority,
            ),
            scoring=LeadScoring(
                score=min(score, 100),
                status=status,
                confidence=0.85,
                reasons=reasons,
            ),
            summary=f"Запрос на {need}, ориентир по срокам: {timeline}. Бюджет: {budget}.",
            next_step="Связаться для презентации и согласования ТЗ",
        )
