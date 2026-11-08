"""Pydantic data models for Lead Qualification, Sales Projects, and CRM Integration."""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class SalesProject(str, Enum):
    """Направления продаж (коммерческие проекты)."""
    ANGARS = "Проект: Ангары и Здания"           # БВЗ, металлокаркасы, ЛСТК, склады, ангары
    FASADY_KROVLYA = "Проект: Кровли и Фасады"   # Фасадные кассеты, металлосайдинг, профлист, сэндвич-панели
    GAZOBETON = "Проект: Газобетон"             # Автоклавный газобетон, стеновые блоки, перемычки
    COMPLEX = "Комплексный проект (Здание + Фасад + Блоки)"
    UNCERTAIN = "Направление уточняется"


class LeadStatus(str, Enum):
    HOT = "HOT"       # Горячий: есть бюджет, ЛПР, срочно (до 1-2 недель)
    WARM = "WARM"     # Тёплый: есть потребность, срок в течение 1-2 месяцев
    COLD = "COLD"     # Холодный: приценивается на перспективу, бюджет не ясен
    JUNK = "JUNK"     # Нецелевой / спам / поиск работы / не наш профиль


class BANTCriteria(BaseModel):
    """BANT-модель квалификации клиента."""
    budget: Optional[str] = Field(None, description="Бюджет или ценовые ожидания клиента")
    budget_amount: Optional[float] = Field(None, description="Числовая оценка бюджета в рублях")
    authority: Optional[str] = Field(None, description="Роль собеседника: ЛПР, снабженец, техспециалист, частник")
    need: Optional[str] = Field(None, description="Конкретная потребность: объект, тип продукции/услуги")
    timeline: Optional[str] = Field(None, description="Сроки реализации проекта / закупки")


class TechnicalSpecs(BaseModel):
    """Специфические параметры в зависимости от направления продаж."""
    area_sqm: Optional[float] = Field(None, description="Площадь здания/фасада в м²")
    volume_cbm: Optional[float] = Field(None, description="Объем газобетона в м³")
    density: Optional[str] = Field(None, description="Плотность газобетона: D400, D500, D600")
    building_purpose: Optional[str] = Field(None, description="Назначение здания: склад, цех, СТО, гараж")
    cassette_type: Optional[str] = Field(None, description="Тип кассет/фасада: КФ-1..КФ-4, сайдинг")
    delivery_city: Optional[str] = Field(None, description="Город/объект доставки")


class LeadScoring(BaseModel):
    """Оценка качества и перспективности лида."""
    score: int = Field(0, ge=0, le=100, description="Итоговый балл квалификации (0-100)")
    status: LeadStatus = Field(LeadStatus.COLD, description="Категория лида")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Уверенность AI в оценке")
    reasons: List[str] = Field(default_factory=list, description="Факторы, повлиявшие на скоринг")


class LeadProfile(BaseModel):
    """Полный профиль квалифицированного лида с направлением продаж."""
    client_name: Optional[str] = Field(None, description="Имя контактного лица")
    company_name: Optional[str] = Field(None, description="Название компании")
    phone: Optional[str] = Field(None, description="Контактный номер телефона")
    email: Optional[str] = Field(None, description="Электронная почта")
    telegram_id: Optional[str] = Field(None, description="ID / Username в Telegram")
    project: SalesProject = Field(SalesProject.UNCERTAIN, description="Целевое коммерческое направление")
    bant: BANTCriteria = Field(default_factory=BANTCriteria)
    specs: TechnicalSpecs = Field(default_factory=TechnicalSpecs)
    scoring: LeadScoring = Field(default_factory=LeadScoring)
    summary: str = Field("", description="Ёмкая выжимка для руководителя направления и менеджера")
    next_step: str = Field("Связаться для уточнения ТЗ", description="Рекомендуемое следующее действие")


class ChatMessage(BaseModel):
    role: str = Field(..., description="Роль: 'user', 'assistant' или 'system'")
    content: str = Field(..., description="Текст сообщения")


class DialogState(BaseModel):
    session_id: str
    messages: List[ChatMessage] = Field(default_factory=list)
    profile: LeadProfile = Field(default_factory=LeadProfile)
    is_completed: bool = False
    turn_count: int = 0
