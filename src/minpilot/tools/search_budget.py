"""Shared per-task paid request reservations; unknown charges consume headroom."""
import threading


class SearchLimit(Exception):
    pass


class PaidSearchBudget:
    def __init__(self, limit=100):
        self.limit = limit
        self.billed = self.unknown = self.inflight = self.nonbillable = 0
        self.lock = threading.RLock()

    def reserve(self):
        with self.lock:
            if self.billed + self.unknown + self.inflight >= self.limit:
                raise SearchLimit("task paid-search limit reached (100 credits); cache/free fallback remain available")
            self.inflight += 1

    def settle(self, outcome):
        with self.lock:
            self.inflight -= 1
            setattr(self, outcome, getattr(self, outcome) + 1)

    def dump(self):
        with self.lock:
            return {k: getattr(self, k) for k in ("limit", "billed", "unknown", "inflight", "nonbillable")}

    def load(self, state):
        with self.lock:
            if state.get("limit") != self.limit or state.get("inflight") != 0:
                raise ValueError("invalid paid-search checkpoint")
            for key in ("billed", "unknown", "nonbillable"):
                value = state.get(key)
                if type(value) is not int or value < 0:
                    raise ValueError("invalid paid-search counters")
                setattr(self, key, value)
            if self.billed + self.unknown > self.limit:
                raise ValueError("paid-search counters exceed limit")
