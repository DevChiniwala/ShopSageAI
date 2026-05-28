"""
SQLAlchemy Models for ShopSage AI.
"""

from typing import Optional
from datetime import datetime, timezone
import time
from sqlalchemy import String, Integer, Float, Boolean, Column, ForeignKey, Text, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shopsage.db.database import Base


def utcnow_ts() -> float:
    return time.time()


class Tenant(Base):
    __tablename__ = "tenant_registrations"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String, default="free", nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(String, default="")
    created_at: Mapped[float] = mapped_column(Float, default=utcnow_ts, nullable=False)
    activated_at: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[Optional[str]] = mapped_column("metadata", Text, default="{}")

    # Relationships
    api_keys = relationship("APIKey", back_populates="tenant", cascade="all, delete-orphan")


class APIKey(Base):
    __tablename__ = "api_keys"

    key_hash: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenant_registrations.tenant_id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    prefix: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=utcnow_ts, nullable=False)
    expires_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    tenant = relationship("Tenant", back_populates="api_keys")


class Webhook(Base):
    __tablename__ = "webhooks"

    webhook_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    secret: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[str] = mapped_column(String, nullable=False) # JSON list
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, default="", nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, default="delete", nullable=False)
    grace_period_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    notify_before_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=utcnow_ts, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, default=utcnow_ts, nullable=False)


class OnboardingChecklist(Base):
    __tablename__ = "onboarding_checklist"

    step_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, default="")
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[float] = mapped_column(Float, default=0.0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
