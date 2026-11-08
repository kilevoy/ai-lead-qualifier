"""Unit and integration tests for AI Lead Qualifier with Project Direction support."""

import asyncio
from qualifier.models import DialogState, LeadStatus, SalesProject
from qualifier.agent import LeadQualifierAgent
from qualifier.crm import AmoCRMClient
from qualifier.telegram import TelegramNotifier


def test_project_detection_angars():
    async def run():
        agent = LeadQualifierAgent(mock_mode=True)
        session = DialogState(session_id="test-angar")

        reply, profile = await agent.process_turn(
            session,
            "Здравствуйте! Нам нужен быстровозводимый склад из металлокаркаса ЛСТК на 1500 кв.м. "
            "Сроки горят, за месяц смонтировать. Бюджет 6.5 млн руб. "
            "Я генеральный директор ООО ПромИнвест, Игорь, тел: +7 (919) 343-48-71"
        )
        assert profile.project == SalesProject.ANGARS
        assert profile.specs.area_sqm == 1500.0
        assert profile.phone == "+7 (919) 343-48-71"
        assert profile.scoring.score >= 75
        assert profile.scoring.status == LeadStatus.HOT

        # Проверка маршрутизации в CRM
        crm = AmoCRMClient(mock_mode=True)
        res = await crm.push_lead(profile)
        assert "Ангары и Здания" in res["pipeline"]

    asyncio.run(run())


def test_project_detection_fasady():
    async def run():
        agent = LeadQualifierAgent(mock_mode=True)
        session = DialogState(session_id="test-fasad")

        reply, profile = await agent.process_turn(
            session,
            "Добрый день, требуется навесная фасадная система из кассет КФ-1, площадь около 2400 м2. "
            "Монтаж планируем весной. Контакт: +7 (912) 800-11-22, прораб Сергей"
        )
        assert profile.project == SalesProject.FASADY_KROVLYA
        assert profile.specs.cassette_type == "КФ-1"
        assert profile.specs.area_sqm == 2400.0

        crm = AmoCRMClient(mock_mode=True)
        res = await crm.push_lead(profile)
        assert "Кровли и Фасады" in res["pipeline"]

    asyncio.run(run())


def test_project_detection_gazobeton():
    async def run():
        agent = LeadQualifierAgent(mock_mode=True)
        session = DialogState(session_id="test-gazobeton")

        reply, profile = await agent.process_turn(
            session,
            "Нужен автоклавный газобетон D500, объем 180 куб для строительства коттеджного поселка. "
            "Доставка в Челябинск. Телефон для сметы: +7 (902) 600-30-40"
        )
        assert profile.project == SalesProject.GAZOBETON
        assert profile.specs.density == "D500"
        assert profile.specs.volume_cbm == 180.0

        crm = AmoCRMClient(mock_mode=True)
        res = await crm.push_lead(profile)
        assert "Газобетон" in res["pipeline"]

        notifier = TelegramNotifier(mock_mode=True)
        card = notifier.format_lead_card(profile)
        assert "АВТОКЛАВНЫЙ ГАЗОБЕТОН" in card
        assert "180 м³" in card

    asyncio.run(run())
