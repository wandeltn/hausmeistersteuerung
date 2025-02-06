import functools
import logging
from math import floor
from typing import Union

from homeassistant.exceptions import IntegrationError
from homeassistant.util.color import color_RGB_to_hsv, color_hsv_to_RGB, rgbww_to_color_temperature

log = logging.getLogger(__name__)

allowed_chars_per_type = {
    "fixed": "",
    "binary": "",
    "dimmer": "d",
    "color_temp": "dcChHtT",
    "rgb": "drRgGbBuUwW",
    "rgbw": "drRgGbBuUwW",
    "rgbww": "dcChHtTrRgGbBuU"
}


def validate(channel_setup: Union[str, list], type: str):
    allowed_chars = allowed_chars_per_type[type]
    for channel in channel_setup:
        if (isinstance(channel, str) and not (channel in allowed_chars)) and (not isinstance(channel, int)):
            raise IllegalChannelSetup(f"The letter '{channel}' is not allowed for type {type}")


def _default_calculation_function(channel_value):
    return channel_value if isinstance(channel_value, int) else 0


def to_values(channel_setup: str, channel_size: int, is_on: bool = True, brightness: int = 255, red: int = -1,
              green: int = -1, blue: int = -1, cold_white: int = -1, warm_white: int = -1,
              color_temp_kelvin: int | None = None, min_kelvin: int | None = None, max_kelvin: int | None = None
              ) -> list[int]:

    if min_kelvin is not None and max_kelvin is not None:
        kelvin_diff = (max_kelvin - min_kelvin)

        if cold_white == -1 and warm_white == -1 and color_temp_kelvin is not None:
            cold_white = 255 * (color_temp_kelvin - min_kelvin) / kelvin_diff
            warm_white = 255 - cold_white
        elif cold_white != -1 and warm_white != -1 and color_temp_kelvin is None:
            color_temp_kelvin, _ = rgbww_to_color_temperature((red, green, blue, cold_white, warm_white), min_kelvin, max_kelvin)

    max_color = max(1, max(red, green, blue, cold_white, warm_white))

    # d = dimmer
    # r = red (scaled for brightness)
    # R = red (not scaled)
    # g = green (scaled for brightness)
    # G = green (not scaled)
    # b = blue (scaled for brightness)
    # B = blue (not scaled)
    # w = white (automatically calculated, scaled for brightness)
    # W = white (automatically calculated, not scaled)
    # c = cool (scaled for brightness)
    # C = cool (not scaled)
    # h = hot (scaled for brightness)
    # H = hot (not scaled)
    # t = temperature (0 = hot, 255 = cold)
    # T = temperature (255 = hot, 0 = cold)
    # u = hue
    # U = saturation
    switcher = {
        "d": lambda: brightness,
        "r": lambda: is_on * red * brightness / max_color,
        "R": lambda: is_on * red * 255 / max_color,
        "g": lambda: is_on * green * brightness / max_color,
        "G": lambda: is_on * green * 255 / max_color,
        "b": lambda: is_on * blue * brightness / max_color,
        "B": lambda: is_on * blue * 255 / max_color,
        "w": lambda: is_on * cold_white * brightness / max_color,
        "W": lambda: is_on * cold_white * 255 / max_color,
        "c": lambda: is_on * cold_white * brightness / max_color,
        "C": lambda: is_on * cold_white * 255 / max_color,
        "h": lambda: is_on * warm_white * brightness / max_color,
        "H": lambda: is_on * warm_white * 255 / max_color,
        "t": lambda: (color_temp_kelvin - min_kelvin) * 255 / kelvin_diff,
        "T": lambda: 255 - (color_temp_kelvin - min_kelvin) * 255 / kelvin_diff,
        "u": lambda: color_RGB_to_hsv(red, green, blue)[0] * 255 / 360,
        "U": lambda: color_RGB_to_hsv(red, green, blue)[1] * 255 / 100,
    }

    values: list[int] = list()
    for channel in channel_setup:
        calculation_function = switcher.get(channel, functools.partial(_default_calculation_function, channel))
        value = floor(calculation_function())
        if not (0 <= value <= 255):
            log.warning(f"Value for channel {channel} isn't within bound: {value}")
            value = max(0, min(255, value))

        values.append(int(round(value * channel_size)))

    return values


def from_values(channel_setup: str, channel_size: int, values: list[int],
                min_kelvin: int | None = None, max_kelvin: int | None = None):
    assert len(channel_setup) == len(values)

    brightness: int | None = None
    red: int | None = None
    green: int | None = None
    blue: int | None = None
    hue: int | None = None
    saturation: int | None = None
    cold_white: int | None = None
    warm_white: int | None = None
    color_temp_kelvin: int | None = None

    # Find brightness
    for index, channel in enumerate(channel_setup):
        value = values[index]

        if channel == "d":
            brightness = value
            break

        elif channel in "rgbwch":
            if brightness is None or value > brightness:
                brightness = value

    if brightness is None:
        brightness = 255
    else:
        brightness = floor(brightness / channel_size)

    is_on = brightness > 0

    # Get values
    for index, channel in enumerate(channel_setup):
        value = floor(values[index] / channel_size)

        if channel == "r":
            red = _scale_brightness(value, brightness)
        elif channel == "R":
            red = value
        elif channel == "g":
            green = _scale_brightness(value, brightness)
        elif channel == "G":
            green = value
        elif channel == "b":
            blue = _scale_brightness(value, brightness)
        elif channel == "B":
            blue = value
        elif channel in "wc":
            cold_white = _scale_brightness(value, brightness)
        elif channel in "WC":
            cold_white = value
        elif channel == "h":
            warm_white = _scale_brightness(value, brightness)
        elif channel == "H":
            warm_white = value
        elif channel == "t":
            cold_white = value
        elif channel == "T":
            warm_white = value
        elif channel == "u":
            hue = int(value * 360 / 255)
        elif channel == "U":
            saturation = int(value * 100 / 255)

    if cold_white is None and warm_white is not None:
        cold_white = 255 - warm_white
    elif cold_white is not None and warm_white is None:
        warm_white = 255 - cold_white

    if min_kelvin is not None and max_kelvin is not None:
        white_sum = cold_white + warm_white
        if white_sum == 0:
            color_temp_kelvin = round((min_kelvin + max_kelvin) / 2)
        else:
            cold_ratio = cold_white / (white_sum)
            color_temp_kelvin = round(min_kelvin - min_kelvin * cold_ratio + max_kelvin * cold_ratio)

    if hue is not None and saturation is not None and red is None and green is None and blue is None:
        red, green, blue = color_hsv_to_RGB(hue, saturation, 1)

    return is_on, brightness, red, green, blue, cold_white, warm_white, color_temp_kelvin


def _scale_brightness(value: int | None, brightness: int) -> int | None:
    if value is not None:
        if brightness == 0:
            return value
        else:
            return round(value * 255 / brightness)


class IllegalChannelSetup(IntegrationError):
    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason

    def __str__(self) -> str:
        return self.reason
