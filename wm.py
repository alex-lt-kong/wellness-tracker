#!/usr/bin/python3

from flask import Flask, render_template, Response,request, redirect, session
from flask import send_file, jsonify
from flask_cors import CORS
from hashlib import sha256
from sqlalchemy import create_engine, text
from waitress import serve

import argparse
import datetime as dt
import json
import logging
import numpy as np
import os
import pandas as pd
import pymysql
import signal
import smtplib
import sys
import threading
import time


app = Flask(__name__)
app.secret_key = b''
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    # If this is set to True, client-side JavaScript will not be able to
    # access the session cookie.
    SESSION_COOKIE_SAMESITE='Lax',
)


CORS(app)
# This necessary for javascript to access a telemetry link without opening it:
# https://stackoverflow.com/questions/22181384/javascript-no-access-control-allow-origin-header-is-present-on-the-requested
stop_signal = False
app_address = ''
app_path = '/root/bin/weight-manager'
debug_mode = False
settings_path = f'{app_path}/settings.json'
users_path = f'{app_path}/users.json'
plots_path = f'{app_path}/plots'
app_name = 'weight_manager'

db_url = ''
db_username = ''
db_password = ''
db_name = ''


def get_average_weight(username: str, days: int):

    conn = pymysql.connect(db_url, db_username, db_password, db_name)
    cursor = conn.cursor()
    sql = '''
    SELECT COUNT(`value`), AVG(`value`)
    FROM `weights`
    WHERE (`record_time` between (NOW() - INTERVAL %s DAY ) and NOW()) AND
         `username` = %s'''
    cursor.execute(sql, (days, username))
    results = cursor.fetchall()

    if results is not None:
        entry_count = results[0][0]
    else:
        entry_count = 0
    if entry_count > 0:
        average_weight = results[0][1]
    else:
        average_weight = np.nan

    return entry_count, average_weight


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

    if request.method == 'POST':

        username = request.form['username']
        try:
            with open(users_path, 'r') as json_file:
                json_str = json_file.read()
                json_data = json.loads(json_str)
        except Exception as ex:
            return render_template('login.html', err_msg=f'错误：{str(ex)}')
        if request.form['username'] not in json_data['users']:
            return render_template('login.html',
                                   err_msg=f'错误：用户{username}不存在')
        if (sha256(request.form['password'].encode('utf-8')).hexdigest() !=
                json_data['users'][username]):
            return render_template('login.html', err_msg='错误：密码错误')

        session[f'{app_name}'] = {}
        session[f'{app_name}']['username'] = username
        print(session)
        return redirect(f'{app_address}/')

    return render_template('login.html', err_msg='')


@app.route('/', methods=['GET'])
def index():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return redirect(f'{app_address}/login/')

    if 'weight_today' not in request.args:
        return render_template('record.html', username=username)

    try:
        weight_today = float(request.args.get('weight_today'))
        remark = request.args.get('remark')
    except:
        return('输入的不是数字！请重新输入！（注意检查中英文标点）')

    current_time = dt.datetime.now()
    if current_time.minute < 30:
        current_time = current_time.replace(microsecond=0, second=0, minute=0)
    else:
        current_time = current_time.replace(microsecond=0, second=0, minute=30)

    conn = pymysql.connect(db_url, db_username, db_password, db_name)
    conn.autocommit(True) # It appears that both UPDATE and SELECT need "commit"
    cursor = conn.cursor()
    sql = 'SELECT `id`, `record_time`, `value` FROM `weights` WHERE `record_time` = %s AND `username` = %s'
    cursor.execute(sql, (current_time, username))
    results = cursor.fetchall()
    if len(results) > 0:
        sql = 'UPDATE `weights` SET `value` = %s, `remark` = %s WHERE `record_time` = %s AND `username` = %s'
        cursor.execute(sql, (weight_today, remark, current_time, username))
    else:
        sql = 'INSERT INTO `weights` (`record_time`, `username`, `value`, `value_type`, `remark`) VALUES (%s, %s, %s, %s, %s)'
        cursor.execute(sql, (current_time, username, weight_today, 'weight', remark))
    cursor.close()

    return redirect(f'{app_address}/summary/')


@app.route('/get-latest-data/', methods=['GET'])
def get_latest_data():
    # It turns out that combining get_data() and get_latest_data() is NOT
    # a good idea since there are a few differences..
    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)

    db_error = False
    try:
        conn = pymysql.connect(db_url, db_username, db_password, db_name)
        conn.autocommit(True) # It appears that both UPDATE and SELECT need "commit"
        cursor = conn.cursor()
        sql = """
            SELECT `record_time`, `value`, `remark`
            FROM `weights`
            WHERE `username` = %s AND `value_type` = %s
            ORDER BY `record_time` DESC
            LIMIT 1"""
        cursor.execute(sql, (username, "weight"))
        results = cursor.fetchall()
    except Exception as ex:
        logging.error('Database operation error: {ex}')
        db_error = True
    finally:
        cursor.close()
        conn.close()
    
    if db_error:
        return Response('数据库错误', 500)

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

    db_conn_str = f'mysql+pymysql://{db_username}:{db_password}@{db_url}/{db_name}'
    db_conn = create_engine(db_conn_str)
    sql = text('''
    SELECT `record_time`, `value` AS value_raw, `remark`
    FROM `weights`
    WHERE `username` = :username AND
          (`record_time` >= (DATE(NOW()) - INTERVAL :days DAY))
    ORDER BY `record_time` DESC
    ''')
    df = pd.read_sql(sql,
                    con=db_conn,
                    params={'username': username, 'days': days})

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

    return jsonify({
        "record_times": record_times,
        "values_raw": values_raw,
        "values_ema": values_ema,
        "remarks": remarks
    })


def generate_stat_table(username):

    table_html = """
    <table class="w3-table w3-striped w3-bordered w3-hoverable">
      <tr class="w3-blue">
        <th>时间跨度</th><th>测量次数</th><th>平均体重</th><th>变动</th>
      </tr>
    """

    denominators = [7, 30, 120, 365, 730, 1461]
    denominators_names = ['1周', '1月', '4月', '1年', '2年', '4年']
    _, today_weight = get_average_weight(username, 1)
    for i in range(len(denominators)):
        entry_count, average_weight = get_average_weight(username, denominators[i])
        table_html += '<tr class="w3-hover-blue">'
        table_html += f'<td class="w3-border">{denominators_names[i]}</td>'
        table_html += f'<td class="w3-border">{entry_count}</td>'
        table_html += f'<td class="w3-border">{average_weight:.1f}</td>'

        if average_weight != 0:
            change = (today_weight - average_weight) * 1000 / average_weight
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

    print(session)
    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return redirect(f'{app_address}/login/')

    kwargs = {
        'app_address': app_address,
        'mode': 'dev' if debug_mode else 'prod',
        'stat_table': generate_stat_table(username),
        'username': username
        }

    return render_template('summary.html', **kwargs)

def cleanup(*args):

    global stop_signal
    stop_signal = True
    logging.info('Stop signal received, exiting')
    sys.exit(0)


def send_notification_email(delay: int, from_name: str, subject: str, mainbody: str):

    global stop_signal

    logging.info('Wait for {} seconds before sending the email'.format(delay))
    sec_count = 0
    while sec_count < delay:
        time.sleep(1)  # This delay has to be long enough to accommodate the startup time of pfSense.
        sec_count += 1
        if stop_signal:
            return
    logging.debug('Sending [{}] notification email'.format(subject))

    try:
        with open(settings_path, 'r') as json_file:
            json_str = json_file.read()
            json_data = json.loads(json_str)
    except:
        json_data = None
        logging.error(sys.exc_info())

    sender = json_data['email']['address']
    password = json_data['email']['password']
    receivers = ['admin@mamsds.net']

    message = ('From: {} <{}>\n'
                'To: Mamsds Admin Account <admin@mamsds.net>\n'
                'Content-Type: text/html; charset="UTF-8"\n'
                'Subject: {}\n'
                '<meta http-equiv="Content-Type"  content="text/html charset=UTF-8" /><html><font size="2" color="black">{}</font></html>'.format(from_name, sender, subject, mainbody.replace('\n', '<br>')))

    try:
        smtpObj = smtplib.SMTP(host='server172.web-hosting.com', port=587)
        smtpObj.starttls()
        smtpObj.login(sender, password)
        smtpObj.sendmail(sender, receivers, message.encode('utf-8'))
        smtpObj.quit()
        logging.debug("Email [{}] sent successfully".format(subject))
    except:
        logging.error("{}".format(sys.exc_info()))


def main():

    ap = argparse.ArgumentParser()
    ap.add_argument('--debug', dest='debug', action='store_true')
    args = vars(ap.parse_args())
    global debug_mode
    debug_mode = args['debug']

    with open(settings_path, 'r') as json_file:
        json_str = json_file.read()
        json_data = json.loads(json_str)

    global db_url, db_username, db_password, db_name
    global app_address
    db_url = json_data['db']['url']
    db_username = json_data['db']['username']
    db_password = json_data['db']['password']
    db_name = json_data['db']['name']

    app.secret_key = json_data['app']['secret_key']
    app_address = json_data['app']['app_address']
    # secret_key must be the same if the server is shared by more than one service!
    print(app.secret_key)
    logging.basicConfig(
        filename='/var/log/mamsds/weight-manager.log',
        level=logging.DEBUG if debug_mode else logging.INFO,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    logging.info('weight manager started')
    start_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if debug_mode is True:
        print('Running in debug mode')
        logging.info('Running in debug mode')
    else:
        logging.info('Running in production mode')

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    email_sender = threading.Thread(target=send_notification_email,
                                    args=(0 if debug_mode else 600, 'weight manager notification service', 'weight manager started', f'weight manager is started at {start_time}'))
    email_sender.start()
    logging.info('weight manager server')

    serve(app, host='0.0.0.0', port=90)


if __name__ == '__main__':

    main()
