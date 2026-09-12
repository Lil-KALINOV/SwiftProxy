import threading

from .utils import human_bytes


class _Stats:
    _FIELDS = (
        'connections_total', 'connections_active',
        'connections_ws', 'connections_tcp_fallback',
        'connections_cfproxy', 'connections_fronting',
        'connections_bad', 'connections_masked',
        'ws_errors', 'bytes_up', 'bytes_down',
        'pool_hits', 'pool_misses',
        'cf_pool_hits', 'cf_pool_misses',
    )

    def __init__(self):
        self._lock = threading.Lock()
        self._data = dict.fromkeys(self._FIELDS, 0)

    def incr(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._data[name] = self._data[name] + value

    def summary(self) -> str:
        with self._lock:
            d = dict(self._data)
        pool_total = d['pool_hits'] + d['pool_misses']
        pool_s = (f"{d['pool_hits']}/{pool_total}"
                  if pool_total else "n/a")
        cf_pool_total = d['cf_pool_hits'] + d['cf_pool_misses']
        cf_pool_s = (f"{d['cf_pool_hits']}/{cf_pool_total}"
                     if cf_pool_total else "n/a")
        return (f"total={d['connections_total']} "
                f"active={d['connections_active']} "
                f"ws={d['connections_ws']} "
                f"tcp_fb={d['connections_tcp_fallback']} "
                f"cf={d['connections_cfproxy']} "
                f"front={d['connections_fronting']} "
                f"bad={d['connections_bad']} "
                f"masked={d['connections_masked']} "
                f"err={d['ws_errors']} "
                f"pool={pool_s} "
                f"cf_pool={cf_pool_s} "
                f"up={human_bytes(d['bytes_up'])} "
                f"down={human_bytes(d['bytes_down'])}")


stats = _Stats()