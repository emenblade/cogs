"""Background thread that streams Docker events and fires callbacks.

Usage:
    listener = DockerListener(on_start=my_async_fn, on_stop=my_async_fn, loop=asyncio_loop)
    listener.start()
    # ... later ...
    listener.stop()  # blocks up to 5s for clean exit
"""

import threading
import logging
from typing import Callable, Awaitable
import asyncio

log = logging.getLogger("red.gsm-autosync.docker_listener")


class DockerListener(threading.Thread):
    """Streams Docker container events in a background thread.

    Calls on_start(container_name, container_id) or
          on_stop(container_name, container_id)
    as asyncio coroutines scheduled on the provided event loop.
    """

    def __init__(
        self,
        on_start: Callable[[str, str], Awaitable[None]],
        on_stop: Callable[[str, str], Awaitable[None]],
        loop: asyncio.AbstractEventLoop,
    ):
        super().__init__(daemon=True, name="gsm-autosync-docker-listener")
        self._on_start = on_start
        self._on_stop = on_stop
        self._loop = loop
        self._client = None
        self._running = False

    def run(self):
        try:
            import docker as _docker
        except ImportError:
            log.error("docker package not installed")
            return

        try:
            self._client = _docker.from_env()
        except Exception as e:
            log.error("Failed to connect to Docker socket: %s", e)
            return

        self._running = True
        log.info("Docker event listener started")

        try:
            for event in self._client.events(decode=True, filters={"type": "container"}):
                if not self._running:
                    break
                action = event.get("Action", "")
                attrs = event.get("Actor", {}).get("Attributes", {})
                name = attrs.get("name", "")
                cid = event.get("Actor", {}).get("ID", "")[:12]

                if action == "start":
                    asyncio.run_coroutine_threadsafe(
                        self._on_start(name, cid), self._loop
                    )
                elif action in ("die", "stop"):
                    asyncio.run_coroutine_threadsafe(
                        self._on_stop(name, cid), self._loop
                    )
        except Exception as e:
            if self._running:
                log.error("Docker event stream error: %s", e)
        finally:
            log.info("Docker event listener stopped")

    def stop(self):
        """Signal the thread to stop and close the Docker client."""
        self._running = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        if self.is_alive():
            self.join(timeout=5)

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._running

    @staticmethod
    def docker_available() -> bool:
        client = None
        try:
            import docker as _docker
            client = _docker.from_env()
            client.ping()
            return True
        except Exception:
            return False
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    @staticmethod
    def get_container_ip(container_name: str) -> str | None:
        """Return the bridge network IP for a container, or None."""
        client = None
        try:
            import docker as _docker
            client = _docker.from_env()
            container = client.containers.get(container_name)
            networks = container.attrs["NetworkSettings"]["Networks"]
            # Prefer bridge network; fall back to first available
            if "bridge" in networks:
                return networks["bridge"]["IPAddress"] or None
            for net in networks.values():
                ip = net.get("IPAddress")
                if ip:
                    return ip
            return None
        except Exception as e:
            log.error("Failed to get IP for container %s: %s", container_name, e)
            return None
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    @staticmethod
    def list_running_containers() -> list[str]:
        """Return names of all currently running containers."""
        client = None
        try:
            import docker as _docker
            client = _docker.from_env()
            containers = client.containers.list()
            names = [c.name for c in containers]
            return names
        except Exception as e:
            log.error("Failed to list containers: %s", e)
            return []
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
