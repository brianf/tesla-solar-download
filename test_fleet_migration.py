"""Tests for the Fleet API migration: csv_writer + fleet_client.

Focus on contract preservation: column sets and value derivation must match
the Owner-API era CSVs that the SolarTracker Java side has been parsing.
"""

import csv
import json
import os
import tempfile
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from csv_writer import (
    EXCLUDED_COLUMNS,
    write_energy_csv,
    write_power_csv,
    write_soe_csv,
)
from fleet_client import AuthRequired, FleetClient, FleetConfig


@pytest.fixture
def tmp_outdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def fleet_sample_power_row():
    return {
        "timestamp": "2026-06-14T00:05:00-04:00",
        "solar_power": 100.0,
        "battery_power": 50.0,
        "grid_power": 200.0,
        "generator_power": 0,
        "grid_services_power": 0,  # excluded
    }


@pytest.fixture
def fleet_sample_energy_row():
    return {
        "timestamp": "2026-06-01T00:00:00-04:00",
        "solar_energy_exported": 100,
        "grid_energy_imported": 200,
        "grid_energy_exported_from_solar": 10,
        "grid_energy_exported_from_battery": 5,
        "battery_energy_exported": 30,
        "battery_energy_imported_from_grid": 0,
        "battery_energy_imported_from_solar": 25,
        "consumer_energy_imported_from_grid": 195,
        "consumer_energy_imported_from_solar": 65,
        "consumer_energy_imported_from_battery": 30,
        # Fleet-API-only fields that must NOT appear in the CSV:
        "raw_timestamp": "2026-06-01T00:00:00-04:00",
        "total_home_usage": 290,
        "total_battery_discharge": 30,
        "total_solar_generation": 100,
        "total_battery_charge": 25,
        "total_grid_energy_exported": 15,
        "generator_energy_exported": 0,
    }


class TestPowerCsvContract:
    def test_load_power_derived_as_sum(self, tmp_outdir, fleet_sample_power_row):
        write_power_csv(
            [fleet_sample_power_row],
            datetime(2026, 6, 14),
            123,
            tmp_outdir,
            partial_day=False,
        )
        path = os.path.join(tmp_outdir, "123", "power", "2026-06-14.csv")
        with open(path) as f:
            row = next(csv.DictReader(f))
        assert float(row["load_power"]) == 350.0  # 100 + 50 + 200 + 0

    def test_columns_match_legacy_contract(self, tmp_outdir, fleet_sample_power_row):
        write_power_csv([fleet_sample_power_row], datetime(2026, 6, 14), 1, tmp_outdir)
        with open(os.path.join(tmp_outdir, "1", "power", "2026-06-14.csv")) as f:
            header = f.readline().strip().split(",")
        assert "grid_services_power" not in header
        assert "generator_power" not in header
        assert header == [
            "timestamp",
            "solar_power",
            "battery_power",
            "grid_power",
            "load_power",
        ]

    def test_partial_day_suffix(self, tmp_outdir, fleet_sample_power_row):
        write_power_csv([fleet_sample_power_row], datetime(2026, 6, 14), 1, tmp_outdir,
                        partial_day=True)
        assert os.path.exists(os.path.join(tmp_outdir, "1", "power", "2026-06-14.partial.csv"))


class TestEnergyCsvContract:
    def test_excludes_all_fleet_only_fields(self, tmp_outdir, fleet_sample_energy_row):
        write_energy_csv([fleet_sample_energy_row], datetime(2026, 6, 1), 1, tmp_outdir)
        with open(os.path.join(tmp_outdir, "1", "energy", "2026-06.csv")) as f:
            header = f.readline().strip().split(",")
        for forbidden in (
            "raw_timestamp", "total_home_usage", "total_battery_discharge",
            "total_solar_generation", "total_battery_charge",
            "total_grid_energy_exported", "generator_energy_exported",
        ):
            assert forbidden not in header, f"{forbidden} leaked into CSV header"

    def test_legacy_columns_present(self, tmp_outdir, fleet_sample_energy_row):
        write_energy_csv([fleet_sample_energy_row], datetime(2026, 6, 1), 1, tmp_outdir)
        with open(os.path.join(tmp_outdir, "1", "energy", "2026-06.csv")) as f:
            header = f.readline().strip().split(",")
        for required in (
            "timestamp",
            "solar_energy_exported",
            "grid_energy_imported",
            "grid_energy_exported_from_solar",
            "grid_energy_exported_from_battery",
            "battery_energy_exported",
            "battery_energy_imported_from_grid",
            "battery_energy_imported_from_solar",
            "consumer_energy_imported_from_grid",
            "consumer_energy_imported_from_solar",
            "consumer_energy_imported_from_battery",
        ):
            assert required in header


class TestSoeCsvContract:
    def test_columns_only_timestamp_and_soe(self, tmp_outdir):
        ts = [{"timestamp": "2026-06-14T00:00:00-04:00", "soe": 97}]
        write_soe_csv(ts, datetime(2026, 6, 14), 1, tmp_outdir)
        with open(os.path.join(tmp_outdir, "1", "soe", "2026-06-14.csv")) as f:
            header = f.readline().strip().split(",")
        assert header == ["timestamp", "soe"]


class TestExcludedColumnsList:
    def test_includes_legacy_and_fleet_only(self):
        # Sanity: catches accidental deletions
        for col in ("grid_services_power", "generator_power",
                    "raw_timestamp", "total_home_usage"):
            assert col in EXCLUDED_COLUMNS


class TestFleetClient:
    def test_load_cache_missing_raises_auth_required(self):
        cfg = FleetConfig("cid", "csec", "/nonexistent/path.json")
        with pytest.raises(AuthRequired):
            FleetClient(cfg)

    def test_refresh_skipped_when_token_fresh(self, tmp_outdir):
        cache = os.path.join(tmp_outdir, "cache.json")
        with open(cache, "w") as f:
            json.dump({
                "access_token": "fresh",
                "refresh_token": "r",
                "expires_at": time.time() + 7200,
            }, f)
        cfg = FleetConfig("cid", "csec", cache)
        with patch("fleet_client.requests") as mreq:
            client = FleetClient(cfg)
            client._refresh_if_needed()
            mreq.post.assert_not_called()

    def test_refresh_invalid_grant_raises_auth_required(self, tmp_outdir):
        cache = os.path.join(tmp_outdir, "cache.json")
        with open(cache, "w") as f:
            json.dump({
                "access_token": "stale",
                "refresh_token": "r",
                "expires_at": time.time() - 100,
            }, f)
        cfg = FleetConfig("cid", "csec", cache)
        with patch("fleet_client.requests") as mreq:
            mreq.post.return_value = MagicMock(status_code=400, text='{"error":"invalid_grant"}')
            client = FleetClient(cfg)
            with pytest.raises(AuthRequired):
                client._refresh_if_needed()

    def test_refresh_persists_rotated_token(self, tmp_outdir):
        cache = os.path.join(tmp_outdir, "cache.json")
        with open(cache, "w") as f:
            json.dump({
                "access_token": "stale",
                "refresh_token": "old-refresh",
                "expires_at": time.time() - 100,
            }, f)
        cfg = FleetConfig("cid", "csec", cache)
        with patch("fleet_client.requests") as mreq:
            ok = MagicMock(status_code=200)
            ok.json.return_value = {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 28800,
                "token_type": "Bearer",
            }
            mreq.post.return_value = ok
            client = FleetClient(cfg)
            client._refresh_if_needed()
        with open(cache) as f:
            saved = json.load(f)
        assert saved["access_token"] == "new-access"
        assert saved["refresh_token"] == "new-refresh"
