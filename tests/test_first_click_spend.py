"""Execute the attribution SQL against orders, spend and IST boundary fixtures."""
from datetime import date, datetime, time, timedelta, timezone
import sqlite3

import pytest

from app.api.routers.analytics import _first_click_sql


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE ga4_order_attribution (
            order_at TEXT, first_source TEXT, last_source TEXT,
            first_ad_id TEXT, last_ad_id TEXT, first_adset_id TEXT, last_adset_id TEXT,
            revenue REAL, days_to_convert INTEGER, total_sessions INTEGER);
        CREATE TABLE insights_daily_by_ad(ad_id TEXT, day TEXT, spend REAL);
        CREATE TABLE insights_daily_by_adset(adset_id TEXT, day TEXT, spend REAL);
        CREATE TABLE ad_lifecycle(ad_id TEXT, ad_name TEXT);
        CREATE TABLE meta_adsets(adset_id TEXT, adset_name TEXT);
    """)
    orders = [
        ("2026-09-30 18:29:59", "a", "a", 9999),  # Before 1 Oct IST.
        ("2026-09-30 18:30:00", "a", "b", 100),
        ("2026-10-01 12:00:00", "a", "b", 200),  # Same ad/day, second order.
        ("2026-10-02 18:29:59", "a", "a", 300),
        ("2026-10-02 18:30:00", "a", "a", 9999),  # After 2 Oct IST.
        ("2026-10-01 13:00:00", "unknown", None, 50),
        ("2026-10-02 08:00:00", "b", "c", 400),
        ("2026-10-01 14:00:00", "d", "b", 500),
        ("2026-10-01 14:30:00", "e", "a", 0),  # A zero-value order still has a first touch.
        ("2026-10-01 15:00:00", "idle", "b", 90),
    ]
    for at, first, last, revenue in orders:
        conn.execute("INSERT INTO ga4_order_attribution VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (at, "META", "META", first, last, first, last, revenue, 20, 3))
    spend = [
        ("a", "2026-09-30", 9999), ("a", "2026-10-01", 1100),
        ("a", "2026-10-02", 1200), ("a", "2026-10-03", 9999),
        ("b", "2026-10-01", 900), ("b", "2026-10-02", 600),
        ("c", "2026-10-02", 400), ("d", "2026-10-01", 2000),
        ("e", "2026-10-01", 1500), ("idle", "2026-09-30", 9999),
    ]
    for entity, day, amount in spend:
        conn.execute("INSERT INTO insights_daily_by_ad VALUES (?,?,?)", (entity, day, amount))
        conn.execute("INSERT INTO insights_daily_by_adset VALUES (?,?,?)", (entity, day, amount * 2))
    for entity in ("a", "b", "c", "d", "e", "idle"):
        conn.execute("INSERT INTO ad_lifecycle VALUES (?,?)", (entity, "Ad " + entity))
        conn.execute("INSERT INTO meta_adsets VALUES (?,?)", (entity, "Set " + entity))
    yield conn
    conn.close()


def query(db, grain, start="2026-10-01", end="2026-10-02"):
    # Adapt only PostgreSQL syntax and timestamp parameters; execute the actual
    # aggregation, joins, side counts and ROAS expressions unchanged.
    sql = _first_click_sql(grain).replace("public.", "").replace("btrim(", "trim(")
    sql = sql.replace("'first'::text", "'first'").replace("'last'::text", "'last'")
    sql = sql.replace("NULL::numeric", "CAST(NULL AS NUMERIC)")
    sql = sql.replace("(CAST(:from_date AS date)::timestamp AT TIME ZONE 'Asia/Kolkata')", ":start_utc")
    sql = sql.replace("((CAST(:to_date AS date) + 1)::timestamp AT TIME ZONE 'Asia/Kolkata')", ":end_utc")
    sql = sql.replace("CAST(:from_date AS date)", ":from_date").replace("CAST(:to_date AS date)", ":to_date")
    ist = timezone(timedelta(hours=5, minutes=30))
    def utc(day):
        return datetime.combine(day, time.min, ist).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    params = {"from_date": start, "to_date": end, "start_utc": utc(date.fromisoformat(start)),
              "end_utc": utc(date.fromisoformat(end) + timedelta(days=1))}
    return {r["source"]: dict(r) for r in db.execute(sql, params)}


@pytest.mark.parametrize("grain,multiplier", [("ad", 1), ("adset", 2)])
def test_spend_is_once_per_entity_per_side_and_only_in_selected_dates(db, grain, multiplier):
    rows = query(db, grain)
    a = rows["a"]
    assert a["first_click_revenue"] == 600
    assert a["last_click_revenue"] == 300
    assert a["first_click_spend"] == a["last_click_spend"] == 2300 * multiplier
    assert a["first_click_roas"] == pytest.approx(600 / (2300 * multiplier))
    assert a["last_click_roas"] == pytest.approx(300 / (2300 * multiplier))
    assert rows["b"]["first_click_spend"] == rows["b"]["last_click_spend"] == 1500 * multiplier
    # Day-one spend is included even though b only first-opens an order on day two.
    assert rows["b"]["first_click_revenue"] == 400


@pytest.mark.parametrize("grain", ["ad", "adset"])
def test_only_one_journey_side_does_not_claim_both_spends(db, grain):
    rows = query(db, grain)
    assert rows["d"]["first_click_spend"] > 0
    assert rows["d"]["last_click_spend"] == 0
    assert rows["d"]["last_click_roas"] is None
    assert rows["c"]["first_click_spend"] == 0
    assert rows["c"]["last_click_spend"] > 0
    assert rows["c"]["first_click_roas"] is None
    assert rows["c"]["last_click_roas"] is None  # Below the ₹1,000 floor.


def test_missing_spend_and_zero_revenue_do_not_change_order_presence(db):
    rows = query(db, "ad")
    for entity in ("unknown", "idle"):
        assert rows[entity]["first_click_spend"] is None
        assert rows[entity]["last_click_spend"] is None
        assert rows[entity]["first_click_roas"] is None
    assert rows["e"]["first_click_spend"] == 1500
    assert rows["e"]["first_click_roas"] == 0


def test_changing_range_changes_orders_and_both_spend_columns(db):
    rows = query(db, "ad", end="2026-10-01")
    assert rows["a"]["first_click_spend"] == rows["a"]["last_click_spend"] == 1100
    assert rows["a"]["first_click_revenue"] == 300
    assert rows["a"]["last_click_revenue"] == 0
    assert rows["b"]["first_click_spend"] == 0
    assert rows["b"]["last_click_spend"] == 900
    assert "c" not in rows


def test_source_grain_retains_revenue_without_inventing_channel_spend(db):
    row = query(db, "source")["META"]
    assert row["first_click_revenue"] == row["last_click_revenue"] == 1640
    for field in ("spend", "first_click_spend", "last_click_spend", "first_click_roas", "last_click_roas"):
        assert row[field] is None
