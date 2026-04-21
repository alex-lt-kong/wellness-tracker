from typing import List
from dataclasses import dataclass


@dataclass
class DtoData:
    record_times: List[str]
    values_raw: List[float]
    values_ema: List[float]
    band_upper: List[float]
    band_lower: List[float]
    remarks: List[str]
    reference_value: float
