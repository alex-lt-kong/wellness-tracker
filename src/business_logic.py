from dto.dto_data import DtoData

import data_access as da
import datetime as dt
import global_vars as gv


def get_data_by_duration(days: int, username: str,
                         value_type: str) -> DtoData:

    df = da.get_data_by_duration(username, value_type, days)

    span = int(df.shape[0] / 5)
    if span < 1:
        span = 1
    df.loc[:, 'value_ema'] = df['value_raw'].ewm(
        span=span, adjust=False).mean().round(2)

    reference_value = -1
    if (gv.settings['users'][username]['gender'] in
            gv.settings['items'][value_type]['reference_value']):
        reference_value = gv.settings['items'][value_type][
            'reference_value'][gv.settings['users'][username]['gender']]
    return DtoData(
        df['record_time'].to_list(), df['value_raw'].to_list(),
        df['value_ema'].to_list(), df['remark'].to_list(), reference_value)


def get_latest_data(username: str, value_type: str) -> DtoData:
    results = da.get_latest_data(username, value_type)
    reference_value = -1
    if (gv.settings['users'][username]['gender'] in
            gv.settings['items'][value_type]['reference_value']):
        reference_value = gv.settings['items'][value_type][
            'reference_value'][gv.settings['users'][username]['gender']]
    if len(results) == 1:
        return DtoData([results[0][0]], [results[0][1]], [results[0][1]],
                       [results[0][2]],  reference_value)
    if len(results) == 0:
        return DtoData([], [], [], [], reference_value)
    raise ValueError(f'Impossible scenario, len(results)=={len(results)}')


def submit_data(username: str, value_type: str,
                value: float, remark: str) -> None:
    submission_time = dt.datetime.now() - dt.timedelta(
        seconds=gv.settings['app']['submission_diff_tol'])
    # If the interval between two submissions are not larger than this number
    # of minutes, the second submission will be considered the same as the
    # first submission and overwrite the first submission.
    da.write_data(submission_time, username, value_type, value, remark)
