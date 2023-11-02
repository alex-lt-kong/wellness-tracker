import data_access as da
import global_vars as gv
import http_service
import json
import logging
import os
import sys


def main():

    with open(os.path.join(gv.app_dir, 'settings.json'), 'r') as json_file:
        json_str = json_file.read()
        gv.settings = json.loads(json_str)

    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format=('%(asctime)s.%(msecs)03d %(levelname)s %(module)s - '
                '%(funcName)s: %(message)s'),
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    logging.info('Wellness Tracker started')
    da.prepare_database()
    http_service.start_http_service()
    logging.info('Wellness Tracker exited')


if __name__ == '__main__':

    main()
