"""pytest configuration for Shopping List with Grocy tests."""

import sys

if sys.platform == "win32":
    import pytest_socket

    # pytest-homeassistant-custom-component's own pytest_runtest_setup hook
    # calls pytest_socket.disable_socket(allow_unix_socket=True) before every
    # test, unconditionally, with no fixture or marker to opt out. Fighting
    # hook execution order to re-enable sockets afterward doesn't work: the
    # fixture setup where asyncio creates its event loop is itself just
    # another pytest_runtest_setup hookimpl, and its position relative to
    # HA's disable call can't be controlled from a conftest.py hookimpl.
    #
    # Instead, patch pytest_socket's own family check so the "allow_unix_socket"
    # exemption also covers the AF_INET loopback socket asyncio falls back to
    # on Windows. This Python build has no native socket.socketpair(), so
    # asyncio always uses that fallback for its internal self-pipe.
    #
    # Linux CI is untouched: this whole block is skipped there, and native
    # AF_UNIX socketpair() never goes through pytest_socket's guard at all.
    pytest_socket._is_unix_socket = lambda family: True