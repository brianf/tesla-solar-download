#!/usr/bin/env python3
"""
Download missing April 17, 2025 data
"""
import teslapy
import csv
import logging
import os
from datetime import datetime
import pytz
from dateutil.parser import parse

logger = logging.getLogger(__name__)

SITE_ID = 2252412585360442
TIMEZONE = 'America/New_York'

def download_power_day(tesla, date):
    """Download power data for a specific day"""
    tz = pytz.timezone(TIMEZONE)
    start_date = tz.localize(date.replace(hour=0, minute=0, second=0)).isoformat()
    end_date = tz.localize(date.replace(hour=23, minute=59, second=59)).isoformat()

    logger.info(
        f"Downloading power data for {date.strftime('%Y-%m-%d')}...",
        extra={
            'operation': 'download_start',
            'data_type': 'power',
            'date': date.strftime('%Y-%m-%d')
        }
    )
    logger.info(
        f"  Start: {start_date}",
        extra={
            'operation': 'date_info',
            'date_type': 'start',
            'start_date': start_date
        }
    )
    logger.info(
        f"  End: {end_date}",
        extra={
            'operation': 'date_info',
            'date_type': 'end',
            'end_date': end_date
        }
    )

    try:
        response = tesla.api(
            'CALENDAR_HISTORY_DATA',
            path_vars={'site_id': SITE_ID},
            kind='power',
            period='day',
            start_date=start_date,
            end_date=end_date,
            time_zone=TIMEZONE,
        )

        if 'response' not in response or 'time_series' not in response['response']:
            logger.error(
                "  ERROR: No time_series in response",
                extra={
                    'operation': 'download_error',
                    'error_type': 'no_time_series',
                    'data_type': 'power'
                }
            )
            return False

        time_series = response['response']['time_series']
        logger.info(
            f"  Received {len(time_series)} data points",
            extra={
                'operation': 'download_progress',
                'data_type': 'power',
                'data_points': len(time_series)
            }
        )

        if not time_series:
            logger.warning(
                "  WARNING: Empty time series",
                extra={
                    'operation': 'download_warning',
                    'warning_type': 'empty_time_series',
                    'data_type': 'power'
                }
            )
            return False

        # Get fieldnames
        fieldnames = set()
        for entry in time_series:
            fieldnames.update(entry.keys())
        fieldnames = sorted(fieldnames)

        # Add load_power if not present
        if 'load_power' not in fieldnames:
            fieldnames.append('load_power')

        # Write CSV
        csv_filename = f'download/{SITE_ID}/power/{date.strftime("%Y-%m-%d")}.csv'
        os.makedirs(os.path.dirname(csv_filename), exist_ok=True)

        with open(csv_filename, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for entry in time_series:
                # Format timestamp
                entry['timestamp'] = parse(entry['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                # Calculate load_power
                entry['load_power'] = (
                    entry.get('solar_power', 0) +
                    entry.get('battery_power', 0) +
                    entry.get('grid_power', 0) +
                    entry.get('generator_power', 0)
                )
                writer.writerow(entry)

        logger.info(
            f"  ✓ Successfully wrote {csv_filename}",
            extra={
                'operation': 'file_write_success',
                'data_type': 'power',
                'csv_filename': csv_filename
            }
        )
        return True

    except Exception as e:
        logger.error(
            f"  ERROR: {e}",
            extra={
                'operation': 'download_error',
                'error': str(e),
                'data_type': 'power'
            }
        )
        import traceback
        traceback.print_exc()
        return False


def download_soe_day(tesla, date):
    """Download SOE data for a specific day"""
    tz = pytz.timezone(TIMEZONE)
    start_date = tz.localize(date.replace(hour=0, minute=0, second=0)).isoformat()
    end_date = tz.localize(date.replace(hour=23, minute=59, second=59)).isoformat()

    logger.info(
        f"Downloading SOE data for {date.strftime('%Y-%m-%d')}...",
        extra={
            'operation': 'download_start',
            'data_type': 'soe',
            'date': date.strftime('%Y-%m-%d')
        }
    )
    logger.info(
        f"  Start: {start_date}",
        extra={
            'operation': 'date_info',
            'date_type': 'start',
            'start_date': start_date
        }
    )
    logger.info(
        f"  End: {end_date}",
        extra={
            'operation': 'date_info',
            'date_type': 'end',
            'end_date': end_date
        }
    )

    try:
        response = tesla.api(
            'CALENDAR_HISTORY_DATA',
            path_vars={'site_id': SITE_ID},
            kind='soe',
            period='day',
            start_date=start_date,
            end_date=end_date,
            time_zone=TIMEZONE,
        )

        if 'response' not in response or 'time_series' not in response['response']:
            logger.warning(
                "  WARNING: No time_series in response (may not have SOE data for this day)",
                extra={
                    'operation': 'download_warning',
                    'warning_type': 'no_time_series',
                    'data_type': 'soe'
                }
            )
            return False

        time_series = response['response']['time_series']
        logger.info(
            f"  Received {len(time_series)} data points",
            extra={
                'operation': 'download_progress',
                'data_type': 'soe',
                'data_points': len(time_series)
            }
        )

        if not time_series:
            logger.warning(
                "  WARNING: Empty time series",
                extra={
                    'operation': 'download_warning',
                    'warning_type': 'empty_time_series',
                    'data_type': 'soe'
                }
            )
            return False

        # Get fieldnames
        fieldnames = set()
        for entry in time_series:
            fieldnames.update(entry.keys())
        fieldnames = sorted(fieldnames)

        # Write CSV
        csv_filename = f'download/{SITE_ID}/soe/{date.strftime("%Y-%m-%d")}.csv'
        os.makedirs(os.path.dirname(csv_filename), exist_ok=True)

        with open(csv_filename, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for entry in time_series:
                # Format timestamp
                entry['timestamp'] = parse(entry['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                writer.writerow(entry)

        logger.info(
            f"  ✓ Successfully wrote {csv_filename}",
            extra={
                'operation': 'file_write_success',
                'data_type': 'soe',
                'csv_filename': csv_filename
            }
        )
        return True

    except Exception as e:
        logger.error(
            f"  ERROR: {e}",
            extra={
                'operation': 'download_error',
                'error': str(e),
                'data_type': 'soe'
            }
        )
        import traceback
        traceback.print_exc()
        return False


def main():
    tesla = teslapy.Tesla('brianf@infinity.nu', retry=2, timeout=10)

    if not tesla.authorized:
        logger.error(
            "ERROR: Not authorized. Please run the main script first.",
            extra={
                'operation': 'auth_error',
                'error_type': 'not_authorized'
            }
        )
        return

    # Download missing day: April 17, 2025
    date = datetime(2025, 4, 17)

    logger.info(
        "=" * 80,
        extra={'operation': 'separator'}
    )
    logger.info(
        f"Downloading missing data for {date.strftime('%Y-%m-%d')}",
        extra={
            'operation': 'download_session_start',
            'date': date.strftime('%Y-%m-%d')
        }
    )
    logger.info(
        "=" * 80,
        extra={'operation': 'separator'}
    )
    logger.info(
        '',
        extra={'operation': 'separator'}
    )

    power_success = download_power_day(tesla, date)
    logger.info(
        '',
        extra={'operation': 'separator'}
    )
    soe_success = download_soe_day(tesla, date)

    logger.info(
        '',
        extra={'operation': 'separator'}
    )
    logger.info(
        "=" * 80,
        extra={'operation': 'separator'}
    )
    logger.info(
        "SUMMARY",
        extra={'operation': 'summary'}
    )
    logger.info(
        "=" * 80,
        extra={'operation': 'separator'}
    )
    logger.info(
        f"Power data: {'✓ Success' if power_success else '✗ Failed'}",
        extra={
            'operation': 'summary',
            'data_type': 'power',
            'success': power_success
        }
    )
    logger.info(
        f"SOE data: {'✓ Success' if soe_success else '✗ Failed'}",
        extra={
            'operation': 'summary',
            'data_type': 'soe',
            'success': soe_success
        }
    )


if __name__ == '__main__':
    main()
