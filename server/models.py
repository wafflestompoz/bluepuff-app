"""Database tables. SQLite by default (DATABASE_URL), Postgres in production."""
import datetime as dt
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()
now = lambda: dt.datetime.now(dt.timezone.utc)

# Club licence tiers: member cap, sensors included, regatta events a year, coach seats.
TIERS = {
    "none": {"cap": 0, "sensors": 0, "events": 0, "coaches": 0},
    "club": {"cap": 50, "sensors": 0, "events": 0, "coaches": 0},
    "plus": {"cap": 150, "sensors": 1, "events": 0, "coaches": 0},
    "pro": {"cap": 250, "sensors": 2, "events": 4, "coaches": 5},
}
ROLES = ("member", "officer", "admin", "coach")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, default="")
    password_hash = Column(String, nullable=False)
    plan = Column(String, default="free")            # free | racer | racer_pro (own subscription)
    plan_until = Column(DateTime(timezone=True))
    created = Column(DateTime(timezone=True), default=now)
    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"
    token_hash = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created = Column(DateTime(timezone=True), default=now)
    user = relationship("User")


class Club(Base):
    __tablename__ = "clubs"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False, index=True)    # the engine's club id (forecast/clubs_static.csv)
    name = Column(String, nullable=False)
    country = Column(String, default="")
    tz = Column(String, default="UTC")
    code = Column(String, unique=True, nullable=False)                # members join with this
    tier = Column(String, default="none")
    licence_until = Column(Date)
    memberships = relationship("Membership", back_populates="club", cascade="all, delete-orphan")
    fleets = relationship("ClubFleet", back_populates="club", cascade="all, delete-orphan")
    starts = relationship("Start", back_populates="club", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "club_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    role = Column(String, default="member")
    home = Column(Boolean, default=False)            # the club whose licence covers the sailor
    fleet = Column(String)                           # the class they race, for their briefing
    joined = Column(DateTime(timezone=True), default=now)
    user = relationship("User", back_populates="memberships")
    club = relationship("Club", back_populates="memberships")


class ClubFleet(Base):
    """A club's own limits for a class, over the defaults in engine/classes.csv."""
    __tablename__ = "club_fleets"
    __table_args__ = (UniqueConstraint("club_id", "cls"),)
    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    cls = Column(String, nullable=False)
    label = Column(String)                           # e.g. "Juniors (Optimist)"
    min_kn = Column(Float)
    max_gust_kn = Column(Float)
    club = relationship("Club", back_populates="fleets")


class Start(Base):
    __tablename__ = "starts"
    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    time = Column(String, nullable=False)            # HH:MM local
    fleets = Column(String, nullable=False)          # comma-separated class ids
    window_h = Column(Float, default=2.5)
    event_id = Column(Integer, ForeignKey("events.id"))
    club = relationship("Club", back_populates="starts")


class Notice(Base):
    """Race officer messages: shown in the app and on regatta pages, and pushed to members."""
    __tablename__ = "notices"
    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"))
    author_id = Column(Integer, ForeignKey("users.id"))
    text = Column(Text, nullable=False)
    created = Column(DateTime(timezone=True), default=now)
    pushed = Column(Integer, default=0)


class Event(Base):
    """A regatta with a public page (Club Pro)."""
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    first_day = Column(Date, nullable=False)
    last_day = Column(Date, nullable=False)
    classes = Column(String, default="")
    entries = Column(Integer)
    created = Column(DateTime(timezone=True), default=now)


class Sensor(Base):
    __tablename__ = "sensors"
    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    dev_eui = Column(String, unique=True, nullable=False, index=True)   # LoRaWAN device id
    label = Column(String, default="Club sensor")
    model = Column(String, default="barani-meteowind-iot-pro")
    shipped = Column(Date)


class Reading(Base):
    __tablename__ = "readings"
    id = Column(Integer, primary_key=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False, index=True)
    time = Column(DateTime(timezone=True), nullable=False, index=True)
    wind_kn = Column(Float)
    gust_kn = Column(Float)
    dir = Column(Float)
    battery_v = Column(Float)


class PushToken(Base):
    __tablename__ = "push_tokens"
    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created = Column(DateTime(timezone=True), default=now)


def make_session_factory(url):
    eng = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)
