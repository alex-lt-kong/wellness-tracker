#!/usr/bin/python3

from flask import Response, request, redirect, session
from flask import send_file, jsonify
from hashlib import sha256
from waitress import serve

import argparse
import datetime as dt
import flask
import importlib
import json
import logging
import numpy as np
import os
import pandas as pd
import pymysql
import signal
import sys
import threading
import time


app = flask.Flask(__name__)
app.secret_key = b''
app.config['JSON_AS_ASCII'] = False
app.config['JSON_SORT_KEYS'] = False
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    # If this is set to True, client-side JavaScript will not be able to
    # access the session cookie.
    SESSION_COOKIE_SAMESITE='Lax',
)

# This necessary for javascript to access a telemetry link without opening it:
# https://stackoverflow.com/questions/22181384/javascript-no-access-control-allow-origin-header-is-present-on-the-requested
stop_signal = False

# app_address: the app's address (including protocol and port) on the Internet
app_address = ''
# app_dir: the app's real address on the filesystem
app_dir = os.path.dirname(os.path.realpath(__file__))
debug_mode = False
settings = {}
app_name = 'health-manager'


db_url = ''
db_username = ''
db_password = ''
db_name = ''

def get_average_value(username: str, value_type: str, days: int):

    conn = pymysql.connect(db_url, db_username, db_password, db_name)
    cursor = conn.cursor()
    sql = '''
        SELECT COUNT(`value`), AVG(`value`)
        FROM `user_data`
        WHERE (`record_time` between (NOW() - INTERVAL %s DAY ) and NOW()) AND
            `username` = %s AND
            `value_type` = %s
        '''
    cursor.execute(sql, (days, username, value_type))
    results = cursor.fetchall()

    if results is not None:
        entry_count = results[0][0]
    else:
        entry_count = 0
    if entry_count > 0:
        average_value = results[0][1]
    else:
        average_value = np.nan

    return entry_count, average_value


@app.route('/logout/')
def logout():

    if f'{app_name}' in session:
        session[f'{app_name}'].pop('username', None)
    return redirect(f'{app_address}/')


@app.before_request
def make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = dt.timedelta(days=365)


@app.route('/login/', methods=['GET', 'POST'])
def login():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        return redirect(f'{app_address}/')

    kwargs = {
        'app_address': app_address,
        'mode': 'dev' if debug_mode else 'prod',
        'telemetry_url': settings['app']['telemetry_url']
    }
    if request.method == 'POST':

        username = request.form['username']
        kwargs['username'] = username

        if request.form['username'] not in settings['users']:
            kwargs['err_msg'] = f'错误：用户{username}不存在'
            return flask.render_template('login.html', **kwargs)
        if (sha256(request.form['password'].encode('utf-8')).hexdigest() !=
                settings['users'][username]['password_hash']):
            kwargs['err_msg'] = '错误：密码错误'
            return flask.render_template('login.html', **kwargs)

        session[f'{app_name}'] = {}
        session[f'{app_name}']['username'] = username
        return redirect(f'{app_address}/')


    return flask.render_template('login.html', **kwargs)


@app.route('/', methods=['GET'])
def index():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return redirect(f'{app_address}/login/')

    kwargs = {
        'app_address': app_address,
        'mode': 'dev' if debug_mode else 'prod',
        'username': username,
        'telemetry_url': settings['app']['telemetry_url']
    }

    response = flask.make_response(flask.render_template('record.html', **kwargs))
    # render_template actually returns a string, just a string returned from
    # a view is automatically wrapped in a response by Flask
    # https://stackoverflow.com/questions/29464276/add-response-headers-to-flask-web-app
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response



@app.route('/get-available-items/', methods=['GET'])
def get_available_items():
    
    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)

    return {"data": settings['items']}


@app.route('/submit-data/', methods=['POST'])
def submit_data():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)
    
    try:
        value = float(request.form['value'])
        value_type = str(request.form['value_type'])
        remark = str(request.form['remark'])
    except Exception as ex:
        return Response('参数错误', 400)
    if value_type not in settings['items'].keys():
        return Response('value_type不在允许列表内', 400)

    submission_time = dt.datetime.now() - dt.timedelta(seconds=settings['app']['submission_diff_tol'])
    # If the interval between two submissions are not larger than this number of
    # minutes, the second submission will be considered the same as the first
    # submission and overwrite the first submission.

    try:
        conn = pymysql.connect(db_url, db_username, db_password, db_name)
        conn.autocommit(True) # It appears that both UPDATE and SELECT need "commit"
        cursor = conn.cursor()
        sql = """
            SELECT `id`, `record_time`, `value`, `value_type`
            FROM `user_data`
            WHERE `record_time` >= %s AND `username` = %s AND `value_type` = %s
            ORDER BY `record_time` ASC
        """
        cursor.execute(sql, (submission_time, username, value_type))
        results = cursor.fetchall()

        if len(results) > 0:
            sql = """
                UPDATE `user_data`
                SET `record_time`= %s, `value` = %s, `remark` = %s
                WHERE `record_time` = %s AND `username` = %s
            """
            cursor.execute(sql, (dt.datetime.now(), value, remark, results[-1][1], username))
            # len(results) could be greater than 1 suppose server side changes
            # the submission_diff_tol config item
        else:
            sql = """
                INSERT INTO `user_data` (`record_time`, `username`, `value`, `value_type`, `remark`)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(
                sql,
                (dt.datetime.now(), username, value, value_type, remark)
            )
    except Exception as ex:
        logging.error(f'Database operation error: {ex}')
        return Response('数据库错误', 500)
    finally:
        cursor.close()
        conn.close()

    return Response('数据写入成功', 200)


@app.route('/get-latest-data/', methods=['GET'])
def get_latest_data():
    # It turns out that combining get_data() and get_latest_data() is NOT
    # a good idea since there are a few differences..
    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)

    try:
        value_type = str(request.args.get('value_type'))
    except Exception as ex:
        return Response('参数错误', 400)
    try:
        conn = pymysql.connect(db_url, db_username, db_password, db_name)
        conn.autocommit(True) # It appears that both UPDATE and SELECT need "commit"
        cursor = conn.cursor()
        sql = """
            SELECT `record_time`, `value`, `remark`
            FROM `user_data`
            WHERE `username` = %s AND `value_type` = %s
            ORDER BY `record_time` DESC
            LIMIT 1"""
        cursor.execute(sql, (username, value_type))
        results = cursor.fetchall()
    except Exception as ex:
        logging.error('Database operation error: {ex}')
        return Response('数据库错误', 500)
    finally:
        cursor.close()
        conn.close()

    if len(results) == 1:
        return jsonify({
            'record_time': results[0][0].strftime("%Y-%m-%d %H:%M:%S"),
            'value': results[0][1],
            'remark': results[0][2],
        })
    elif len(results) == 0:
        return jsonify({
            'record_time': None,
            'value': None,
            'remark': None,
        })
    else:
        return Response('内部错误', 500)


@app.route('/get-data/', methods=['GET'])
def get_data():
    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)
    
    days = -1
    try:
        days = int(request.args.get('days')) - 1
        value_type = str(request.args.get('value_type'))
    except Exception as ex:
        return Response('参数错误', 400)
    if days <= 0 or days >= 3650:
        days = 3650

    try:
        conn = pymysql.connect(db_url, db_username, db_password, db_name)
        sql = '''
        SELECT `record_time`, `value` AS value_raw, `remark`
        FROM `user_data`
        WHERE `username` = %s AND
            `value_type` = %s AND
            (`record_time` >= (DATE(NOW()) - INTERVAL %s DAY))
        ORDER BY `record_time` ASC
        '''
        df = pd.read_sql(sql,
                        con=conn,
                        params=[username, value_type, days])
    except Exception as ex:
        return Response('数据库错误', 500)
    finally:
        conn.close()

    span =  int(df.shape[0] / 5)
    if span < 1:
        span = 1
    df.loc[:,'value_ema'] = df['value_raw'].ewm(span=span, adjust=False).mean().round(2)
    record_times, values_raw, values_ema, remarks = [], [], [], []
    for index, row in df.iterrows():
        record_times.append(row['record_time'].strftime("%Y-%m-%d %H:%M:%S"))
        values_raw.append(row['value_raw'])
        values_ema.append(row['value_ema'])
        remarks.append(row['remark'])

    reference_value = -1
    if settings['users'][username]['gender'] in settings['items'][value_type]['reference_value']:
        reference_value = settings['items'][value_type]['reference_value'][settings['users'][username]['gender']]

    return jsonify({
        "record_times": record_times,
        "values_raw": values_raw,
        "values_ema": values_ema,
        "remarks": remarks,
        "reference_value": reference_value
    })


def generate_stat_table(username, value_type):

    table_html = """
    <table class="w3-table w3-striped w3-bordered w3-hoverable">
      <tr class="w3-blue">
        <th>时间跨度</th><th>测量次数</th><th>平均值</th><th>变动</th>
      </tr>
    """

    denominators = [7, 30, 120, 365, 730, 1826, 3652]
    denominators_names = ['1周', '1月', '4月', '1年', '2年', '5年', '10年']
    _, today_weight = get_average_value(username, value_type, 1)
    for i in range(len(denominators)):
        entry_count, average_value = get_average_value(username, value_type, denominators[i])
        table_html += '<tr class="w3-hover-blue">'
        table_html += f'<td class="w3-border">{denominators_names[i]}</td>'
        table_html += f'<td class="w3-border">{entry_count}</td>'
        table_html += f'<td class="w3-border">{average_value:.1f}</td>'

        if average_value != 0:
            change = (today_weight - average_value) * 1000 / average_value
            if change > 0:
                change_html = '<span class="w3-text-red">{:+.0f}‰</span>'.format(change)
            elif change < 0:
                change_html = '<span class="w3-text-green">{:+.0f}‰</span>'.format(change)
            elif change == 0:
                change_html = '0‰'
            else:
                change_html = 'nan‰'
        else:
            change_html = 'nan‰'
        table_html += f'<td class="w3-border"><b>{change_html}</b></td>'
        table_html += '</tr>'
    table_html += '</table>'

    return table_html


@app.route('/summary/', methods=['GET'])
def summary():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return redirect(f'{app_address}/login/')

    try:
        value_type = str(request.args.get('value_type'))
        if value_type not in settings['items']:
            raise ValueError('')
            # the program will work even without this check
    except Exception as ex:
        return Response('参数错误', 400)

    kwargs = {
        'app_address': app_address,
        'mode': 'dev' if debug_mode else 'prod',
        'stat_table': generate_stat_table(username, value_type),
        'username': username,
        'telemetry_url': settings['app']['telemetry_url'],
        'value_type': value_type
        }

    return flask.render_template('summary.html', **kwargs)


def cleanup(*args):

    global stop_signal
    stop_signal = True
    logging.info('Stop signal received, exiting')
    sys.exit(0)


def main():

    ap = argparse.ArgumentParser()
    ap.add_argument('--debug', dest='debug', action='store_true')
    args = vars(ap.parse_args())
    global debug_mode
    debug_mode = args['debug']

    global db_url, db_username, db_password, db_name
    global app_address, settings
    with open(os.path.join(app_dir, 'settings.json'), 'r') as json_file:
        json_str = json_file.read()
        settings = json.loads(json_str)

    db_url = settings['db']['url']
    db_username = settings['db']['username']
    db_password = settings['db']['password']
    db_name = settings['db']['name']

    app.secret_key = settings['app']['secret_key']
    app_address = settings['app']['app_address']
    # secret_key must be the same if the server is shared by more than one service!
    logging.basicConfig(
        filename=settings['app']['log_path'],
        level=logging.DEBUG if debug_mode else logging.INFO,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    logging.info('weight manager started')
    start_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if debug_mode is True:
        print('Running in debug mode')
        logging.info('Running in debug mode')
        print(settings)
    else:
        logging.info('Running in production mode')

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    emailer = importlib.machinery.SourceFileLoader(
                    'emailer',
                    settings['email']['path']
                ).load_module()
    th_email = threading.Thread(target=emailer.send_service_start_notification,
                                kwargs={'settings_path': os.path.join(app_dir, 'settings.json'),
                                        'service_name': app_name,
                                        'path_of_logs_to_send': settings['app']['log_path'],
                                        'delay': 0 if debug_mode else 300})
    th_email.start()

    logging.info('Health Manager started')

    serve(app, host='0.0.0.0', port=90)


if __name__ == '__main__':

    main()
