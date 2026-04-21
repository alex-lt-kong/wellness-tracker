from dto.dto_data import DtoData

import data_access as da
import datetime as dt
import global_vars as gv
import numpy as np

# Maximum number of data points to return to the frontend.
# Longer time horizons are downsampled to this limit to keep
# charts responsive on mobile devices.
MAX_CHART_POINTS = 200


def _downsample(df, max_points: int):
    """Downsample a DataFrame to at most max_points rows using evenly-spaced
    indices, always preserving the first and last rows."""
    n = len(df)
    if n <= max_points:
        return df
    # Generate evenly spaced indices including 0 and n-1
    indices = np.linspace(0, n - 1, max_points, dtype=int)
    indices = np.unique(indices)  # remove duplicates from rounding
    return df.iloc[indices].reset_index(drop=True)


def get_data_by_duration(days: int, username: str,
                         value_type: str) -> DtoData:

    df = da.get_data_by_duration(username, value_type, days)
    span = int(df.shape[0] / 5)
    if span < 1:
        span = 1
    df.loc[:, 'value_ema'] = df['value_raw'].ewm(
        span=span, adjust=False).mean().round(2)

    # Bollinger Bands: EMA ± 2 * EWM standard deviation.
    # Using EWM std to match the EMA weighting (recent data weighted more).
    ewm_std = df['value_raw'].ewm(span=span, adjust=False).std().fillna(0)
    df.loc[:, 'band_upper'] = (df['value_ema'] + 2 * ewm_std).round(2)
    df.loc[:, 'band_lower'] = (df['value_ema'] - 2 * ewm_std).round(2)

    # Downsample after calculations so smoothing uses all data points
    df = _downsample(df, MAX_CHART_POINTS)

    reference_value = -1
    if (gv.settings['users'][username]['gender'] in
            gv.settings['items'][value_type]['reference_value']):
        reference_value = gv.settings['items'][value_type][
            'reference_value'][gv.settings['users'][username]['gender']]
    return DtoData(
        df['record_time'].to_list(), df['value_raw'].to_list(),
        df['value_ema'].to_list(), df['band_upper'].to_list(),
        df['band_lower'].to_list(), df['remark'].to_list(), reference_value)


def get_latest_data(username: str, value_type: str) -> DtoData:
    results = da.get_latest_data(username, value_type)
    reference_value = -1
    if (gv.settings['users'][username]['gender'] in
            gv.settings['items'][value_type]['reference_value']):
        reference_value = gv.settings['items'][value_type][
            'reference_value'][gv.settings['users'][username]['gender']]
    if len(results) == 1:
        return DtoData([results[0][0]], [results[0][1]], [results[0][1]],
                       [results[0][1]], [results[0][1]],
                       [results[0][2]], reference_value)
    if len(results) == 0:
        return DtoData([], [], [], [], [], [], reference_value)
    raise ValueError(f'Impossible scenario, len(results)=={len(results)}')


def submit_data(username: str, value_type: str,
                value: float, remark: str) -> None:
    submission_time = dt.datetime.now() - dt.timedelta(
        seconds=gv.settings['app']['submission_diff_tol'])
    # If the interval between two submissions are not larger than this number
    # of minutes, the second submission will be considered the same as the
    # first submission and overwrite the first submission.
    da.write_data(submission_time, username, value_type, value, remark)
