"""Unit and integration tests for AI Lead Qualifier."""

import asyncio
from qualifier.models import DialogState, LeadStatus
from qualifier.agent import LeadQualifierAgent
from qualifier.crm import AmoCRMClient
from qualifier.telegram import TelegramNotifier


def test_agent_dialog_turn():
    async def run():
        agent = LeadQualifierAgent(mock_mode=True)
        session = DialogState(session_id="test-session-1")

        # Ход 1
        reply1, profile1 = await agent.process_turn(session, "Здравствуйте! Нам нужны металлоконструкции для склада 1500 кв.м.")
        assert "объект" in reply1.lower() or "задачу" in reply1.lower()
        assert profile1.bant.need == "Металлоконструкции / ЛСТК"
        assert session.turn_count == 1

        # Ход 2
        reply2, profile2 = await agent.process_turn(session, "Сроки горят, нужно срочно за 2 недели смонтировать. Бюджет около 4.5 млн руб.")
        assert "сроки" in reply2.lower() or "проект" in reply2.lower()
        assert "срочно" in profile2.bant.timeline.lower()
        assert profile2.bant.budget_amount == 4_500_000.0

        # Ход 3 (с контактами)
        reply3, profile3 = await agent.process_turn(session, "Я генеральный директор ООО ПромСтрой, зовут Игорь, телефон +7 (912) 345-67-89")
        assert "бюджет" in reply3.lower() or "специалист" in reply3.lower() or "свяжется" in reply3.lower()
        assert profile3.phone == "+7 (912) 345-67-89"
        assert profile3.scoring.score >= 75
        assert profile3.scoring.status == LeadStatus.HOT

    asyncio.run(run())


def test_crm_mock_push():
    async def run():
        agent = LeadQualifierAgent(mock_mode=True)
        session = DialogState(session_id="test-crm-session")
        
        await agent.process_turn(session, "Нужен расчет септика для базы отдыха, телефон +7 (900) 111-22-33")
        
        crm = AmoCRMClient(mock_mode=True)
        result = await crm.push_lead(session.profile)

        assert result["status"] == "success"
        assert "amoCRM" in result["crm"]
        assert result["deal_id"] > 0
        assert "detail" in result["deal_url"]

    asyncio.run(run())


def test_telegram_formatting():
    async def run():
        agent = LeadQualifierAgent(mock_mode=True)
        session = DialogState(session_id="test-tg-session")
        
        await agent.process_turn(session, "Требуется ремонт турбины и компрессора, срочно, +7 (919) 343-48-71")
        
        notifier = TelegramNotifier(mock_mode=True)
        card = notifier.format_lead_card(session.profile, deal_url="https://demo.amocrm.ru/leads/detail/123")
        
        assert "Потребность (Need)" in card
        assert "Сроки (Timeline)" in card
        assert "Телефон" in card
        assert "+7 (919) 343-48-71" in card
        assert "https://demo.amocrm.ru/leads/detail/123" in card

        send_res = await notifier.send_lead_alert(session.profile)
        assert send_res["status"] == "success"

    asyncio.run(run())
