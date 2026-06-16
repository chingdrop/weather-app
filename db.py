import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Engine, ForeignKey, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

DB_PATH = os.environ.get("DB_PATH", "weather.db")
_engine: Engine | None = None


class Base(DeclarativeBase):
    pass


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    lat: Mapped[float]
    lon: Mapped[float]
    timezone: Mapped[str] = mapped_column(String(50))
    ntfy_topic: Mapped[str] = mapped_column(String(200))
    rain_prob_alert_percent: Mapped[float | None]
    rain_amount_alert_in: Mapped[float | None]
    wind_gust_alert_mph: Mapped[float | None]
    heat_index_alert_f: Mapped[float | None]
    frost_temp_alert_f: Mapped[float | None]
    uv_index_alert: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("locations.id"))
    type: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("locations.id"))
    type: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _require_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("db.init_db() has not been called")
    return _engine


def _migrate(engine: Engine) -> None:
    """Add location_id to pre-existing reports/alerts tables."""
    inspector = inspect(engine)
    existing = inspector.get_table_names()
    with engine.connect() as conn:
        if "reports" in existing:
            cols = [c["name"] for c in inspector.get_columns("reports")]
            if "location_id" not in cols:
                conn.execute(text("ALTER TABLE reports ADD COLUMN location_id INTEGER REFERENCES locations(id)"))
        if "alerts" in existing:
            cols = [c["name"] for c in inspector.get_columns("alerts")]
            if "location_id" not in cols:
                conn.execute(text("ALTER TABLE alerts ADD COLUMN location_id INTEGER REFERENCES locations(id)"))
        conn.commit()


def init_db() -> None:
    global _engine
    engine = create_engine(f"sqlite:///{DB_PATH}")
    _migrate(engine)
    Base.metadata.create_all(engine)
    _engine = engine


def upsert_location(
        name: str,
        lat: float,
        lon: float,
        tz_name: str,
        ntfy_topic: str,
        rain_prob_alert_percent: float | None = None,
        rain_amount_alert_in: float | None = None,
        wind_gust_alert_mph: float | None = None,
        heat_index_alert_f: float | None = None,
        frost_temp_alert_f: float | None = None,
        uv_index_alert: int | None = None,
) -> int:
    with Session(_require_engine()) as session:
        loc = session.query(Location).filter_by(name=name).first()
        if loc is None:
            loc = Location(
                name=name, lat=lat, lon=lon, timezone=tz_name, ntfy_topic=ntfy_topic,
                rain_prob_alert_percent=rain_prob_alert_percent,
                rain_amount_alert_in=rain_amount_alert_in,
                wind_gust_alert_mph=wind_gust_alert_mph,
                heat_index_alert_f=heat_index_alert_f,
                frost_temp_alert_f=frost_temp_alert_f,
                uv_index_alert=uv_index_alert,
                created_at=datetime.now(timezone.utc),
            )
            session.add(loc)
        else:
            loc.lat = lat
            loc.lon = lon
            loc.timezone = tz_name
            loc.ntfy_topic = ntfy_topic
            loc.rain_prob_alert_percent = rain_prob_alert_percent
            loc.rain_amount_alert_in = rain_amount_alert_in
            loc.wind_gust_alert_mph = wind_gust_alert_mph
            loc.heat_index_alert_f = heat_index_alert_f
            loc.frost_temp_alert_f = frost_temp_alert_f
            loc.uv_index_alert = uv_index_alert
        session.commit()
        session.refresh(loc)
        return loc.id


def record_report(location_id: int, report_type: str, message: str) -> None:
    with Session(_require_engine()) as session:
        session.add(
            Report(location_id=location_id, type=report_type, message=message, created_at=datetime.now(timezone.utc)))
        session.commit()


def record_alert(location_id: int, alert_type: str, message: str) -> None:
    with Session(_require_engine()) as session:
        session.add(
            Alert(location_id=location_id, type=alert_type, message=message, created_at=datetime.now(timezone.utc)))
        session.commit()


def _row_to_dict(obj) -> dict:
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col.name] = val
    return result


def get_reports(location_id: int | None = None, report_type: str | None = None, limit: int = 50) -> list[dict]:
    with Session(_require_engine()) as session:
        q = session.query(Report).order_by(Report.id.desc())
        if location_id is not None:
            q = q.filter(Report.location_id == location_id)
        if report_type:
            q = q.filter(Report.type == report_type)
        return [_row_to_dict(r) for r in q.limit(limit).all()]


def get_alerts(location_id: int | None = None, alert_type: str | None = None, limit: int = 50) -> list[dict]:
    with Session(_require_engine()) as session:
        q = session.query(Alert).order_by(Alert.id.desc())
        if location_id is not None:
            q = q.filter(Alert.location_id == location_id)
        if alert_type:
            q = q.filter(Alert.type == alert_type)
        return [_row_to_dict(a) for a in q.limit(limit).all()]


def prune_old_records(retain_days: int) -> tuple[int, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)
    with Session(_require_engine()) as session:
        reports_deleted = session.query(Report).filter(Report.created_at < cutoff).delete()
        alerts_deleted = session.query(Alert).filter(Alert.created_at < cutoff).delete()
        session.commit()
    return reports_deleted, alerts_deleted


def get_last_report_time(location_id: int, report_type: str) -> datetime | None:
    with Session(_require_engine()) as session:
        row = (
            session.query(Report)
            .filter(Report.location_id == location_id, Report.type == report_type)
            .order_by(Report.id.desc())
            .first()
        )
        return row.created_at if row else None


def get_last_alert_time(location_id: int, alert_type: str) -> datetime | None:
    with Session(_require_engine()) as session:
        row = (
            session.query(Alert)
            .filter(Alert.location_id == location_id, Alert.type == alert_type)
            .order_by(Alert.id.desc())
            .first()
        )
        return row.created_at if row else None
