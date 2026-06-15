"""Tesla Solar/Powerwall download — Fleet API edition.

Replaces the Owner-API/teslapy stack that Tesla shut down on 2026-06-12.

Auth model:
- TESLA_FLEET_CLIENT_ID / TESLA_FLEET_CLIENT_SECRET in env.
- fleet-cache.json holds access_token + (rotating) refresh_token.
- One-time bootstrap: tesla_solar_download.py --setup --redirect-uri <uri>

CSV/JSONL contract is unchanged from the v2.x Owner-API version.
"""

import argparse
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta

import pytz
from dateutil.parser import parse

from csv_writer import (
    delete_partial_files,
    get_energy_csv_path,
    get_power_csv_path,
    write_energy_csv,
    write_power_csv,
    write_soe_csv,
)
from fleet_client import AuthRequired, FleetClient, FleetConfig, run_setup
from structured_logger import setup_logging

logger = logging.getLogger(__name__)


def _resolve_timezone(site_info, installation_date):
    if "installation_time_zone" in site_info:
        return site_info["installation_time_zone"]
    offset = installation_date.strftime("%z")
    for tz in pytz.country_timezones("us"):
        if datetime.now(pytz.timezone(tz)).strftime("%z") == offset:
            return tz
    return "America/New_York"


def _download_power_and_soe(client, site_id, timezone, output_dir, oldest_date_override):
    site_info = client.site_info(site_id)
    installation_date = parse(site_info["installation_date"])

    logger.info(
        f"  Installation date: {installation_date.strftime('%Y-%m-%d')}",
        extra={
            "operation": "date_info", "data_type": "power",
            "date_type": "installation",
            "date": installation_date.strftime("%Y-%m-%d"),
        },
    )

    date = datetime.now(pytz.timezone(timezone)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if oldest_date_override:
        effective_oldest = pytz.timezone(timezone).localize(
            oldest_date_override.replace(hour=0, minute=0, second=0, tzinfo=None)
        )
    else:
        effective_oldest = installation_date

    partial_day = True
    power_files = 0
    soe_files = 0

    while date > effective_oldest:
        csv_path = get_power_csv_path(date, site_id, output_dir)
        if partial_day or not os.path.exists(csv_path):
            try:
                start = pytz.timezone(timezone).localize(
                    date.replace(hour=0, minute=0, second=0, tzinfo=None)
                ).isoformat()
                end = pytz.timezone(timezone).localize(
                    date.replace(hour=23, minute=59, second=59, tzinfo=None)
                ).isoformat()

                power_resp = client.calendar_history(
                    site_id, kind="power", period="day",
                    start_date=start, end_date=end, time_zone=timezone,
                )
                if power_resp.get("time_series"):
                    write_power_csv(power_resp["time_series"], date, site_id,
                                    output_dir, partial_day=partial_day)
                    power_files += 1

                soe_resp = client.calendar_history(
                    site_id, kind="soe", period="day",
                    start_date=start, end_date=end, time_zone=timezone,
                )
                if soe_resp.get("time_series"):
                    write_soe_csv(soe_resp["time_series"], date, site_id,
                                  output_dir, partial_day=partial_day)
                    soe_files += 1
            except AuthRequired:
                raise
            except Exception:
                traceback.print_exc()
            time.sleep(1)
        date -= timedelta(days=1)
        partial_day = False
        date = pytz.timezone(timezone).localize(date.replace(tzinfo=None))

    logger.info(
        f"Power download complete: {power_files} files",
        extra={"operation": "download_power", "status": "success", "files": power_files},
    )
    logger.info(
        f"SOE download complete: {soe_files} files",
        extra={"operation": "download_soe", "status": "success", "files": soe_files},
    )


def _download_energy(client, site_id, timezone, output_dir, oldest_date_override):
    site_info = client.site_info(site_id)
    installation_date = parse(site_info["installation_date"])

    logger.info(
        f"  Installation date: {installation_date.strftime('%Y-%m-%d')}",
        extra={
            "operation": "date_info", "data_type": "energy",
            "date_type": "installation",
            "date": installation_date.strftime("%Y-%m-%d"),
        },
    )

    now = datetime.now(pytz.timezone(timezone)).replace(microsecond=0)
    start_date = now.replace(hour=0, minute=0, second=0)
    end_date = now.replace(hour=23, minute=59, second=59)
    start_date = start_date - timedelta(days=start_date.day - 1)

    if oldest_date_override:
        effective_oldest = pytz.timezone(timezone).localize(
            oldest_date_override.replace(hour=0, minute=0, second=0, tzinfo=None)
        )
    else:
        effective_oldest = installation_date

    partial_month = True
    energy_files = 0

    while end_date > effective_oldest:
        csv_path = get_energy_csv_path(start_date, site_id, output_dir)
        if partial_month or not os.path.exists(csv_path):
            try:
                resp = client.calendar_history(
                    site_id, kind="energy", period="month",
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    time_zone=timezone,
                )
                if resp.get("time_series"):
                    write_energy_csv(resp["time_series"], start_date, site_id,
                                     output_dir, partial_month=partial_month)
                    energy_files += 1
            except AuthRequired:
                raise
            except Exception:
                traceback.print_exc()
            time.sleep(1)
        partial_month = False
        end_date = start_date - timedelta(seconds=1)
        start_date = end_date.replace(hour=0, minute=0, second=0) - timedelta(
            days=end_date.day - 1
        )
        start_date = pytz.timezone(timezone).localize(start_date.replace(tzinfo=None))

    logger.info(
        f"Energy download complete: {energy_files} files",
        extra={"operation": "download_energy", "status": "success", "files": energy_files},
    )


def main():
    parser = argparse.ArgumentParser(description="Tesla Fleet API solar/powerwall downloader")
    parser.add_argument("--email", type=str, default=None,
                        help="(deprecated; ignored — Fleet API uses tokens, not email)")
    parser.add_argument("--output-dir", type=str, default="download")
    parser.add_argument("--log-file", type=str, default=None)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--oldest-date", type=str, default=None)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--cache-file", type=str, default="fleet-cache.json")
    parser.add_argument("--site-id", type=str, default=None,
                        help="Override site discovery; defaults to first battery/solar product")
    parser.add_argument("--setup", action="store_true",
                        help="Run one-time OAuth flow and write fleet-cache.json")
    parser.add_argument("--redirect-uri", type=str, default=None,
                        help="OAuth redirect URI registered with the Tesla developer app (for --setup)")
    args = parser.parse_args()

    setup_logging(
        log_file=args.log_file,
        console_level=logging.DEBUG if args.debug else logging.INFO,
    )

    if args.setup:
        if not args.redirect_uri:
            print("ERROR: --redirect-uri is required for --setup", file=sys.stderr)
            sys.exit(1)
        run_setup(args.cache_file, args.redirect_uri)
        return

    logger.info(
        "Tesla Fleet download starting",
        extra={
            "operation": "startup",
            "output_dir": args.output_dir,
            "log_file": args.log_file or "console_only",
            "non_interactive": args.non_interactive,
        },
    )

    os.makedirs(args.output_dir, exist_ok=True)

    oldest_date_override = None
    if args.oldest_date:
        try:
            oldest_date_override = parse(args.oldest_date)
        except Exception:
            logger.error(
                f"Invalid --oldest-date: {args.oldest_date}",
                extra={"operation": "validation_error", "error": "invalid_date"},
            )
            sys.exit(1)

    try:
        config = FleetConfig.from_env(args.cache_file)
        client = FleetClient(config, timeout=args.timeout)
        client._refresh_if_needed()
        client.emit_token_status(logger)
    except AuthRequired as e:
        logger.error(
            "Authentication required",
            extra={
                "operation": "auth_required",
                "error": str(e),
                "instructions": "Run with --setup locally and copy fleet-cache.json into the data volume.",
            },
        )
        sys.exit(2)
    except Exception as e:
        logger.error(
            f"Startup failed: {e}",
            extra={"operation": "startup_failed", "error": str(e)},
        )
        sys.exit(1)

    try:
        products = client.products()
    except AuthRequired as e:
        logger.error("Auth required during products list",
                     extra={"operation": "auth_required", "error": str(e)})
        sys.exit(2)

    energy_sites = [
        p for p in products
        if p.get("resource_type") in ("battery", "solar") and p.get("energy_site_id")
    ]
    if args.site_id:
        energy_sites = [p for p in energy_sites if str(p["energy_site_id"]) == str(args.site_id)]
    if not energy_sites:
        logger.error("No energy sites found", extra={"operation": "no_sites", "error": "no energy sites"})
        sys.exit(1)

    for product in energy_sites:
        site_id = product["energy_site_id"]
        resource_type = product.get("resource_type")
        masked = f"***{str(site_id)[-4:]}"

        site_info = client.site_info(site_id)
        installation_date = parse(site_info["installation_date"])
        timezone = _resolve_timezone(site_info, installation_date)

        logger.info(
            f"Downloading energy for {resource_type} site {masked}",
            extra={
                "operation": "download_start", "data_type": "energy",
                "resource_type": resource_type, "site_id": masked,
            },
        )
        try:
            delete_partial_files(site_id, args.output_dir, "energy")
            _download_energy(client, site_id, timezone, args.output_dir, oldest_date_override)
        except AuthRequired as e:
            logger.error("Auth required mid-download",
                         extra={"operation": "auth_required", "error": str(e)})
            sys.exit(2)
        except Exception:
            traceback.print_exc()

        logger.info(
            f"Downloading power+soe for {resource_type} site {masked}",
            extra={
                "operation": "download_start", "data_type": "power",
                "resource_type": resource_type, "site_id": masked,
            },
        )
        try:
            delete_partial_files(site_id, args.output_dir, "power")
            delete_partial_files(site_id, args.output_dir, "soe")
            _download_power_and_soe(client, site_id, timezone, args.output_dir, oldest_date_override)
        except AuthRequired as e:
            logger.error("Auth required mid-download",
                         extra={"operation": "auth_required", "error": str(e)})
            sys.exit(2)
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    main()
