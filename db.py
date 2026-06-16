import os
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

DB_PATH = os.environ.get("DB_PATH", "weather.db")
_engine = None


class Base(DeclarativeBase):
    pass


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def init_db() -> None:
    global _engine
    _engine = create_engine(f"sqlite:///{DB_PATH}")
    Base.metadata.create_all(_engine)


def record_report(report_type: str, message: str) -> None:
    with Session(_engine) as session:
        session.add(Report(type=report_type, message=message, created_at=datetime.now(timezone.utc)))
        session.commit()


def record_alert(alert_type: str, message: str) -> None:
    with Session(_engine) as session:
        session.add(Alert(type=alert_type, message=message, created_at=datetime.now(timezone.utc)))
        session.commit()


def _row_to_dict(obj) -> dict:
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col.name] = val
    return result


def get_reports(report_type: str | None = None, limit: int = 50) -> list[dict]:
    with Session(_engine) as session:
        q = session.query(Report).order_by(Report.id.desc())
        if report_type:
            q = q.filter(Report.type == report_type)
        return [_row_to_dict(r) for r in q.limit(limit).all()]


def get_alerts(alert_type: str | None = None, limit: int = 50) -> list[dict]:
    with Session(_engine) as session:
        q = session.query(Alert).order_by(Alert.id.desc())
        if alert_type:
            q = q.filter(Alert.type == alert_type)
        return [_row_to_dict(a) for a in q.limit(limit).all()]