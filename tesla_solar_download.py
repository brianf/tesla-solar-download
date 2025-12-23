"""
Copyright 2023 Ziga Mahkovec

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import csv
import logging
import os
import time
import traceback
from datetime import datetime, timedelta

import pytz
import teslapy
from dateutil.parser import parse
from retry import retry

logger = logging.getLogger(__name__)

# Exclude columns that are not relevant (and generally not set).
EXCLUDED_COLUMNS = (
    'grid_services_power',
    'generator_power',
    'generator_energy_exported',
    'grid_services_energy_imported',
    'grid_services_energy_exported',
    'grid_energy_exported_from_generator',
    'battery_energy_imported_from_generator',
    'consumer_energy_imported_from_generator',
)


def _remove_excluded_columns(timeseries):
    for col in EXCLUDED_COLUMNS:
        if col in timeseries:
            del timeseries[col]


def _get_energy_csv_name(date, site_id, output_dir='download', partial_month=False):
    """Generate energy CSV file path.

    Args:
        date: Date for the file
        site_id: Tesla site ID
        output_dir: Base output directory (default: 'download')
        partial_month: Whether file is partial month

    Returns:
        str: Path like {output_dir}/{site_id}/energy/{YYYY-MM}.csv
    """
    str_date = date.strftime('%Y-%m')
    suffix = '.partial.csv' if partial_month else '.csv'
    return os.path.join(output_dir, str(site_id), 'energy', f'{str_date}{suffix}')


def _get_fieldnames_from_series(timeseries):
    keys = dict()
    for series in timeseries:
        for k in series.keys():
            keys[k] = True
    return list(keys.keys())


def _write_energy_csv(timeseries, date, site_id, output_dir='download', partial_month=False):
    if not timeseries:
        raise ValueError('No timeseries')

    csv_filename = _get_energy_csv_name(date, site_id, output_dir=output_dir, partial_month=partial_month)
    os.makedirs(os.path.dirname(csv_filename), exist_ok=True)
    fieldnames = _get_fieldnames_from_series(timeseries)
    fieldnames = [n for n in fieldnames if n not in EXCLUDED_COLUMNS]
    with open(csv_filename, 'w') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for ts in timeseries:
            ts['timestamp'] = parse(ts['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            _remove_excluded_columns(ts)
            writer.writerow(ts)


@retry(tries=2, delay=5)
def _download_energy_month(
    tesla, site_id, timezone, start_date, end_date, output_dir='download', partial_month=False
):
    response = tesla.api(
        'CALENDAR_HISTORY_DATA',
        path_vars={'site_id': site_id},
        kind='energy',
        period='month',
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        time_zone=timezone,
    )['response']

    if not response or 'time_series' not in response:
        raise ValueError(f'No timeseries for {start_date}')
    _write_energy_csv(
        response['time_series'], start_date, site_id, output_dir=output_dir, partial_month=partial_month
    )


def _get_timezone(site_config, installation_date):
    if 'installation_time_zone' in site_config:
        return site_config['installation_time_zone']
    offset = installation_date.strftime('%z')
    for tz in pytz.country_timezones('us'):
        if datetime.now(pytz.timezone(tz)).strftime('%z') == offset:
            return tz
    for tz in pytz.common_timezones:
        if datetime.now(pytz.timezone(tz)).strftime('%z') == offset:
            return tz
    for tz in pytz.all_timezones:
        if datetime.now(pytz.timezone(tz)).strftime('%z') == offset:
            return tz


def _download_energy_data(tesla, site_id, output_dir='download', oldest_date_override=None, debug=False):
    site_config = tesla.api('SITE_CONFIG', path_vars={'site_id': site_id})['response']
    installation_date = parse(site_config['installation_date'])
    timezone = _get_timezone(site_config, installation_date)

    logger.info(
        f'  Installation date from API: {installation_date.strftime("%Y-%m-%d")}',
        extra={
            'operation': 'date_info',
            'date_type': 'installation',
            'date': installation_date.strftime("%Y-%m-%d"),
            'data_type': 'energy'
        }
    )

    now = datetime.now(pytz.timezone(timezone)).replace(microsecond=0)
    start_date = now.replace(hour=0, minute=0, second=0)
    end_date = now.replace(hour=23, minute=59, second=59)

    # Beginning of the month.
    start_date = start_date - timedelta(days=start_date.day - 1)

    # Determine effective oldest date
    if oldest_date_override:
        # Make the override timezone-aware by localizing to the site's timezone
        effective_oldest_date = pytz.timezone(timezone).localize(
            oldest_date_override.replace(hour=0, minute=0, second=0, tzinfo=None)
        )
        logger.info(
            f'  Using oldest date: {effective_oldest_date.strftime("%Y-%m-%d")} (from --oldest-date parameter)',
            extra={
                'operation': 'date_info',
                'date_type': 'oldest',
                'date': effective_oldest_date.strftime("%Y-%m-%d"),
                'source': 'parameter',
                'data_type': 'energy'
            }
        )
    else:
        effective_oldest_date = installation_date
        logger.info(
            f'  Using oldest date: {effective_oldest_date.strftime("%Y-%m-%d")} (from installation date)',
            extra={
                'operation': 'date_info',
                'date_type': 'oldest',
                'date': effective_oldest_date.strftime("%Y-%m-%d"),
                'source': 'installation',
                'data_type': 'energy'
            }
        )

    if debug:
        logger.debug(
            f'Timezone: {timezone}',
            extra={
                'operation': 'debug_info',
                'timezone': timezone,
                'data_type': 'energy'
            }
        )
        logger.debug(
            f'Start date: {start_date}',
            extra={
                'operation': 'debug_info',
                'start_date': str(start_date),
                'data_type': 'energy'
            }
        )

    # The latest month will be partial.
    partial_month = True

    while end_date > effective_oldest_date:
        csv_name = _get_energy_csv_name(start_date, site_id, output_dir=output_dir)
        if partial_month or not os.path.exists(
            _get_energy_csv_name(start_date, site_id, output_dir=output_dir)
        ):
            logger.info(
                f'  {os.path.basename(csv_name)}',
                extra={
                    'operation': 'file_download',
                    'csv_filename': os.path.basename(csv_name),
                    'data_type': 'energy',
                    'period': start_date.strftime("%Y-%m")
                }
            )
            try:
                _download_energy_month(
                    tesla,
                    site_id,
                    timezone,
                    start_date,
                    end_date,
                    output_dir=output_dir,
                    partial_month=partial_month,
                )
            except Exception:
                traceback.print_exc()
            time.sleep(1)
        partial_month = False
        end_date = start_date - timedelta(seconds=1)
        start_date = end_date.replace(hour=0, minute=0, second=0) - timedelta(
            days=end_date.day - 1
        )
        start_date = pytz.timezone(timezone).localize(start_date.replace(tzinfo=None))


def _delete_partial_energy_files(site_id, output_dir='download'):
    dir = os.path.join(output_dir, str(site_id), 'energy')
    if not os.path.exists(dir):
        return
    for fname in os.listdir(dir):
        if '.partial.csv' in fname:
            os.remove(os.path.join(dir, fname))


def _get_power_csv_name(date, site_id, output_dir='download', partial_day=False):
    """Generate power CSV file path.

    Args:
        date: Date for the file
        site_id: Tesla site ID
        output_dir: Base output directory (default: 'download')
        partial_day: Whether file is partial day

    Returns:
        str: Path like {output_dir}/{site_id}/power/{YYYY-MM-DD}.csv
    """
    str_date = date.strftime('%Y-%m-%d')
    suffix = '.partial.csv' if partial_day else '.csv'
    return os.path.join(output_dir, str(site_id), 'power', f'{str_date}{suffix}')


def _get_soe_csv_name(date, site_id, output_dir='download', partial_day=False):
    """Generate state of charge (SOE) CSV file path.

    Args:
        date: Date for the file
        site_id: Tesla site ID
        output_dir: Base output directory (default: 'download')
        partial_day: Whether file is partial day

    Returns:
        str: Path like {output_dir}/{site_id}/soe/{YYYY-MM-DD}.csv
    """
    str_date = date.strftime('%Y-%m-%d')
    suffix = '.partial.csv' if partial_day else '.csv'
    return os.path.join(output_dir, str(site_id), 'soe', f'{str_date}{suffix}')


def _write_power_csv(timeseries, date, site_id, output_dir='download', partial_day=False):
    if not timeseries:
        raise ValueError(f'No timeseries for {date}')

    csv_filename = _get_power_csv_name(date, site_id, output_dir=output_dir, partial_day=partial_day)
    os.makedirs(os.path.dirname(csv_filename), exist_ok=True)
    fieldnames = _get_fieldnames_from_series(timeseries) + ['load_power']
    fieldnames = [n for n in fieldnames if n not in EXCLUDED_COLUMNS]
    with open(csv_filename, 'w') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for ts in timeseries:
            ts['timestamp'] = parse(ts['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            ts['load_power'] = (
                ts['solar_power']
                + ts['battery_power']
                + ts['grid_power']
                + ts['generator_power']
            )
            _remove_excluded_columns(ts)
            writer.writerow(ts)


def _write_soe_csv(timeseries, date, site_id, output_dir='download', partial_day=False):
    if not timeseries:
        raise ValueError(f'No timeseries for {date}')

    csv_filename = _get_soe_csv_name(date, site_id, output_dir=output_dir, partial_day=partial_day)
    os.makedirs(os.path.dirname(csv_filename), exist_ok=True)
    fieldnames = _get_fieldnames_from_series(timeseries)
    fieldnames = [n for n in fieldnames if n not in EXCLUDED_COLUMNS]
    with open(csv_filename, 'w') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for ts in timeseries:
            ts['timestamp'] = parse(ts['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            _remove_excluded_columns(ts)
            writer.writerow(ts)


@retry(tries=2, delay=5)
def _download_power_day(tesla, site_id, timezone, date, output_dir='download', partial_day=True):
    start_date = (
        pytz.timezone(timezone)
        .localize(date.replace(hour=0, minute=0, second=0, tzinfo=None))
        .isoformat()
    )
    end_date = (
        pytz.timezone(timezone)
        .localize(date.replace(hour=23, minute=59, second=59, tzinfo=None))
        .isoformat()
    )
    response = tesla.api(
        'CALENDAR_HISTORY_DATA',
        path_vars={'site_id': site_id},
        kind='power',
        period='day',
        start_date=start_date,
        end_date=end_date,
        time_zone=timezone,
    )['response']

    if not response or 'time_series' not in response:
        raise ValueError(f'No timeseries for {date}')
    _write_power_csv(response['time_series'], date, site_id, output_dir=output_dir, partial_day=partial_day)


@retry(tries=2, delay=5)
def _download_soe_day(tesla, site_id, timezone, date, output_dir='download', partial_day=True):
    start_date = (
        pytz.timezone(timezone)
        .localize(date.replace(hour=0, minute=0, second=0, tzinfo=None))
        .isoformat()
    )
    end_date = (
        pytz.timezone(timezone)
        .localize(date.replace(hour=23, minute=59, second=59, tzinfo=None))
        .isoformat()
    )
    response = tesla.api(
        'CALENDAR_HISTORY_DATA',
        path_vars={'site_id': site_id},
        kind='soe',
        period='day',
        start_date=start_date,
        end_date=end_date,
        time_zone=timezone,
    )['response']

    if response and 'time_series' in response:
        _write_soe_csv(response['time_series'], date, site_id, output_dir=output_dir, partial_day=partial_day)


def _download_power_data(tesla, site_id, output_dir='download', oldest_date_override=None, debug=False):
    site_config = tesla.api('SITE_CONFIG', path_vars={'site_id': site_id})['response']
    installation_date = parse(site_config['installation_date'])
    timezone = _get_timezone(site_config, installation_date)

    logger.info(
        f'  Installation date from API: {installation_date.strftime("%Y-%m-%d")}',
        extra={
            'operation': 'date_info',
            'date_type': 'installation',
            'date': installation_date.strftime("%Y-%m-%d"),
            'data_type': 'power'
        }
    )

    date = datetime.now(pytz.timezone(timezone)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # Determine effective oldest date
    if oldest_date_override:
        # Make the override timezone-aware by localizing to the site's timezone
        effective_oldest_date = pytz.timezone(timezone).localize(
            oldest_date_override.replace(hour=0, minute=0, second=0, tzinfo=None)
        )
        logger.info(
            f'  Using oldest date: {effective_oldest_date.strftime("%Y-%m-%d")} (from --oldest-date parameter)',
            extra={
                'operation': 'date_info',
                'date_type': 'oldest',
                'date': effective_oldest_date.strftime("%Y-%m-%d"),
                'source': 'parameter',
                'data_type': 'power'
            }
        )
    else:
        effective_oldest_date = installation_date
        logger.info(
            f'  Using oldest date: {effective_oldest_date.strftime("%Y-%m-%d")} (from installation date)',
            extra={
                'operation': 'date_info',
                'date_type': 'oldest',
                'date': effective_oldest_date.strftime("%Y-%m-%d"),
                'source': 'installation',
                'data_type': 'power'
            }
        )

    if debug:
        logger.debug(
            f'Timezone: {timezone}',
            extra={
                'operation': 'debug_info',
                'timezone': timezone,
                'data_type': 'power'
            }
        )
        logger.debug(
            f'Start date: {date}',
            extra={
                'operation': 'debug_info',
                'start_date': str(date),
                'data_type': 'power'
            }
        )

    # The first day (today) will be partial.
    partial_day = True

    while date > effective_oldest_date:
        csv_name = _get_power_csv_name(date, site_id, output_dir=output_dir)
        if partial_day or not os.path.exists(csv_name):
            logger.info(
                f'  {os.path.basename(csv_name)}',
                extra={
                    'operation': 'file_download',
                    'csv_filename': os.path.basename(csv_name),
                    'data_type': 'power',
                    'period': date.strftime("%Y-%m-%d")
                }
            )
            try:
                _download_power_day(tesla, site_id, timezone, date, output_dir=output_dir, partial_day=partial_day)
                _download_soe_day(tesla, site_id, timezone, date, output_dir=output_dir, partial_day=partial_day)
            except Exception:
                traceback.print_exc()
            time.sleep(1)
        date -= timedelta(days=1)
        partial_day = False
        # Re-localize the date based on the timezone.  This is important because we maybe have
        # crossed a daylight saving change so the timezone offset will be different.
        date = pytz.timezone(timezone).localize(date.replace(tzinfo=None))


def _delete_partial_power_files(site_id, output_dir='download'):
    dir = os.path.join(output_dir, str(site_id), 'power')
    if not os.path.exists(dir):
        return
    for fname in os.listdir(dir):
        if '.partial.csv' in fname:
            os.remove(os.path.join(dir, fname))


def _delete_partial_soe_files(site_id, output_dir='download'):
    dir = os.path.join(output_dir, str(site_id), 'soe')
    if not os.path.exists(dir):
        return
    for fname in os.listdir(dir):
        if '.partial.csv' in fname:
            os.remove(os.path.join(dir, fname))


def main():
    parser = argparse.ArgumentParser(
        description='Download Tesla Solar/Powerwall power data'
    )
    parser.add_argument(
        '--email', type=str, required=True, help='Tesla account email address'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='download',
        help='Base directory for downloaded files (default: download)'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        default=None,
        help='Path to JSON log file (optional, enables structured logging)'
    )
    parser.add_argument(
        '--non-interactive',
        action='store_true',
        help='Exit with error if auth required (for cron jobs)'
    )
    parser.add_argument('--debug', action='store_true', help='Print debug info')
    parser.add_argument(
        '--oldest-date',
        type=str,
        help='Oldest date to fetch data from (YYYY-MM-DD format). Defaults to installation date.'
    )
    args = parser.parse_args()

    # Initialize structured logging
    import logging
    from structured_logger import setup_logging

    setup_logging(
        log_file=args.log_file,
        console_level=logging.DEBUG if args.debug else logging.INFO
    )
    logger = logging.getLogger(__name__)

    logger.info("Tesla Solar Download starting", extra={
        'operation': 'startup',
        'email': args.email,
        'output_dir': args.output_dir,
        'log_file': args.log_file or 'console_only',
        'non_interactive': args.non_interactive
    })

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Parse oldest_date if provided
    oldest_date_override = None
    if args.oldest_date:
        try:
            oldest_date_override = parse(args.oldest_date)
        except Exception as e:
            logger.error(
                f"Error: Invalid date format for --oldest-date: {args.oldest_date}",
                extra={
                    'operation': 'validation_error',
                    'error_type': 'invalid_date',
                    'provided_value': args.oldest_date
                }
            )
            logger.error(
                "Expected format: YYYY-MM-DD",
                extra={
                    'operation': 'validation_error',
                    'error_type': 'invalid_date'
                }
            )
            return

    tesla = teslapy.Tesla(args.email, retry=2, timeout=10)
    if not tesla.authorized:
        auth_url = tesla.authorization_url()

        if args.non_interactive:
            logger.error(
                "Authentication required - not authorized",
                extra={
                    'operation': 'auth_required',
                    'auth_url': auth_url,
                    'cache_file': 'cache.json',
                    'instructions': 'Run script locally to authenticate, then upload cache.json'
                }
            )
            import sys
            sys.exit(2)  # Exit code 2 = auth failure

        # Interactive auth
        logger.info(
            'STEP 1: Log in to Tesla.  Open this page in your browser:\n',
            extra={
                'operation': 'auth_prompt',
                'step': 1,
                'prompt_text': 'Log in to Tesla'
            }
        )
        logger.info(
            auth_url,
            extra={
                'operation': 'auth_prompt',
                'auth_url': auth_url
            }
        )
        logger.info(
            '',
            extra={'operation': 'auth_prompt'}
        )
        logger.info(
            'After successful login, you will get a Page Not Found error.  That\'s expected.',
            extra={
                'operation': 'auth_prompt',
                'prompt_text': 'Page Not Found is expected'
            }
        )
        logger.info(
            'Just copy the url of that page and paste it here:',
            extra={
                'operation': 'auth_prompt',
                'prompt_text': 'Paste URL here'
            }
        )
        tesla.fetch_token(authorization_response=input('URL after authentication: '))
        logger.info(
            '\nSuccess!',
            extra={
                'operation': 'auth_prompt',
                'prompt_text': 'Authentication successful'
            }
        )

    # Log token status
    if tesla.authorized:
        logger.info(
            "Authenticated successfully",
            extra={
                'operation': 'auth_status',
                'expires_at': tesla.expires_at,
                'expires_at_human': time.ctime(tesla.expires_at),
                'time_until_expiry_hours': (tesla.expires_at - time.time()) / 3600,
                'cache_file': 'cache.json'
            }
        )

    for product in tesla.api('PRODUCT_LIST')['response']:
        resource_type = product.get('resource_type')
        if resource_type in ('battery', 'solar'):
            site_id = product['energy_site_id']
            obfuscated_site_it = f'***{str(site_id)[-4:]}'
            logger.info(
                f'Downloading energy data for {resource_type} site {obfuscated_site_it} to {args.output_dir}/energy/',
                extra={
                    'operation': 'download_start',
                    'data_type': 'energy',
                    'resource_type': resource_type,
                    'site_id': obfuscated_site_it,
                    'output_dir': f'{args.output_dir}/energy/'
                }
            )
            try:
                _delete_partial_energy_files(site_id, output_dir=args.output_dir)
                _download_energy_data(tesla, site_id, output_dir=args.output_dir, oldest_date_override=oldest_date_override, debug=args.debug)
            except Exception:
                traceback.print_exc()
            logger.info(
                '',
                extra={'operation': 'separator'}
            )

            logger.info(
                f'Downloading power data for {resource_type} site {obfuscated_site_it} to {args.output_dir}/power/',
                extra={
                    'operation': 'download_start',
                    'data_type': 'power',
                    'resource_type': resource_type,
                    'site_id': obfuscated_site_it,
                    'output_dir': f'{args.output_dir}/power/'
                }
            )
            try:
                _delete_partial_power_files(site_id, output_dir=args.output_dir)
                _delete_partial_soe_files(site_id, output_dir=args.output_dir)
                _download_power_data(tesla, site_id, output_dir=args.output_dir, oldest_date_override=oldest_date_override, debug=args.debug)
            except Exception:
                traceback.print_exc()


if __name__ == '__main__':
    main()
