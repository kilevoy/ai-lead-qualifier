"""FastAPI application for webhooks and interactive demo."""

import os
import uuid
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMouter, CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from qualifier.models import DialogState, LeadProfile
from qualifier.agent import LeadQualifierAgent
from qualifier.crm import AmoCRMClient
from qualifier.telegram import TelegramNotifier

app = FastAPI(
    title="AI Lead Qualifier & CRM Automation API",
    description="Интеллектуальная B2B-квалификация лидов и автосоздание сделок в CRM",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище активных диалоговых сессий в памяти
sessions: Dict[str, DialogState] = {}

agent = LeadQualifierAgent()
crm = AmoCRMClient()
telegram = TelegramNotifier()


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    profile: LeadProfile
    turn_count: int


class PushRequest(BaseModel):
    session_id: str


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "mock_mode": agent.mock_mode,
        "active_sessions": len(sessions),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    if session_id not in sessions:
        sessions[session_id] = DialogState(session_id=session_id)
    
    session = sessions[session_id]
    reply, profile = await agent.process_turn(session, req.message)
    
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        profile=profile,
        turn_count=session.turn_count,
    )


@app.post("/api/push-to-crm")
async def push_to_crm_endpoint(req: PushRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    
    session = sessions[req.session_id]
    crm_result = await crm.push_lead(session.profile)
    tg_result = await telegram.send_lead_alert(session.profile, deal_url=crm_result.get("deal_url"))

    return {
        "crm": crm_result,
        "telegram": tg_result,
    }


# Монтирование статики для веб-интерфейса
web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.exists(web_dir):
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")

