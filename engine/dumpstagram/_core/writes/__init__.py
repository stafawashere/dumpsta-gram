"""Write capabilities, one module each, every one of them sending through ``_core/writing.py``.

Nothing in this package may name ``run_with_retries`` or ``with_token_recovery``, and a gate
scans it to hold that. A write is sent once, and whether to send it again is the caller's
decision after reading the state it would have changed.
"""
