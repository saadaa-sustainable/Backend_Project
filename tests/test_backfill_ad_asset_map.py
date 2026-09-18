"""Exact matching, source identity validation, and additive apply safeguards."""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

import pytest
from pglast import parse_sql

from scripts import backfill_ad_asset_map as backfill


WINDOW = {"from_date": date(2026, 8, 18), "to_date": date(2026, 9, 16), "basis": "delivered"}


@pytest.fixture(autouse=True)
def fake_bulk_insert(monkeypatch):
    def insert(cur, statement, rows, *, page_size, fetch):
        assert page_size == 250
        assert fetch is True
        cur.execute(statement, rows)
        return cur.fetchall()
    monkeypatch.setattr(backfill, "execute_values", insert)


def video(asset_id: str, **kwargs) -> backfill.Asset:
    return backfill.Asset("content_asset_register", asset_id, asset_id, **kwargs)


def plan(name: str, assets: list[backfill.Asset]):
    return backfill.plan_matches([
        {"ad_id": "ad-1", "ad_name": name, "period_spend": 123,
         "ad_created_date": date(2026, 7, 1)}
    ], assets, **WINDOW)


@pytest.mark.parametrize("name,matched", [
    ("Product_CPL012-0963_Copy", True),
    ("cpl012-0963", True),
    ("xCPL012-0963", False),
    ("CPL012-09630", False),
    ("CPL012-0963A", True),  # Preserve the current right non-digit boundary.
    ("CPL012_0963", False),
])
def test_exact_identifier_boundaries_and_case(name, matched):
    proposed, unresolved = plan(name, [video("CPL012-0963")])
    assert bool(proposed) is matched
    assert bool(unresolved) is not matched


def test_regex_characters_in_identifier_are_literal():
    asset = video("ASSET.[12]")
    assert len(plan("ad_ASSET.[12]_Copy", [asset])[0]) == 1
    assert not plan("ad_ASSETx1_Copy", [asset])[0]


def test_multiple_candidates_and_duplicate_register_rows_are_never_mapped():
    proposed, unresolved = plan("CPL012-0963+CPL010-0785", [video("CPL012-0963"), video("CPL010-0785")])
    assert proposed == []
    assert unresolved[0]["reason"] == "ambiguous_registered_identifiers"
    assert not plan("CPL012-0963", [video("CPL012-0963"), video("CPL012-0963")])[0]


def test_unregistered_codes_are_reported_but_never_synthesized():
    proposed, unresolved = plan("CPL012-0963_GAD-Sep-1493_SIF-12345-P1", [])
    assert proposed == []
    assert unresolved[0]["reason"] == "identifier_absent_from_registers"
    assert unresolved[0]["referenced_codes"] == "CPL012-0963 | GAD-Sep-1493 | SIF-12345-P1"
    assert plan("catalogue sale", [])[1][0]["reason"] == "no_recognizable_asset_identifier"


def snapshot(tmp_path: Path, payload) -> Path:
    path = tmp_path / "source.json"
    path.write_text(json.dumps(payload))
    return path


def test_valid_snapshot_is_virtual_and_existing_register_wins(tmp_path):
    path = snapshot(tmp_path, {"content_asset_register": [{"asset_id": "CPL012-0963", "link_to_asset": "https://example.test/asset"}]})
    sources = backfill.load_source_rows([path])
    assert sources[0].row["link_to_asset"] == "https://example.test/asset"
    assert plan("CPL012-0963", sources)[0][0]["source"] == str(path)
    existing = video("CPL012-0963")
    assert backfill.merge_assets([existing], sources) == [existing]


@pytest.mark.parametrize("payload", [
    {"unknown_table": []},
    {"content_asset_register": [{"asset_id": "CPL012-0963", "sql": "anything"}]},
    {"content_asset_register": [{"asset_id": " CPL012-0963"}]},
    {"content_asset_register": [{"asset_id": "CPL012-0963"}, {"asset_id": "cpl012-0963"}]},
    {"content_influencer_posts": [{"id": "123", "post_id": "SIF-12345-P1"}]},
    {"content_influencer_posts": [{"id": 123, "post_id": "SIF-12345-P1", "post_id_short": "SIF-99999-P1"}]},
    {"content_influencer_posts": [{"id": 123, "post_id": "SIF-12345-P1"}, {"id": 123, "post_id": "SIF-99999-P1"}]},
])
def test_invalid_sources_fail_before_database_work(tmp_path, payload):
    with pytest.raises(ValueError):
        backfill.load_source_rows([snapshot(tmp_path, payload)])


@pytest.mark.parametrize("existing", [
    [backfill.Asset("content_influencer_posts", "SIF-12345-P1", 2)],
    [backfill.Asset("content_influencer_posts", "SIF-99999-P1", 1)],
    [backfill.Asset("content_influencer_posts", "SIF-12345-P1", 1),
     backfill.Asset("content_influencer_posts", "SIF-12345-P1", 2)],
])
def test_influencer_identity_conflicts_fail(existing):
    with pytest.raises(ValueError):
        backfill.merge_assets(existing, [backfill.Asset("content_influencer_posts", "SIF-12345-P1", 1)])


def test_exact_executable_sql_parses_and_excludes_existing_mappings():
    for query in [backfill.SCOPE_SQL, backfill.SCOPE_SQL + " FOR SHARE OF al", backfill.INSERT_MAP_SQL]:
        parse_sql(re.sub(r"%\([^)]+\)s", "NULL", query).replace("%s", "(NULL,NULL,NULL,NULL)"))
    assert "NOT EXISTS" in backfill.SCOPE_SQL
    assert "COALESCE(impressions, 0) > 0" in backfill.SCOPE_SQL
    assert "al.ad_name = p.ad_name" in backfill.INSERT_MAP_SQL
    assert "ON CONFLICT (ad_id) DO NOTHING" in backfill.INSERT_MAP_SQL
    assert "UPDATE" not in backfill.INSERT_MAP_SQL


class Cursor:
    def __init__(self, *, fail_insert=False):
        self.commands = []
        self.result = []
        self.fail_insert = fail_insert

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, command, params=None):
        rendered = str(command)
        self.commands.append((rendered, params))
        if "WITH delivery AS" in rendered:
            self.result = [{"ad_id": "ad-1", "ad_name": "CPL012-0963_Copy", "period_spend": 123,
                            "ad_created_date": date(2026, 7, 1)}]
        elif "information_schema.columns" in rendered:
            self.result = [{"column_name": c} for c in ("asset_id", "link_to_asset", "mirrored_at")]
        elif "SELECT" in rendered and "AS asset_id" in rendered:
            self.result = ([{"asset_id": "CPL012-0963", "pk": "CPL012-0963"}]
                           if "content_asset_register" in rendered else [])
        elif "INSERT INTO" in rendered:
            self.result = [] if self.fail_insert else [{"ad_id": f"ad-{i}"} for i in range(len(params))]
        else:
            self.result = []

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None


class Connection:
    def __init__(self):
        self.cur = Cursor()
        self.settings = {}
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def set_session(self, **kwargs):
        self.settings = kwargs

    def cursor(self, **_):
        return self.cur

    def __enter__(self):
        return self

    def __exit__(self, error_type, *_):
        self.committed = error_type is None
        self.rolled_back = error_type is not None
        return False

    def close(self):
        self.closed = True


def cli_args(tmp_path):
    return ["--from-date", "2026-08-18", "--to-date", "2026-09-16", "--output-dir", str(tmp_path)]


def test_default_preview_uses_read_only_transaction_and_emits_review_files(tmp_path, monkeypatch):
    conn = Connection()
    monkeypatch.setattr(backfill.psycopg2, "connect", lambda *args, **kwargs: conn)
    monkeypatch.setattr(backfill, "load_dotenv", lambda *args, **kwargs: None)
    assert backfill.main(cli_args(tmp_path)) == 0
    assert conn.settings["readonly"] is True
    assert conn.closed
    assert all(not any(mutation in q for mutation in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "LOCK TABLE"))
               for q, _ in conn.cur.commands)
    report = json.loads((tmp_path / "summary.json").read_text())
    assert report["status"] == "preview_read_only"
    assert report["proposed_matches"] == 1
    assert report["inserted_mappings"] == 0
    with (tmp_path / "proposal.csv").open() as handle:
        assert list(csv.DictReader(handle))[0]["ad_name"] == "CPL012-0963_Copy"


def test_expected_match_guard_prevents_any_inserts_and_rolls_back(tmp_path, monkeypatch):
    conn = Connection()
    monkeypatch.setattr(backfill.psycopg2, "connect", lambda *args, **kwargs: conn)
    monkeypatch.setattr(backfill, "load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="Expected 0 matches; found 1"):
        backfill.main(cli_args(tmp_path) + ["--apply", "--expected-matches", "0"])
    assert conn.rolled_back
    assert not conn.committed
    assert all("INSERT" not in q for q, _ in conn.cur.commands)


def test_apply_preserves_existing_register_and_uses_live_lifecycle_metrics(tmp_path, monkeypatch):
    conn = Connection()
    monkeypatch.setattr(backfill.psycopg2, "connect", lambda *args, **kwargs: conn)
    monkeypatch.setattr(backfill, "load_dotenv", lambda *args, **kwargs: None)
    assert backfill.main(cli_args(tmp_path) + ["--apply", "--expected-matches", "1"]) == 0
    assert conn.committed
    inserts = [q for q, _ in conn.cur.commands if "INSERT" in q]
    assert inserts == [backfill.INSERT_MAP_SQL]
    assert any("FOR SHARE OF al" in q for q, _ in conn.cur.commands)


def test_only_needed_source_rows_imported_once_and_optional_missing_columns_omitted():
    row = {"asset_id": "CPL012-0963", "link_to_asset": "https://example.test/asset", "source_ad_id": "old"}
    source = video("CPL012-0963", source="snapshot", row=row)
    unused = video("CPL012-0999", source="snapshot", row={"asset_id": "CPL012-0999"})
    proposed, _ = plan("CPL012-0963", [source, unused])
    cur = Cursor()
    columns, omitted = backfill.source_target_columns(cur, [source, unused])
    assert omitted == {"content_asset_register": ["source_ad_id"]}
    counts = backfill.insert_proposals(cur, proposed + [{**proposed[0], "ad_id": "ad-2"}], columns)
    assert counts == {"video": 1}
    inserts = [(q, p) for q, p in cur.commands if "INSERT" in q]
    assert len(inserts) == 2
    assert "source_ad_id" not in inserts[0][0]
    assert "CPL012-0999" not in str(inserts)


def test_missing_or_raced_ad_aborts_apply():
    proposed, _ = plan("CPL012-0963", [video("CPL012-0963")])
    with pytest.raises(RuntimeError, match="Ad changed or was mapped"):
        backfill.insert_proposals(Cursor(fail_insert=True), proposed, {})
