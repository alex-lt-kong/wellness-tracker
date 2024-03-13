from flask import Response, request, redirect, session
from hashlib import sha256
from waitress import serve


import business_logic as bl
import datetime as dt
import data_access as da
import flask
import global_vars as gv
import plugins_router as pgr


app = flask.Flask(__name__)
advertised_address = ''


@app.route('/', methods=['GET'])
def index():

    kwargs = {
        'advertised_address': advertised_address,
        'cdn_address': gv.settings['app']['cdn_address'],
        'username': request.authorization.username
    }

    return flask.make_response(
        flask.render_template('record.html', **kwargs))


@app.route('/get-available-items/', methods=['GET'])
def get_available_items():

    return {"data": gv.settings['items']}


@app.route('/submit-data/', methods=['POST'])
def submit_data():

    try:
        value = float(request.form['value'])
        value_type = str(request.form['value_type'])
        remark = str(request.form['remark'])
    except Exception:
        return Response('Invalid parameters/参数错误 (/submit-data/)', 400)
    if value_type not in gv.settings['items'].keys():
        return Response('value_type不在允许列表内', 400)

    bl.submit_data(request.authorization.username, value_type, value, remark)
    return Response('数据写入成功', 200)


@app.route('/get-latest-data/', methods=['GET'])
def get_latest_data():
    # Can we combine bl.get_latest_data() and bl.get_data_by_duration()?
    # Answer is NO.
    # bl.get_data_by_duration() returns data from the past N days,
    # if there is no data, it returns an empty set.
    # bl.get_latest_data() returns the latest data, no matter how far ago
    # that data is.
    # Using bl.get_data_by_duration() to achieve the function of
    # bl.get_latest_data() means we need to set N to a very large number,
    # which is not a good idea.

    try:
        value_type = str(request.args.get('value_type'))
    except Exception:
        return Response('Invalid parameters/参数错误 (/get-latest-data/)', 400)

    return flask.jsonify(bl.get_latest_data(request.authorization.username, value_type))


@app.route('/get-data-by-duration/', methods=['GET'])
def get_data_by_duration():

    days = -1
    try:
        days = int(str(request.args.get('days'))) - 1
        value_type = str(request.args.get('value_type'))
    except Exception:
        return Response(
            'Invalid parameters/参数错误 (/get-data-by-duration/)', 400)
    if days <= 0 or days >= 3650:
        days = 3650

    return flask.jsonify(bl.get_data_by_duration(days, request.authorization.username, value_type))


def generate_stats_table(username, value_type):

    table_html = """
    <table class="w3-table w3-striped w3-bordered w3-hoverable">
      <tr class="w3-blue">
        <th>Duration<br>时间跨度</th>
        <th>Measurements<br>测量次数</th><th>Avg. Value<br>平均值</th>
        <th>Change<br>变动</th>
      </tr>
    """

    denominators = [7, 30, 120, 365, 730, 1826, 3652]
    denominators_names = [
        '1w/1周', '1m/1月', '4m/4月', '1y/1年', '2y/2年', '5y/5年', '10y/10年'
    ]
    values_raw = bl.get_latest_data(username, value_type).values_raw
    latest_value = values_raw[0] if len(values_raw) > 0 else None
    for i in range(len(denominators)):
        entry_count, average_value = da.get_average_value(
            username, value_type, denominators[i])
        table_html += '<tr class="w3-hover-blue">'
        table_html += f'<td class="w3-border">{denominators_names[i]}</td>'
        table_html += f'<td class="w3-border">{entry_count}</td>'
        table_html += (f'<td class="w3-border">{average_value:.1f}</td>'
                       if isinstance(average_value, float) else
                       '<td class="w3-border">NA</td>')
        if (average_value is not None and latest_value is not None
                and average_value != 0 and entry_count > 0):
            change = (latest_value - average_value) * 1000 / average_value
            if change > 0:
                change_html = f'<span class="w3-text-red">{change:+.0f}‰</span>'
            elif change < 0:
                change_html = f'<span class="w3-text-green">{change:+.0f}‰</span>'
            else:
                change_html = '0‰'
        else:
            change_html = 'nan‰'
        table_html += f'<td class="w3-border"><b>{change_html}</b></td>'
        table_html += '</tr>'
    table_html += '</table>'

    return table_html


@app.route('/summary/', methods=['GET'])
def summary():
    username = request.authorization.username
    try:
        value_type = str(request.args.get('value_type'))
        if value_type not in gv.settings['items']:
            raise ValueError('')
            # the program will work even without this check
    except Exception:
        return Response('''
        <p>data type unspecified/数据类型未指定</p>
        <p><a href="../">
            Click here to return to record page/点此返回记录页
        </a></p>
        ''', 400)

    plugin_html = ''
    try:
        plugin_html = pgr.plugins_router[username][value_type](
            username, value_type)
    except KeyError:
        pass
    kwargs = {
        'advertised_address': advertised_address,
        'stats_table': generate_stats_table(username, value_type),
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
    # advertised_address: the app's address (including protocol and port) on
    # the Internet
    advertised_address = gv.settings['app']['advertised_address']

    da.prepare_database()
    serve(app, host=gv.settings['app']['host'], port=gv.settings['app']['port'])
