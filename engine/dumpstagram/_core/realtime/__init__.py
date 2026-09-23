"""The listener behind ``events()``, kept apart from the request path per ADR-0006.

It shares the session and the pacer with every other capability and shares none of their
modules. ``buffer.py`` holds events between the loop that produces them and whoever drains
them, and ``pump.py`` turns polls into events. The transport is whatever ``EventSource`` the
client hands the pump, and the polling one arrives in Step 23 of ``engine/docs/build-plan.md``.
"""
