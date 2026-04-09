"""pytest configuration for Shopping List with Grocy tests."""

import asyncio
import sys


def pytest_configure(config):
    """Use the standard asyncio policy on Windows.

    homeassistant installs HassEventLoopPolicy which creates a ProactorEventLoop.
    On Windows that loop calls socketpair() in __init__, which can block under
    certain test setups. The standard DefaultEventLoopPolicy is safe everywhere.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
