from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.supplier_key import SupplierKey
    from models.pricing_rule import PricingRule


class Protocol(Base):
    __tablename__ = "protocols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tier: Mapped[str] = mapped_column(String(16), nullable=False)  # "free" | "paid"
    default_retail_micros: Mapped[int] = mapped_column(Integer, nullable=False)
    supplier_override_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_keys_per_supplier: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # JSON array of {"path_prefix": str, "model_pattern": str} routing rules
    match_rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    base_url: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    auth_header: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    auth_prefix: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    auth_query_param: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    test_endpoint: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    test_method: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, default="POST")
    # JSON string — default test payload template
    test_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON array string — popular model identifiers for this protocol
    popular_models: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    free_tier: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=True)
    free_tier_note: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    keys: Mapped[List["SupplierKey"]] = relationship(
        "SupplierKey", back_populates="protocol", cascade="all, delete-orphan"
    )
    pricing_rules: Mapped[List["PricingRule"]] = relationship(
        "PricingRule", back_populates="protocol", cascade="all, delete-orphan"
    )
