"""CSV writers for Tesla calendar history.

Preserves the exact on-disk contract Java's import services depend on:
  power/YYYY-MM-DD.csv  -- 5-min, columns: timestamp,solar_power,battery_power,grid_power,load_power
  energy/YYYY-MM.csv    -- 30-min rows, dynamic *_energy_* columns
  soe/YYYY-MM-DD.csv    -- 15-min, columns: timestamp,soe
"""

import csv
import os

from dateutil.parser import parse

# Owner-API era exclusions plus new Fleet-API-only fields that the Java side
# does not expect.
EXCLUDED_COLUMNS = (
    "grid_services_power",
    "generator_power",
    "generator_energy_exported",
    "grid_services_energy_imported",
    "grid_services_energy_exported",
    "grid_energy_exported_from_generator",
    "battery_energy_imported_from_generator",
    "consumer_energy_imported_from_generator",
    # Fleet-API additions not in legacy contract:
    "raw_timestamp",
    "total_home_usage",
    "total_battery_discharge",
    "total_solar_generation",
    "total_battery_charge",
    "total_grid_energy_exported",
)


def _strip(row):
    for col in EXCLUDED_COLUMNS:
        row.pop(col, None)


def _fieldnames(timeseries):
    keys = {}
    for row in timeseries:
        for k in row:
            keys[k] = True
    return list(keys)


def _power_csv_path(date, site_id, output_dir, partial_day):
    suffix = ".partial.csv" if partial_day else ".csv"
    return os.path.join(output_dir, str(site_id), "power", f"{date.strftime('%Y-%m-%d')}{suffix}")


def _energy_csv_path(date, site_id, output_dir, partial_month):
    suffix = ".partial.csv" if partial_month else ".csv"
    return os.path.join(output_dir, str(site_id), "energy", f"{date.strftime('%Y-%m')}{suffix}")


def _soe_csv_path(date, site_id, output_dir, partial_day):
    suffix = ".partial.csv" if partial_day else ".csv"
    return os.path.join(output_dir, str(site_id), "soe", f"{date.strftime('%Y-%m-%d')}{suffix}")


def get_power_csv_path(date, site_id, output_dir, partial_day=False):
    return _power_csv_path(date, site_id, output_dir, partial_day)


def get_energy_csv_path(date, site_id, output_dir, partial_month=False):
    return _energy_csv_path(date, site_id, output_dir, partial_month)


def get_soe_csv_path(date, site_id, output_dir, partial_day=False):
    return _soe_csv_path(date, site_id, output_dir, partial_day)


def write_power_csv(timeseries, date, site_id, output_dir, partial_day=False):
    if not timeseries:
        raise ValueError(f"No timeseries for {date}")
    path = _power_csv_path(date, site_id, output_dir, partial_day)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    base_fields = _fieldnames(timeseries) + ["load_power"]
    fields = [f for f in base_fields if f not in EXCLUDED_COLUMNS]

    with open(path, "w") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in timeseries:
            row["timestamp"] = parse(row["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            row["load_power"] = (
                row.get("solar_power", 0)
                + row.get("battery_power", 0)
                + row.get("grid_power", 0)
                + row.get("generator_power", 0)
            )
            _strip(row)
            writer.writerow(row)
    return path


def write_energy_csv(timeseries, date, site_id, output_dir, partial_month=False):
    if not timeseries:
        raise ValueError(f"No timeseries for {date}")
    path = _energy_csv_path(date, site_id, output_dir, partial_month)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    fields = [f for f in _fieldnames(timeseries) if f not in EXCLUDED_COLUMNS]

    with open(path, "w") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in timeseries:
            row["timestamp"] = parse(row["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            _strip(row)
            writer.writerow(row)
    return path


def write_soe_csv(timeseries, date, site_id, output_dir, partial_day=False):
    if not timeseries:
        raise ValueError(f"No timeseries for {date}")
    path = _soe_csv_path(date, site_id, output_dir, partial_day)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    fields = [f for f in _fieldnames(timeseries) if f not in EXCLUDED_COLUMNS]

    with open(path, "w") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in timeseries:
            row["timestamp"] = parse(row["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            _strip(row)
            writer.writerow(row)
    return path


def delete_partial_files(site_id, output_dir, kind):
    """kind in ('power','energy','soe')"""
    d = os.path.join(output_dir, str(site_id), kind)
    if not os.path.exists(d):
        return
    for fn in os.listdir(d):
        if ".partial.csv" in fn:
            os.remove(os.path.join(d, fn))
