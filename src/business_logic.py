from typing import Any, Dict

import data_access as da
import datetime as dt
import global_vars as gv


def get_data(days: int, username: str, value_type: str) -> Dict[str, Any]:

    df = da.get_data(username, value_type, days)

    span = int(df.shape[0] / 5)
    if span < 1:
        span = 1
    df.loc[:, 'value_ema'] = df['value_raw'].ewm(
        span=span, adjust=False).mean().round(2)
    record_times, values_raw, values_ema, remarks = [], [], [], []
    for index, row in df.iterrows():
        record_times.append(row['record_time'])
        values_raw.append(row['value_raw'])
        values_ema.append(row['value_ema'])
        remarks.append(row['remark'])

    reference_value = -1
    if (gv.settings['users'][username]['gender'] in
            gv.settings['items'][value_type]['reference_value']):
        reference_value = gv.settings['items'][value_type][
            'reference_value'][gv.settings['users'][username]['gender']]

    return {
        "record_times": record_times,
        "values_raw": values_raw,
        "values_ema": values_ema,
        "remarks": remarks,
        "reference_value": reference_value
    }


def get_latest_data(username: str, value_type: str) -> Dict[str, Any]:
    results = da.get_latest_data(username, value_type)

    if len(results) == 1:
        return {
            'record_time': results[0][0],
            'value': results[0][1],
            'remark': results[0][2],
        }
    elif len(results) == 0:
        return {
            'record_time': None,
            'value': None,
            'remark': None,
        }
    raise ValueError('Impossible scenario!')


def submit_data(username: str, value_type: str,
                value: float, remark: str) -> None:
    submission_time = dt.datetime.now() - dt.timedelta(
        seconds=gv.settings['app']['submission_diff_tol'])
    # If the interval between two submissions are not larger than this number
    # of minutes, the second submission will be considered the same as the
    # first submission and overwrite the first submission.
    da.write_data(submission_time, username, value_type, value, remark)
