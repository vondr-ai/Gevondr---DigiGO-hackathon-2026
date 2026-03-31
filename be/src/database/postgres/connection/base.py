# src\database\postgres\connection\base.py
from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

metadata_instance = MetaData()


class Base(DeclarativeBase):
    __abstract__ = True
    metadata = metadata_instance
