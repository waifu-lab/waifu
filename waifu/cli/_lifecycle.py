import json
import os
import socket
import sys
import threading
import time
from typing import Callable, List, Optional

import uvicorn
from loguru import logger

from waifu import __version__

READY_PREFIX = "WAIFU_READY"


def bind_socket(host: str, port: int) -> socket.socket:
    family, type_, proto, _, sockaddr = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
    )[0]
    sock = socket.socket(family, type_, proto)
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(sockaddr)
    return sock


def ready_payload(host: str, port: int) -> dict:
    url_host = f"[{host}]" if ":" in host else host
    return {"host": host, "port": port, "url": f"http://{url_host}:{port}", "pid": os.getpid(), "version": __version__}


class ReadyServer(uvicorn.Server):
    async def startup(self, sockets: Optional[List[socket.socket]] = None) -> None:
        await super().startup(sockets=sockets)
        if self.should_exit or not self.servers:
            return
        host, port = self.servers[0].sockets[0].getsockname()[:2]

        print(f"{READY_PREFIX} {json.dumps(ready_payload(host, port))}", flush=True)


def watch_parent(pid: int, on_exit: Callable[[], None]) -> None:
    """Call ``on_exit`` (from a daemon thread) once process ``pid`` is gone."""
    target = _wait_windows if sys.platform == "win32" else _wait_posix
    threading.Thread(target=target, args=(pid, on_exit), name="parent-watch", daemon=True).start()


def _wait_windows(pid: int, on_exit: Callable[[], None]) -> None:
    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    infinite = 0xFFFFFFFF
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        if ctypes.get_last_error() == error_access_denied:
            logger.warning("Cannot watch parent pid {}: access denied", pid)
            return
        logger.warning("Parent pid {} is not running; shutting down", pid)
        on_exit()
        return
    kernel32.WaitForSingleObject(handle, infinite)
    kernel32.CloseHandle(handle)
    logger.warning("Parent pid {} exited; shutting down", pid)
    on_exit()


def _wait_posix(pid: int, on_exit: Callable[[], None]) -> None:
    is_direct_parent = os.getppid() == pid
    while True:
        if is_direct_parent and os.getppid() != pid:
            break
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        except PermissionError:
            pass
        time.sleep(1.0)
    logger.warning("Parent pid {} exited; shutting down", pid)
    on_exit()


def graceful_exit(server: uvicorn.Server, timeout: float = 10.0) -> Callable[[], None]:
    """Ask uvicorn to stop; hard-exit if shutdown hangs past ``timeout`` seconds."""

    def _exit() -> None:
        server.should_exit = True
        timer = threading.Timer(timeout, os._exit, args=(0,))
        timer.daemon = True
        timer.start()

    return _exit
