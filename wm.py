#!/usr/bin/python3

from flask import Flask, render_template, Response,request, redirect, session
from flask import send_file, jsonify
from flask_cors import CORS
from hashlib import sha256
from scipy.stats import norm
from statsmodels.tsa.stattools import adfuller
from sqlalchemy import create_engine, text
from waitress import serve

import argparse
import datetime as dt
import json
import logging
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import pymysql
import scipy.stats as stats
import signal
import smtplib
import statsmodels.api as sm
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
relative_url = f'../{app_name}'

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


def get_today_weight(username: str):

    conn = pymysql.connect(db_url, db_username, db_password, db_name)
    cursor = conn.cursor()
    sql = '''
    SELECT `id`, `record_time`, `value`, `remark`
    FROM `weights`
    WHERE `record_time` >= CURDATE() AND `username` = %s
    ORDER BY record_time DESC LIMIT 1'''
    cursor.execute(sql, (username))
    results = cursor.fetchall()

    if len(results) == 1:
        today_weight = float(results[0][2])
        latest_record_time = results[0][1]
        remark = str(results[0][3])
    else:
        today_weight = np.nan
        latest_record_time = None
        remark = None

    return today_weight, latest_record_time, remark


@app.route('/logout/')
def logout():

    if f'{app_name}' in session:
        session[f'{app_name}'].pop('username', None)
    return redirect(f'{relative_url}/')


@app.before_request
def make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = dt.timedelta(days=365)


@app.route('/login/', methods=['GET', 'POST'])
def login():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        return redirect(f'{relative_url}/')

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
        return redirect(f'{relative_url}/')

    return render_template('login.html', err_msg='')


@app.route('/', methods=['GET'])
def index():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return redirect(f'{relative_url}/login/')

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

    return redirect(f'{relative_url}/summary/')


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

@app.route('/summary/', methods=['GET'])
def summary():

    print(session)
    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return redirect(f'{relative_url}/login/')

    today_weight, latest_record_time, remark = get_today_weight(username)

    if latest_record_time is None:
        latest_record_time = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    else:
        latest_record_time = latest_record_time.strftime('%Y-%m-%d %H:%M')

    weight_data = []

    denominators = [7, 30, 120, 365, 730, 1461]
    denominators_names = ['1周', '1月', '4月', '1年', '2年', '4年']

    for i in range(len(denominators)):
        entry_count, average_weight = get_average_weight(username, denominators[i])

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
        attendance_rate = '{:.0f}%'.format(entry_count * 100 / denominators[i])
        average_weight = '{:.1f}'.format(average_weight)
        weight_data.append([denominators_names[i], entry_count, attendance_rate, average_weight, change_html])
    kwargs = {
        'app_address': app_address,
        'mode': 'dev' if debug_mode else 'prod'
        }

    return render_template('summary.html',
                           username=username,
                           today_weight=today_weight,
                           remark=remark,
                           latest_record_time=latest_record_time,
                           weight_data=weight_data, **kwargs)


@app.route('/chart/', methods=['GET'])
def chart():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)

    days = -1
    try:
        days = int(request.args.get('days')) - 1
    except Exception as ex:
        pass
    if days <= 0 or days >= 3650:
        days = 3650

    db_conn_str = f'mysql+pymysql://{db_username}:{db_password}@{db_url}/{db_name}'
    db_conn = create_engine(db_conn_str)

    sql = text('''
    SELECT `record_time`, `value`, `remark`
    FROM `weights`
    WHERE `username` = :username AND
          (`record_time` >= (DATE(NOW()) - INTERVAL :days DAY))
    ORDER BY `record_time` DESC
    ''')
    df = pd.read_sql(sql, con=db_conn,
                     params={'username': username, 'days': days})

    df.sort_values('record_time', inplace=True)
    span =  int(df.shape[0] / 5)
    if span < 1:
        span = 1
    df.loc[:,'value_ema'] = df['value'].ewm(span=span, adjust=False).mean().round(2)

    readings_string = ['', '']
    times_string = ''
    remark_string = ''
    for index, row in df.iterrows():
        readings_string[0] += str(row['value']) + ','
        readings_string[1] += str(row['value_ema']) + ','
        times_string += '"' + str(row['record_time']) + '",'
        remark_string += '"' + str(row['remark']) + '",'
    readings_string[0] = readings_string[0][:-1]
    readings_string[1] = readings_string[1][:-1]
    times_string = times_string[:-1]
    remark_string = remark_string[:-1]

    kwargs = {
        'app_address': app_address,
        'mode': 'dev' if debug_mode else 'prod'
        }

    return render_template('chart.html',
                           times_string=times_string,
                           readings_strings=readings_string,
                           remark_string=remark_string,
                           **kwargs)


@app.route('/prediction/', methods=['GET'])
def prediction():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)

    days = -1
    try:
        days = int(request.args.get('days')) - 1
    except Exception as ex:
        ex = ex
    if days <= 0 or days >= 3650:
        days = 3650

    db_conn = create_engine(
            f'mysql+pymysql://{db_username}:{db_password}@{db_url}/{db_name}')

    sql = text('''
    SELECT `record_time`, `value`
    FROM `weights`
    WHERE `username` = :username AND
          (`record_time` >= (DATE(NOW()) - INTERVAL :days DAY))
    ORDER BY `record_time` DESC
    ''')
    df = pd.read_sql(sql=sql, con=db_conn, index_col='record_time',
                     params={'username': username, 'days': days})
    df.sort_values(by=['record_time'], ascending=[True], inplace=True)

    if df.shape[0] < 5:
        return '数据量太小，无预测结果'

    df['linear'] = df['value'] / df['value'].shift(1) - 1

    std = df['linear'].std()
    weighted_average = (df['value'].iloc[-1] * 0.6 +
                        df['value'].iloc[-2] * 0.3 +
                        df['value'].iloc[-3] * 0.1)

    predict_lower = weighted_average * (1 + df['linear'].mean() - 1 * std)
    predict_upper = weighted_average * (1 + df['linear'].mean() + 1 * std)

    return  (f'{predict_lower:.1f}-{predict_upper:.1f}')


@app.route('/get_plot/', methods=['GET'])
def get_plot():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)

    filename = request.args.get('filename')
    file_path = os.path.join(plots_path, f'{username}-{filename}')
    if os.path.commonprefix([os.path.realpath(file_path),
                             plots_path]) != plots_path:
        return ('非法参数！', 403)
    if os.path.isfile(file_path):
        return send_file(file_path, mimetype='image/png')
    else:
        return ('文件不存在', 400)


@app.route('/generate_statistics/', methods=['GET'])
def generate_statistics():

    if f'{app_name}' in session and 'username' in session[f'{app_name}']:
        username = session[f'{app_name}']['username']
    else:
        return Response('用户未登录', 401)

    days = -1
    try:
        days = int(request.args.get('days')) - 1
    except Exception as ex:
        ex = ex
        days = 3650
    if days <= 0 or days >= 3650:
        days = 3650

    db_conn = create_engine(
            f'mysql+pymysql://{db_username}:{db_password}@{db_url}/{db_name}')

    sql = text('''
    SELECT `record_time`, `value`
    FROM `weights`
    WHERE `username` = :username AND
          (`record_time` >= (DATE(NOW()) - INTERVAL :days DAY))
    ORDER BY `record_time` DESC
    ''')
    df = pd.read_sql(sql=sql, con=db_conn,
                     params={'username': username, 'days': days})
    df['record_time'] = pd.to_datetime(df['record_time'],
                                       format='%Y-%m-%d %H:%M:%S')
    df.sort_values(by=['record_time'], ascending=[True], inplace=True)
    df = df.set_index('record_time')
    if df.shape[0] < 5:
        return '数据量太小，无法分析'

    df['linear'] = df['value'] / df['value'].shift(1) - 1
    df['log'] = np.log(df['value']) - np.log(df['value'].shift(1))
    df = df.iloc[1:]
    df['log_normal'] = (df['log'] - df['log'].mean())/df['log'].std()

    fig, ax = plt.subplots(figsize=(5, 5))
    plt.title('Weight Change')
    plt.xlabel('Time')
    plt.ylabel('Standardized Log Weight Change')
    plt.hlines(y=df['log_normal'].mean(),
               xmin=df.index.values[0], xmax=df.index.values[df.shape[0]-1],
               color='r', linewidth=0.75, linestyles='--', label='Mean')
    plt.hlines(y=df['log_normal'].mean() - 2 * df['log_normal'].std(),
               xmin=df.index.values[0], xmax=df.index.values[df.shape[0]-1],
               color='g', linewidth=0.75, linestyles='--',
               label=f'Two Std (σ={df["log"].std()*100:.2f}%)')
    plt.hlines(y=df['log_normal'].mean() + 2 * df['log_normal'].std(),
               xmin=df.index.values[0], xmax=df.index.values[df.shape[0]-1],
               color='g', linewidth=0.75, linestyles='--')

    plt.legend()
    plt.plot(df['log_normal'])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(df.index.values[::int(len(df.index.values)/3)])
    plt.savefig(os.path.join(plots_path, f'{username}-log-change.png'))
    plt.close()

    fig, ax = plt.subplots(figsize=(5, 5))
    plt.title('Histogram of Weight Change Frequency')
    plt.xlabel('Standardized Log Weight Change')
    plt.ylabel('Probablity Density')
    _, bins, _ = plt.hist(df['log_normal'], bins=30, density=True)
    # You have to add density=True if want to overlay a normal distribution
    # curve over it.
    mu, sigma = norm.fit(df['log_normal'])
    y = stats.norm.pdf(bins, mu, sigma)
    plt.plot(bins, y, 'r--', linewidth=2,
             label='Best Fitting')
    plt.legend()
    plt.savefig(os.path.join(plots_path, f'{username}-histogram.png'))
    plt.close()

    fig, ax = plt.subplots(figsize=(5, 5))
    sm.qqplot(df['log_normal'], stats.norm, fit=True, line="45", ax=ax)
    plt.title('Quantile-Quantile Plot')
    plt.savefig(os.path.join(plots_path, f'{username}-qqplot.png'))
    plt.close()

    try:
        p_adf = adfuller(df['log_normal'])[1]
    except Exception as ex:
        ex = ex
        p_adf = 99
    _, p_shapiro = stats.shapiro(df['log_normal'])
    _, p_ks = stats.kstest(df['log_normal'], cdf='norm')
    test_html = f'Adfuller Test: p = {p_adf:.3f}'
    if p_adf > 0.05:
        test_html += ', > 0.05, sample <b>NOT</b> stationary'
    else:
        test_html += ' <= 0.05, sample is stationary'
    test_html += f'<br>Shapiro Test: p = {p_shapiro:.3f}'
    if p_shapiro > 0.05:
        test_html += ', > 0.05, sample looks Gaussian'
    else:
        test_html += ', <= 0.05, sample does <b>NOT</b> lool Gaussian'
    test_html += '<br>KS Test: p = {:.3f}'.format(p_ks)
    if p_ks > 0.05:
        test_html += ', > 0.05, sample looks Gaussian'
    else:
        test_html += ', <= 0.05, sample does <b>NOT</b> look Gaussian'

    # print(df['value'].iloc[-1], df['linear'].mean())

    return render_template('data-analysis.html', username=username,
                           test_html=test_html)


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
