from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.protocol import Protocol
    from models.supplier import Supplier


class SupplierKey(Base):
    __tablename__ = "keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    protocol_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    # Keys are encrypted at rest using AES-256
    secret_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # "native_call" | "api_key_only"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    remaining_quota_micros: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    network: Mapped[str] = mapped_column(String(10), nullable=False, default="testnet", server_default="testnet")
    label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="keys")
    protocol: Mapped["Protocol"] = relationship("Protocol", back_populates="keys")
