"""
ps-throttle: PlayStation Bandwidth Guardian for Transmission

Main entry point and orchestration loop.
Monitors PlayStation activity and dynamically throttles/restores
Transmission instances to ensure optimal gaming bandwidth.
"""

import logging
import signal
import sys
import time

from .config import Config
from .ps_detector import PSDetector
from .docker_discovery import DockerDiscovery
from .transmission_throttle import TransmissionThrottler

logger = logging.getLogger("ps-throttle")


class PSThrottle:
    """Main application orchestrator."""

    def __init__(self):
        self.config = Config()
        self.logger = self.config.setup_logging()
        self.detector = PSDetector(self.config)
        self.discovery = DockerDiscovery(self.config)
        self.throttlers: dict[str, TransmissionThrottler] = {}
        self._running = True

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, shutting down gracefully...", sig_name)
        self._running = False

    def _sync_throttlers(self):
        """
        Sync throttler instances with discovered Transmission containers.
        
        Creates new throttlers for newly discovered containers and
        removes throttlers for containers that no longer exist.
        """
        instances = self.discovery.discover()
        current_ids = {inst.container_id for inst in instances}
        existing_ids = set(self.throttlers.keys())

        # Remove throttlers for containers that no longer exist
        for removed_id in existing_ids - current_ids:
            throttler = self.throttlers.pop(removed_id)
            if throttler.is_throttled:
                logger.warning(
                    "Container %s disappeared while throttled! "
                    "Limits may need manual restoration.",
                    throttler.instance.container_name,
                )

        # Add throttlers for new containers
        for instance in instances:
            if instance.container_id not in self.throttlers:
                self.throttlers[instance.container_id] = TransmissionThrottler(
                    instance, self.config
                )

    def _throttle_all(self):
        """Apply throttle to all discovered Transmission instances."""
        for throttler in self.throttlers.values():
            if not throttler.is_throttled:
                throttler.throttle()

    def _restore_all(self):
        """Restore original limits on all Transmission instances."""
        for throttler in self.throttlers.values():
            if throttler.is_throttled:
                throttler.restore()

    def _log_status(self):
        """Log current status of all managed instances."""
        for throttler in self.throttlers.values():
            status = throttler.get_status()
            if status.get("connected"):
                dl_speed = status.get("download_speed", 0) / 1024  # bytes to KB
                ul_speed = status.get("upload_speed", 0) / 1024
                logger.debug(
                    "📊 %s: %s | ↓%.1f KB/s ↑%.1f KB/s | %d active torrents",
                    status["name"],
                    "🔴 THROTTLED" if status["throttled"] else "🟢 NORMAL",
                    dl_speed, ul_speed,
                    status.get("active_torrents", 0),
                )

    def run(self):
        """Main application loop."""
        logger.info("=" * 60)
        logger.info("🎮 ps-throttle starting up")
        logger.info("=" * 60)
        logger.info("Configuration: %s", self.config)
        logger.info("")
        logger.info("Detection methods: %s", " → ".join(self.config.detection_methods))
        logger.info("  • DDP: PlayStation Device Discovery Protocol (standby vs awake)")
        logger.info("  • TCP: Port %d probe (only open when PS is ON)", self.config.tcp_probe_port)
        logger.info("  • Ping: Basic reachability (⚠️  responds in standby too)")
        logger.info("")

        # Initial discovery
        self._sync_throttlers()

        if self.throttlers:
            logger.info(
                "Found %d Transmission instance(s): %s",
                len(self.throttlers),
                ", ".join(t.instance.container_name for t in self.throttlers.values()),
            )
        else:
            logger.warning(
                "No Transmission containers found yet. Will retry every %ds.",
                self.config.discovery_interval,
            )

        logger.info("")
        logger.info("Monitoring PlayStation at %s every %ds...",
                    self.config.ps_ip, self.config.check_interval)
        logger.info("=" * 60)

        # Main loop
        was_active = False
        while self._running:
            try:
                # Re-discover containers periodically
                self._sync_throttlers()

                # Check PlayStation status
                ps_active = self.detector.check()

                if ps_active and not was_active:
                    # PS just became active - throttle everything
                    logger.info("🎮 PlayStation is ACTIVE - throttling Transmission")
                    self._throttle_all()
                    was_active = True

                elif not ps_active and was_active:
                    # PS just became inactive - restore everything
                    logger.info("💤 PlayStation is INACTIVE - restoring Transmission")
                    self._restore_all()
                    was_active = False

                # Log periodic status
                self._log_status()

                # Sleep until next check
                time.sleep(self.config.check_interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("Unexpected error in main loop: %s", e, exc_info=True)
                time.sleep(self.config.check_interval)

        # Graceful shutdown: restore all limits
        logger.info("Shutting down - restoring all Transmission limits...")
        self._restore_all()
        logger.info("👋 ps-throttle stopped. Goodbye!")


def main():
    """Entry point."""
    app = PSThrottle()
    app.run()


if __name__ == "__main__":
    main()
