from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    buyer_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    supplier_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    protocol_id: Mapped[str] = mapped_column(String(36), nullable=False)
    key_id: Mapped[str] = mapped_column(String(36), nullable=False)
    epoch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    request_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    was_self_served: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    was_refunded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gross_charge_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supplier_share_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jellynet_share_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buyer_discount_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
