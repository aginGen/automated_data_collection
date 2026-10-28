import hashlib
import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def author_key(name):
    return hashlib.sha256(name.casefold().encode()).hexdigest()[:24]


def quote_key(source, source_record_id):
    return hashlib.sha256((source+'|'+source_record_id).encode('utf-8')).hexdigest()


class Quote(BaseModel):
    model_config = ConfigDict(extra='ignore')
    business_key: str = Field(pattern=r'^[0-9a-f]{64}$')
    text: str = Field(min_length=8, max_length=2000)
    author: str = Field(min_length=2, max_length=150)
    author_key: str = Field(pattern=r'^[0-9a-f]{24}$')
    tags: list[str] = Field(max_length=20)
    source: Literal['quotes_html','dummyjson_api']
    source_url: str = Field(min_length=12)
    parser_version: str = Field(min_length=1)
    collected_at: datetime
    source_record_id: str = Field(min_length=1)
    text_length: int = Field(gt=7, le=2000)
    author_birth_year: int | None = Field(default=None, ge=0, le=2100)

    @field_validator('text')
    @classmethod
    def text_is_content(cls,value):
        if value!=value.strip() or '<html' in value.casefold() or '\u200b' in value:
            raise ValueError('Текст должен быть очищенной цитатой')
        return value

    @field_validator('tags')
    @classmethod
    def tags_are_slugs(cls,values):
        if any(not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',v) for v in values):
            raise ValueError('Тег должен быть непустым slug в нижнем регистре')
        return values

    @field_validator('collected_at')
    @classmethod
    def utc_date(cls,value):
        if value.tzinfo is None or value.utcoffset().total_seconds()!=0:
            raise ValueError('Нужен часовой пояс UTC')
        if (value-datetime.now(timezone.utc)).total_seconds()>300:
            raise ValueError('Дата сбора находится в будущем')
        return value

    @model_validator(mode='after')
    def consistent(self):
        if self.business_key!=quote_key(self.source,self.source_record_id):
            raise ValueError('Бизнес-ключ не соответствует источнику и ID')
        if self.author_key!=author_key(self.author):
            raise ValueError('Неверный ключ автора')
        if self.text_length!=len(self.text):
            raise ValueError('Неверная длина текста')
        host='quotes.toscrape.com' if self.source=='quotes_html' else 'dummyjson.com'
        parts=urlsplit(self.source_url)
        if parts.scheme not in ('http','https') or parts.hostname!=host:
            raise ValueError('URL не соответствует источнику')
        return self
