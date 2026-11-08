"""Core Agent logic: conversation management, project direction detection, and BANT extraction."""

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
    TechnicalSpecs,
    LeadScoring,
    LeadStatus,
    SalesProject,
)
from qualifier.prompts import SYSTEM_QUALIFIER_PROMPT, EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


class LeadQualifierAgent:
    """Интеллектуальный агент для квалификации B2B-лидов по проектам (Ангары, Фасады, Газобетон)."""

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
        
        env_mock = os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
        self.mock_mode = mock_mode if mock_mode is not None else (env_mock or not self.api_key)

    async def generate_reply(self, session: DialogState, user_input: str) -> str:
        """Генерация следующей реплики диалога с учётом направления продаж."""
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
        """Извлечение BANT-параметров, проекта и скоринга."""
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
            "temperature": 0.25,
            "max_tokens": 400,
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

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
            parsed = json.loads(resp.json()["choices"][0]["message"]["content"])

        project_str = parsed.get("project", SalesProject.UNCERTAIN.value)
        try:
            project_enum = SalesProject(project_str)
        except ValueError:
            project_enum = SalesProject.UNCERTAIN

        bant_dict = parsed.get("bant", {})
        bant = BANTCriteria(
            budget=bant_dict.get("budget"),
            budget_amount=bant_dict.get("budget_amount"),
            authority=bant_dict.get("authority"),
            need=bant_dict.get("need"),
            timeline=bant_dict.get("timeline"),
        )
        specs_dict = parsed.get("specs", {})
        specs = TechnicalSpecs(
            area_sqm=specs_dict.get("area_sqm"),
            volume_cbm=specs_dict.get("volume_cbm"),
            density=specs_dict.get("density"),
            building_purpose=specs_dict.get("building_purpose"),
            cassette_type=specs_dict.get("cassette_type"),
            delivery_city=specs_dict.get("delivery_city"),
        )
        scoring = LeadScoring(
            score=parsed.get("score", 50),
            status=LeadStatus(parsed.get("status", "WARM")),
            confidence=float(parsed.get("confidence", 0.85)),
            reasons=parsed.get("reasons", []),
        )

        return LeadProfile(
            project=project_enum,
            client_name=parsed.get("client_name"),
            company_name=parsed.get("company_name"),
            phone=parsed.get("phone"),
            email=parsed.get("email"),
            bant=bant,
            specs=specs,
            scoring=scoring,
            summary=parsed.get("summary", ""),
            next_step=parsed.get("next_step", "Связаться с клиентом"),
        )

    # -------------------------------------------------------------------------
    # Автономный эвристический режим (с распознаванием проектов ИНСИ)
    # -------------------------------------------------------------------------
    def _detect_project(self, text: str) -> Tuple[SalesProject, TechnicalSpecs]:
        lower = text.lower()
        has_angar = any(w in lower for w in ["ангар", "склад", "лстк", "каркас", "быстровозводим", "бвз", "ферм"])
        has_fasad = any(w in lower for w in ["фасад", "кассет", "кф-", "кф1", "кф2", "сайдинг", "кровл", "профлист", "сэндвич"])
        has_gazobeton = any(w in lower for w in ["газобетон", "газоблок", "блок", "d400", "d500", "d600", "куб", "м3", "м³"])

        specs = TechnicalSpecs()

        # Поиск площади (м²)
        area_match = re.search(r"(\d+[\s\d]*)\s*(кв\.?\s*м|м2|м²)", lower)
        if area_match:
            specs.area_sqm = float(re.sub(r"[^\d.]", "", area_match.group(1).replace(" ", "")))

        # Поиск кубатуры (м³)
        cbm_match = re.search(r"(\d+[\s\d]*)\s*(куб|м3|м³)", lower)
        if cbm_match:
            specs.volume_cbm = float(re.sub(r"[^\d.]", "", cbm_match.group(1).replace(" ", "")))

        # Поиск плотности газобетона
        density_match = re.search(r"(d\s*400|d\s*500|d\s*600|д\s*400|д\s*500|д\s*600)", lower)
        if density_match:
            specs.density = density_match.group(0).upper().replace(" ", "").replace("Д", "D")

        # Поиск типа кассет
        cassette_match = re.search(r"(кф[- ]?[1-4])", lower)
        if cassette_match:
            specs.cassette_type = cassette_match.group(0).upper()

        # Классификация направления
        active_projects = sum([has_angar, has_fasad, has_gazobeton])
        if active_projects > 1:
            return SalesProject.COMPLEX, specs
        elif has_angar:
            specs.building_purpose = "Склад / Промышленное здание"
            return SalesProject.ANGARS, specs
        elif has_fasad:
            return SalesProject.FASADY_KROVLYA, specs
        elif has_gazobeton:
            return SalesProject.GAZOBETON, specs
        return SalesProject.UNCERTAIN, specs

    def _mock_generate_reply(self, session: DialogState, user_input: str) -> str:
        project, specs = self._detect_project(" ".join([m.content for m in session.messages]))
        turn = session.turn_count

        if turn == 1:
            if project == SalesProject.ANGARS:
                return (
                    "Здравствуйте! Направление «Ангары и быстровозводимые здания». Зафиксировал интерес к металлокаркасу. "
                    "Подскажите ориентировочные габариты (площадь в м², высоту в коньке), планируется тёплый или холодный контур?"
                )
            elif project == SalesProject.FASADY_KROVLYA:
                return (
                    "Здравствуйте! Направление «Кровли и фасадные системы». Зафиксировал запрос. "
                    "Уточните ориентировочную площадь фасада/кровли (в м²), интересуют фасадные кассеты (КФ), сайдинг или сэндвич-панели?"
                )
            elif project == SalesProject.GAZOBETON:
                return (
                    "Здравствуйте! Направление «Автоклавный газобетон». "
                    "Подскажите необходимый объем (м³), какую плотность рассматриваете (D400 для тепла или D500 для несущих стен) и куда планируется доставка?"
                )
            else:
                return (
                    "Добрый день! Спасибо за обращение. Подскажите, какая продукция вас интересует: "
                    "быстровозводимые ангары, фасадные системы/кровля или автоклавный газобетон?"
                )
        elif turn == 2:
            return (
                "Отлично, технические параметры зафиксировал. Подскажите ориентировочные сроки поставки/монтажа "
                "и есть ли уже готовый проект или спецификация?"
            )
        elif turn == 3:
            return (
                "Принято. Для подготовки предварительного расчёта и коммерческого предложения, "
                "уточните, пожалуйста, выделен ли ориентировочный бюджет и контактные данные (имя, телефон/Telegram)?"
            )
        else:
            return (
                "Благодарю за подробную информацию! Данные переданы ведущему инженеру направления. "
                "Расчёт спецификации будет подготовлен и отправлен вам в течение 15 минут."
            )

    def _heuristic_extract_profile(self, session: DialogState) -> LeadProfile:
        full_text = " ".join([m.content for m in session.messages])
        lower = full_text.lower()
        
        project, specs = self._detect_project(full_text)

        # Контакты
        phone_match = re.search(r"(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", full_text)
        email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", full_text)

        # Потребность (Need)
        need = "Поставка строительной продукции"
        if project == SalesProject.ANGARS:
            area = f" {specs.area_sqm:.0f} м²" if specs.area_sqm else ""
            need = f"Быстровозводимый ангар / склад{area} (ЛСТК)"
        elif project == SalesProject.FASADY_KROVLYA:
            area = f" {specs.area_sqm:.0f} м²" if specs.area_sqm else ""
            cass = f" ({specs.cassette_type})" if specs.cassette_type else ""
            need = f"Фасадная система{cass}{area}"
        elif project == SalesProject.GAZOBETON:
            vol = f" {specs.volume_cbm:.0f} м³" if specs.volume_cbm else ""
            den = f" {specs.density}" if specs.density else ""
            need = f"Автоклавный газобетон{den}{vol}"
        elif project == SalesProject.COMPLEX:
            need = "Комплексная поставка (Каркас + Фасады + Блоки)"

        # Сроки (Timeline)
        timeline = "В течение 1-2 месяцев"
        if any(w in lower for w in ["срочно", "недел", "горит", "месяц"]):
            timeline = "Срочно (до 30 дней)"
        elif any(w in lower for w in ["весна", "лето", "квартал"]):
            timeline = "Плановый срок (1-3 месяца)"

        # Бюджет (Budget)
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

        # ЛПР (Authority)
        authority = "Представитель заказчика"
        if any(w in lower for w in ["директор", "гендир", "собственник"]):
            authority = "Генеральный директор / Собственник (ЛПР)"
        elif any(w in lower for w in ["снабжен", "закуп"]):
            authority = "Служба снабжения"
        elif any(w in lower for w in ["прораб", "инженер", "механик"]):
            authority = "Технический специалист / Прораб"

        # Скоринг
        score = 25
        reasons = []
        if project != SalesProject.UNCERTAIN:
            score += 25
            reasons.append(f"Чётко определено коммерческое направление ({project.value})")
        if phone_match or email_match:
            score += 25
            reasons.append("Оставлены прямые контактные данные")
        if specs.area_sqm or specs.volume_cbm:
            score += 15
            reasons.append("Указаны точные физические объёмы (м² или м³)")
        if budget_amt:
            score += 10
            reasons.append("Определены бюджетные ориентиры")

        status = LeadStatus.HOT if score >= 75 else (LeadStatus.WARM if score >= 45 else LeadStatus.COLD)

        return LeadProfile(
            project=project,
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
            specs=specs,
            scoring=LeadScoring(
                score=min(score, 100),
                status=status,
                confidence=0.9,
                reasons=reasons,
            ),
            summary=f"Направление: {project.value}. Потребность: {need}. Сроки: {timeline}. Бюджет: {budget}.",
            next_step=f"Передать в проектную группу «{project.value}» для детального расчёта сметы",
        )
