from abc import ABC, abstractmethod

import business_logic as bl
import datetime as dt
import global_vars as gv


class PluginBase(ABC):
    @staticmethod
    @abstractmethod
    def render(username: str, value_type: str) -> str:
        raise NotImplementedError("")


class BMI(PluginBase):
    @staticmethod
    def render(username: str, value_type: str):
        weight_kg = bl.get_latest_data(username, value_type).values_raw
        if (len(weight_kg) == 0):
            return "<p>BMI:&nbsp;NA, weight not available/没有体重数据</p>"
        try:
            height_cm = gv.settings['users'][username]['height_cm']
            bmi = round(weight_kg[0] / ((height_cm / 100.0) ** 2), 1)
            # reference: https://www.chp.gov.hk/en/resources/e_health_topics/pdfwav_11012.html
            if bmi < 18.5:
                nutritional_status = 'Underweight/过轻'
            elif bmi < 22.9:
                nutritional_status = 'Normal weight/适中'
            elif bmi < 24.9:
                nutritional_status = 'Overweight/过重'
            else:
                nutritional_status = 'Obese/肥胖'
            normal_weight_range = [round(18.5 * ((height_cm / 100.0) ** 2), 1),
                                   round(22.9 * ((height_cm / 100.0) ** 2), 1)]
            return f'''
                <p style="text-align: center;">
                    BMI:&nbsp;{bmi} ({nutritional_status}).
                    Target range/目标区间: {normal_weight_range}kg
                </p>'''
        except Exception as ex:
            return f'<p style="text-align: center;">BMI:&nbsp;NA, {ex}</p>'


class AverageWeightGain(PluginBase):
    @staticmethod
    def render(username: str, value_type: str) -> str:
        data_points = 15
        dto = bl.get_data_by_duration(30, username, value_type)
        if len(dto.record_times) < data_points:
            data_points = len(dto.record_times)
        first_record_time = dt.datetime.strptime(
            dto.record_times[-1 * data_points], '%Y-%m-%d %H:%M:%S')
        last_record_time = dt.datetime.strptime(
            dto.record_times[-1], '%Y-%m-%d %H:%M:%S')
        days = (last_record_time - first_record_time).total_seconds() / (60 * 60 * 24)
        if days == 0:
            return '''
                <p style="text-align: center;">
                    Error: not enough data points[1]
                </p>
            '''
        weight_gain_grams = (dto.values_raw[-1] -
                             dto.values_raw[-1 * data_points]) * 1000
        dob = dt.datetime.strptime(gv.settings['users'][username]['dob'],
                                   '%Y-%m-%d')
        age_in_days = (
            dt.datetime.strptime(dto.record_times[-1], '%Y-%m-%d %H:%M:%S') -
            dob
        ).days
        target_weight_gain_per_day = 0
        if age_in_days < 90:
            target_weight_gain_per_day = int((5.8 - 3.2) / 90 * 1000)
        elif age_in_days < 180:
            target_weight_gain_per_day = int((7.3 - 5.8) / 90 * 1000)
        elif age_in_days < 270:
            target_weight_gain_per_day = int((8.2 - 7.3) / 90 * 1000)
        elif age_in_days < 360:
            target_weight_gain_per_day = int((8.9 - 8.2) / 90 * 1000)
        elif age_in_days < 720:
            target_weight_gain_per_day = int((11.5 - 9.8) / 360 * 1000)
        else:
            target_weight_gain_per_day = -1

        return f'''
            <p style="text-align: center;">
                Avg. weight gain over {int(days)} days:
                <b>{int(round(weight_gain_grams / days, 0))}g</b>.
                She is {age_in_days} days old and should gain
                <b>~{target_weight_gain_per_day}g</b> per day
                <br>
                过去{int(days)}日每日体重平均增加
                <b>{int(round(weight_gain_grams / days, 0))}克</b>。
                她现在{age_in_days}日大，每日体重应当增加
                <b>~{target_weight_gain_per_day}克</b>
            </p>
        '''
