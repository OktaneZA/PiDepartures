"""Operating hours helper.

Based on https://github.com/chrisys/train-departure-display — unchanged.
"""

from datetime import datetime, time


def is_time_between(begin_time, end_time, check_time=None):
    """Return True if check_time falls within the begin–end window.

    Handles midnight crossover (e.g. 22:00–06:00).

    Args:
        begin_time: Window start as datetime.time.
        end_time: Window end as datetime.time.
        check_time: Time to test; defaults to current local time.

    Returns:
        True if check_time is within the window.
    """
    check_time = check_time or datetime.now().time()
    if begin_time < end_time:
        return begin_time <= check_time <= end_time
    else:  # crosses midnight
        return check_time >= begin_time or check_time <= end_time


def isRun(start_hour, end_hour):
    """Return True if the current time is within the start–end hour range.

    Args:
        start_hour: Hour (0–23) the window begins.
        end_hour: Hour (0–23) the window ends.

    Returns:
        True if currently within the operating window.
    """
    return is_time_between(time(start_hour, 0), time(end_hour, 0))
