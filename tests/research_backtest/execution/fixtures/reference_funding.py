from __future__ import annotations


def reference_count_funding_windows(
    entry_time_utc_ms: int,
    maximum_exit_time_utc_ms: int,
    windows: tuple[tuple[int, int, int], ...],
) -> int:
    """Independent reference: no production imports or production calls."""
    total = 0
    for window_start, _nominal_time, window_end in windows:
        if window_end > entry_time_utc_ms and window_start <= maximum_exit_time_utc_ms:
            total += 1
    return total
