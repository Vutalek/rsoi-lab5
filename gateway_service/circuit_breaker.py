from datetime import datetime, timedelta
from typing import Literal
from fastapi import HTTPException

CBState = Literal["CLOSED", "OPEN", "HALF_OPEN"]


class CircuitBreaker:
    fault_count: int
    success_count: int
    max_count: int
    half_opened_threshold: int
    half_open_count: int
    opened_at: datetime | None
    timer_min: int
    state: CBState

    def __init__(self, max_count: int=10, half_opened_threshold: int=2, timer_min: int=2):
        self.fault_count = 0
        self.success_count = 0
        self.max_count = max_count

        self.half_opened_threshold = half_opened_threshold
        self.half_open_count = 0

        self.opened_at = None
        self.timer_min = timer_min

        self.state = "CLOSED"

    def update_timer(self):
        if self.opened_at is not None and self.state == "OPEN":
            current_timestamp = datetime.now()
            if current_timestamp - self.opened_at >= timedelta(minutes=self.timer_min):
                self.state = "HALF_OPEN"
                self.half_open_count = 0

    def check_circuit(self, func):
        def wrapped(*args, **kwargs):
            self.update_timer()
            if self.state == "CLOSED":
                try:
                    result = func(*args, **kwargs)
                except HTTPException:
                    raise
                except Exception as e:
                    self.fault_count += 1
                    if self.fault_count == self.max_count:
                        self.state = "OPEN"
                        self.opened_at = datetime.now()
                    return (False, None)
                return (True, result)
            if self.state == "HALF_OPEN":
                try:
                    result = func(*args, **kwargs)
                except HTTPException:
                    raise
                except Exception as e:
                    self.state = "OPEN"
                    self.opened_at = datetime.now()
                    self.half_open_count = 0
                    return (False, None)
                self.half_open_count += 1
                if self.half_open_count == self.half_opened_threshold:
                    self.state = "CLOSED"
                    self.fault_count = 0
                    self.success_count = 0
                return (True, result)
            else: return (False, None)
        return wrapped