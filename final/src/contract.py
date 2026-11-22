import re
from datetime import date, datetime, timedelta
from typing import Literal
from unicodedata import category as unicode_category
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


class Provenance(BaseModel):
    source_url: str
    collected_at: datetime
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")

    @field_validator("collected_at")
    @classmethod
    def require_utc(cls, value):
        if value.utcoffset() != timedelta(0):
            raise ValueError("время сбора должно быть в UTC")
        return value


class Book(Provenance):
    business_key: str = Field(pattern=r"^books:[1-9]\d*$")
    source: Literal["books"]
    source_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=100)
    currency: Literal["GBP"]
    price_pence: int = Field(gt=0, le=10_000_000)
    rating: int | None = Field(ge=1, le=5)
    in_stock: bool | None
    product_url: str

    @field_validator("title", "category")
    @classmethod
    def require_plain_text(cls, value):
        if value != " ".join(value.split()) or any(unicode_category(ch) in ("Cc", "Cf") for ch in value):
            raise ValueError("лишние пробелы или управляющие символы")
        if re.search(r"<[/!]?[a-zA-Z]", value):
            raise ValueError("в значении осталась HTML-разметка")
        return value

    @model_validator(mode="after")
    def validate_identity(self):
        if self.business_key != f"books:{self.source_id}":
            raise ValueError("бизнес-ключ не соответствует ID товара")
        detail = urlsplit(self.product_url)
        listing = urlsplit(self.source_url)
        id_match = re.search(r"_(\d+)/index\.html$", detail.path)
        if (detail.scheme, detail.hostname) != (listing.scheme, listing.hostname) or (
            id_match is None or int(id_match.group(1)) != self.source_id
        ):
            raise ValueError("адрес карточки не соответствует источнику и ID")
        return self


class Rate(Provenance):
    business_key: str = Field(pattern=r"^GBP:\d{4}-\d{2}-\d{2}$")
    source: Literal["fx"]
    currency: Literal["GBP"]
    rate_date: date
    nominal: Literal[1]
    rub_x10000: int = Field(gt=0, le=10_000_000)
    quote_field: Literal["Value", "Previous"]

    @model_validator(mode="after")
    def validate_identity(self):
        if self.business_key != f"{self.currency}:{self.rate_date.isoformat()}":
            raise ValueError("ключ курса не соответствует валюте и дате")
        return self
