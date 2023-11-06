from flask import Response, request, redirect, session
from hashlib import sha256
from waitress import serve


import business_logic as bl
import datetime as dt
import data_access as da
import flask
import global_vars as gv
import plugins as pg
import plugins_router as pgr


app = flask.Flask(__name__)
advertised_address = ''


@app.route('/logout/')
def logout():
    if gv.app_name in session:
        session[gv.app_name].pop('username', None)
    return redirect(f'{advertised_address}/')


@app.before_request
def make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = dt.timedelta(days=365)


@app.route('/login/', methods=['GET', 'POST'])
def login():

    if gv.app_name in session and 'username' in session[gv.app_name]:
        return redirect(f'{advertised_address}/')

    kwargs = {
        'advertised_address': advertised_address
    }
    if request.method == 'POST':

        username = request.form['username']
        kwargs['username'] = username

        if request.form['username'] not in gv.settings['users']:
            kwargs['err_msg'] = f'错误：用户[{username}]不存在'
            return flask.render_template('login.html', **kwargs)
        if (sha256(request.form['password'].encode('utf-8')).hexdigest() !=
                gv.settings['users'][username]['password_hash']):
            kwargs['err_msg'] = '错误：密码错误'
            return flask.render_template('login.html', **kwargs)

        session[gv.app_name] = {}
        session[gv.app_name]['username'] = username
        return redirect(f'{advertised_address}/')

    return flask.render_template('login.html', **kwargs)


@app.route('/', methods=['GET'])
def index():

    if gv.app_name in session and 'username' in session[gv.app_name]:
        username = session[gv.app_name]['username']
    else:
        return redirect(f'{advertised_address}/login/')

    kwargs = {
        'advertised_address': advertised_address,
        'cdn_address': gv.settings['app']['cdn_address'],
        'username': username
    }

    return flask.make_response(
        flask.render_template('record.html', **kwargs))


@app.route('/get-available-items/', methods=['GET'])
def get_available_items():
    if gv.app_name in session and 'username' in session[gv.app_name]:
        _ = session[gv.app_name]['username']
    else:
        return Response('User not logged in/用户未登录', 401)

    return {"data": gv.settings['items']}


@app.route('/submit-data/', methods=['POST'])
def submit_data():
    if gv.app_name in session and 'username' in session[gv.app_name]:
        username = session[gv.app_name]['username']
    else:
        return Response('User not logged in/用户未登录', 401)

    try:
        value = float(request.form['value'])
        value_type = str(request.form['value_type'])
        remark = str(request.form['remark'])
    except Exception:
        return Response('Invalid parameters/参数错误 (/submit-data/)', 400)
    if value_type not in gv.settings['items'].keys():
        return Response('value_type不在允许列表内', 400)

    bl.submit_data(username, value_type, value, remark)
    return Response('数据写入成功', 200)


@app.route('/get-latest-data/', methods=['GET'])
def get_latest_data():
    # It turns out that combining get_data_by_duration() and
    # get_latest_data() is NOT a good idea since there are a few differences..
    if gv.app_name in session and 'username' in session[gv.app_name]:
        username = session[gv.app_name]['username']
    else:
        return Response('User not logged in/用户未登录', 401)

    try:
        value_type = str(request.args.get('value_type'))
    except Exception:
        return Response('Invalid parameters/参数错误 (/get-latest-data/)', 400)

    return flask.jsonify(bl.get_latest_data(username, value_type))


@app.route('/get-data-by-duration/', methods=['GET'])
def get_data_by_duration():
    if gv.app_name in session and 'username' in session[gv.app_name]:
        username = session[gv.app_name]['username']
    else:
        return Response('User not logged in/用户未登录', 401)
    days = -1
    try:
        days = int(str(request.args.get('days'))) - 1
        value_type = str(request.args.get('value_type'))
    except Exception:
        return Response(
            'Invalid parameters/参数错误 (/get-data-by-duration/)', 400)
    if days <= 0 or days >= 3650:
        days = 3650

    return flask.jsonify(bl.get_data_by_duration(days, username, value_type))


def generate_stat_table(username, value_type):

    table_html = """
    <table class="w3-table w3-striped w3-bordered w3-hoverable">
      <tr class="w3-blue">
        <th>时间跨度</th><th>测量次数</th><th>平均值</th><th>变动</th>
      </tr>
    """

    denominators = [7, 30, 120, 365, 730, 1826, 3652]
    denominators_names = ['1周', '1月', '4月', '1年', '2年', '5年', '10年']
    _, today_weight = da.get_average_value(username, value_type, 1)
    for i in range(len(denominators)):
        entry_count, average_value = da.get_average_value(
            username, value_type, denominators[i])
        table_html += '<tr class="w3-hover-blue">'
        table_html += f'<td class="w3-border">{denominators_names[i]}</td>'
        table_html += f'<td class="w3-border">{entry_count}</td>'
        table_html += f'<td class="w3-border">{average_value:.1f}</td>'

        if average_value != 0:
            change = (today_weight - average_value) * 1000 / average_value
            if change > 0:
                change_html = f'<span class="w3-text-red">{change:+.0f}‰</span>'
            elif change < 0:
                change_html = f'<span class="w3-text-green">{change:+.0f}‰</span>'
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

    if gv.app_name in session and 'username' in session[gv.app_name]:
        username = session[gv.app_name]['username']
    else:
        return redirect(f'{advertised_address}/login/')

    try:
        value_type = str(request.args.get('value_type'))
        if value_type not in gv.settings['items']:
            raise ValueError('')
            # the program will work even without this check
    except Exception:
        return Response('Invalid parameters/参数错误', 400)

    plugin_html = ''
    try:
        plugin_html = pgr.plugins_router[username][value_type](
            username, value_type)
    except KeyError:
        pass
    kwargs = {
        'advertised_address': advertised_address,
        'stat_table': generate_stat_table(username, value_type),
        'plugin_html': plugin_html,
        'username': username,
        'value_type': value_type,
        'cdn_address': gv.settings['app']['cdn_address']
    }

    return flask.render_template('summary.html', **kwargs)


def start_http_service():

    global app, advertised_address
    app.config['JSON_AS_ASCII'] = False
    app.json.sort_keys = False  # type: ignore
    app.config.update(
        # SESSION_COOKIE_SECURE=True means we accept HTTPS connections only
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_HTTPONLY=True,
        # If this is set to True, client-side JavaScript will not be able to
        # access the session cookie.
        SESSION_COOKIE_SAMESITE='Lax',
    )
    # secret_key must be the same if the server is
    # shared by more than one service!
    app.secret_key = gv.settings['app']['secret_key']
    # advertised_address: the app's address (including protocol and port) on
    # the Internet
    advertised_address = gv.settings['app']['advertised_address']

    da.prepare_database()
    serve(app, host=gv.settings['app']['host'], port=gv.settings['app']['port'])