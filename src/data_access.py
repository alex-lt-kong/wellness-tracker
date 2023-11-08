from typing import List, Tuple, Any, Optional

import datetime as dt
import logging
import os
import pandas as pd
import sqlite3

db_path = os.path.join(os.path.dirname(
    os.path.dirname(os.path.realpath(__file__))), 'database.sqlite')


def prepare_database() -> None:
    con: Optional[sqlite3.Connection] = None
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                record_time TEXT NOT NULL,
                username    TEXT NOT NULL,
                value_type  TEXT NOT NULL,
                value       REAL NOT NULL,
                remark      TEXT DEFAULT NULL
            );
        """)
        con.commit()
        con.close()
    except Exception as ex:
        logging.exception('')
        raise ex
    finally:
        if con:
            con.close()


def get_average_value(username: str, value_type: str,
                      days: int) -> Tuple[int, Optional[float]]:
    con: Optional[sqlite3.Connection] = None
    results: Optional[List[Any]] = None
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            SELECT COUNT(value), AVG(value)
            FROM user_data
            WHERE
                record_time >= date('now', '-{} day') AND
                username = ? AND
                value_type = ?
        """.format(days), (username, value_type))
        results = cur.fetchall()
        con.commit()
        con.close()
    except Exception as ex:
        logging.exception('')
        raise ex
    finally:
        if con:
            con.close()
    if results is not None:
        entry_count = results[0][0]
    else:
        entry_count = 0
    if entry_count > 0:
        average_value = results[0][1]
    else:
        average_value = None

    return entry_count, average_value


def write_data(submission_time: dt.datetime, username: str,
               value_type: str, value: float, remark: str) -> None:
    con: Optional[sqlite3.Connection] = None
    results: Optional[List[Any]] = None
    try:
        con = sqlite3.connect(db_path)
        cursor = con.cursor()
        cursor.execute("""
            SELECT id, record_time, value, value_type
            FROM user_data
            WHERE record_time >= ? AND username = ? AND value_type = ?
            ORDER BY record_time ASC
        """, (submission_time, username, value_type))
        results = cursor.fetchall()
        if len(results) > 0:
            cursor.execute("""
                UPDATE user_data
                SET record_time = ?, value = ?, remark = ?
                WHERE record_time = ? AND username = ?
            """, (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  value, remark, results[-1][1], username))
            # len(results) could be greater than 1 suppose server side changes
            # the submission_diff_tol config item
        else:
            cursor.execute("""
                INSERT INTO user_data
                (record_time, username, value, value_type, remark)
                VALUES (?, ?, ?, ?, ?)
            """, (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  username, value, value_type, remark))

        con.commit()
        con.close()
    except Exception as ex:
        logging.exception('')
        raise ex
    finally:
        if con:
            con.close()


def get_latest_data(username: str, value_type: str) -> List[Any]:
    con: Optional[sqlite3.Connection] = None
    try:
        con = sqlite3.connect(db_path)
        cursor = con.cursor()
        cursor.execute("""
            SELECT record_time, value, remark
            FROM user_data
            WHERE username = ? AND value_type = ?
            ORDER BY record_time DESC
            LIMIT 1
        """, (username, value_type))
        result = cursor.fetchall()
        con.close()
        return result
    except Exception as ex:
        logging.exception('')
        raise ex
    finally:
        if con:
            con.close()


def get_data_by_duration(username: str, value_type: str, days: int) -> pd.DataFrame:
    con: Optional[sqlite3.Connection] = None
    try:
        con = sqlite3.connect(db_path)
        df = pd.read_sql("""
            SELECT record_time, value AS value_raw, remark
            FROM user_data
            WHERE username = ? AND
                value_type = ? AND
                (record_time >= date('now', '-{} day'))
            ORDER BY record_time ASC
        """.format(days), con=con, params=[username, value_type])
        con.close()
        return df
    except Exception as ex:
        logging.exception('')
        raise ex
    finally:
        if con:
            con.close()
