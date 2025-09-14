from pydantic import BaseModel
class DateTimeResponse(BaseModel):
    utc_datetime: str
    utc_timestamp: float
    utc_Y: int
    utc_m: int
    utc_d: int
    utc_H: int
    utc_M: int
    utc_S: int
    utc_microsecond: int
    timezone: str = "UTC"
    iso_format: str