"""
Transmission throttle/restore module.

Manages speed limits on discovered Transmission instances via their RPC API.
Saves original settings before throttling and restores them when the PS goes offline.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import transmission_rpc
from transmission_rpc.error import (
    TransmissionError,
    TransmissionConnectError,
    TransmissionAuthError,
    TransmissionTimeoutError,
)

logger = logging.getLogger("ps-throttle.throttle")


@dataclass
class OriginalLimits:
    """Stores the original speed limits of a Transmission instance."""
    speed_limit_down: int = 0
    speed_limit_down_enabled: bool = False
    speed_limit_up: int = 0
    speed_limit_up_enabled: bool = False
    alt_speed_enabled: bool = False


class TransmissionThrottler:
    """
    Manages throttling for a single Transmission instance.
    
    Saves original speed settings before applying throttle limits,
    and can restore them when throttling is no longer needed.
    """

    def __init__(self, instance, config):
        """
        Args:
            instance: TransmissionInstance from docker_discovery
            config: Application Config object
        """
        self.instance = instance
        self.config = config
        self._client: Optional[transmission_rpc.Client] = None
        self._original_limits: Optional[OriginalLimits] = None
        self._is_throttled: bool = False

    @property
    def is_throttled(self) -> bool:
        return self._is_throttled

    def _connect(self) -> Optional[transmission_rpc.Client]:
        """Create or reuse a connection to the Transmission RPC."""
        if self._client is not None:
            try:
                # Quick check if connection is still alive
                self._client.get_session()
                return self._client
            except Exception:
                self._client = None

        try:
            kwargs = {
                "host": self.instance.host,
                "port": self.instance.port,
                "timeout": 10,
            }
            if self.instance.username:
                kwargs["username"] = self.instance.username
                kwargs["password"] = self.instance.password

            self._client = transmission_rpc.Client(**kwargs)
            logger.debug("Connected to %s", self.instance)
            return self._client

        except TransmissionAuthError:
            logger.error(
                "❌ Authentication failed for %s. Check RPC credentials.",
                self.instance
            )
        except TransmissionConnectError as e:
            logger.error("❌ Cannot connect to %s: %s", self.instance, e)
        except Exception as e:
            logger.error("❌ Unexpected error connecting to %s: %s", self.instance, e)

        return None

    def throttle(self) -> bool:
        """
        Apply throttle limits to this Transmission instance.
        
        First saves the current speed limits, then applies the configured
        throttle values. Returns True if successful.
        """
        if self._is_throttled:
            logger.debug("%s is already throttled", self.instance.container_name)
            return True

        client = self._connect()
        if client is None:
            return False

        try:
            # Save current limits before modifying
            session = client.get_session()
            self._original_limits = OriginalLimits(
                speed_limit_down=session.speed_limit_down or 0,
                speed_limit_down_enabled=session.speed_limit_down_enabled or False,
                speed_limit_up=session.speed_limit_up or 0,
                speed_limit_up_enabled=session.speed_limit_up_enabled or False,
                alt_speed_enabled=session.alt_speed_enabled or False,
            )

            logger.info(
                "💾 Saved original limits for %s: ↓%s KB/s (enabled=%s), ↑%s KB/s (enabled=%s)",
                self.instance.container_name,
                self._original_limits.speed_limit_down,
                self._original_limits.speed_limit_down_enabled,
                self._original_limits.speed_limit_up,
                self._original_limits.speed_limit_up_enabled,
            )

            # Apply throttle limits
            client.set_session(
                speed_limit_down=self.config.throttle_down_kb,
                speed_limit_down_enabled=True,
                speed_limit_up=self.config.throttle_up_kb,
                speed_limit_up_enabled=True,
            )

            self._is_throttled = True
            logger.info(
                "⬇️  Throttled %s: ↓%d KB/s, ↑%d KB/s",
                self.instance.container_name,
                self.config.throttle_down_kb,
                self.config.throttle_up_kb,
            )
            return True

        except TransmissionTimeoutError:
            logger.error("Timeout while throttling %s", self.instance.container_name)
        except TransmissionError as e:
            logger.error("RPC error while throttling %s: %s", self.instance.container_name, e)
        except Exception as e:
            logger.error("Unexpected error throttling %s: %s", self.instance.container_name, e)

        return False

    def restore(self) -> bool:
        """
        Restore original speed limits for this Transmission instance.
        
        If no original limits were saved (e.g., the service started while
        throttled), disables all speed limits as a safe default.
        Returns True if successful.
        """
        if not self._is_throttled:
            logger.debug("%s is not throttled, nothing to restore", self.instance.container_name)
            return True

        client = self._connect()
        if client is None:
            return False

        try:
            if self._original_limits:
                # Restore saved limits
                client.set_session(
                    speed_limit_down=self._original_limits.speed_limit_down,
                    speed_limit_down_enabled=self._original_limits.speed_limit_down_enabled,
                    speed_limit_up=self._original_limits.speed_limit_up,
                    speed_limit_up_enabled=self._original_limits.speed_limit_up_enabled,
                )
                logger.info(
                    "✅ Restored %s: ↓%s KB/s (enabled=%s), ↑%s KB/s (enabled=%s)",
                    self.instance.container_name,
                    self._original_limits.speed_limit_down,
                    self._original_limits.speed_limit_down_enabled,
                    self._original_limits.speed_limit_up,
                    self._original_limits.speed_limit_up_enabled,
                )
            else:
                # No saved limits - disable speed limits as a safe default
                client.set_session(
                    speed_limit_down_enabled=False,
                    speed_limit_up_enabled=False,
                )
                logger.info(
                    "✅ Restored %s: speed limits DISABLED (no saved limits)",
                    self.instance.container_name,
                )

            self._is_throttled = False
            self._original_limits = None
            return True

        except TransmissionTimeoutError:
            logger.error("Timeout while restoring %s", self.instance.container_name)
        except TransmissionError as e:
            logger.error("RPC error while restoring %s: %s", self.instance.container_name, e)
        except Exception as e:
            logger.error("Unexpected error restoring %s: %s", self.instance.container_name, e)

        return False

    def get_status(self) -> dict:
        """Get current status of this Transmission instance."""
        client = self._connect()
        if client is None:
            return {
                "name": self.instance.container_name,
                "connected": False,
                "throttled": self._is_throttled,
            }

        try:
            session = client.get_session()
            stats = client.session_stats()
            return {
                "name": self.instance.container_name,
                "connected": True,
                "throttled": self._is_throttled,
                "download_speed": getattr(stats, "download_speed", 0),
                "upload_speed": getattr(stats, "upload_speed", 0),
                "speed_limit_down": session.speed_limit_down,
                "speed_limit_down_enabled": session.speed_limit_down_enabled,
                "speed_limit_up": session.speed_limit_up,
                "speed_limit_up_enabled": session.speed_limit_up_enabled,
                "active_torrents": getattr(stats, "active_torrent_count", 0),
            }
        except Exception as e:
            return {
                "name": self.instance.container_name,
                "connected": False,
                "throttled": self._is_throttled,
                "error": str(e),
            }
