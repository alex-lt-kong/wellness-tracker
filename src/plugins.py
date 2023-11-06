from abc import ABC, abstractmethod

import business_logic as bl
import global_vars as gv


class PluginBase(ABC):
    @staticmethod
    @abstractmethod
    def render(username: str, value_type: str) -> str:
        raise NotImplementedError("")


class BMI(PluginBase):
    @staticmethod
    def render(username: str, value_type: str):
        weight_kg = bl.get_latest_data(username, value_type)['value']
        if (weight_kg is None or
                (isinstance(weight_kg, float) is False and
                 isinstance(weight_kg, int) is False)):
            return "<p>BMI:&nbsp;NA, weight not available</p>"
        try:
            height_cm = gv.settings['users'][username]['height_cm']
            bmi = round(weight_kg / ((height_cm / 100.0) ** 2), 1)
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
