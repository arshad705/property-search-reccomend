from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String

from app.database import Base


class ApiCache(Base):
    __tablename__ = "api_cache"

    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String, unique=True, index=True, nullable=False)
    response_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class QueryLog(Base):
    __tablename__ = "query_log"

    id = Column(Integer, primary_key=True, index=True)
    tool_name = Column(String, nullable=False)
    request_json = Column(JSON, nullable=False)
    response_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
