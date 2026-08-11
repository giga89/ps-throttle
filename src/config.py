"""
Configuration module for ps-throttle.
All settings are loaded from environment variables with sensible defaults.
"""

import os
import logging


class Config:
    """Configuration loaded from environment variables."""

    def __init__(self):
        # PlayStation detection
        self.ps_ip: str = os.getenv("PS_IP", "192.168.9.22")
        self.check_interval: int = int(os.getenv("CHECK_INTERVAL", "10"))
        self.debounce_count: int = int(os.getenv("DEBOUNCE_COUNT", "5"))

        # Detection methods (comma-separated: ddp,tcp,ping)
        self.detection_methods: list[str] = os.getenv(
            "DETECTION_METHODS", "ddp,tcp,ping"
        ).lower().split(",")

        # DDP (Device Discovery Protocol) settings
        self.ddp_port: int = int(os.getenv("DDP_PORT", "987"))
        self.ddp_timeout: float = float(os.getenv("DDP_TIMEOUT", "2.0"))

        # TCP port probe settings (port 9295 = Remote Play, only open when PS is ON)
        self.tcp_probe_port: int = int(os.getenv("TCP_PROBE_PORT", "9295"))
        self.tcp_probe_timeout: float = float(os.getenv("TCP_PROBE_TIMEOUT", "1.5"))

        # Ping settings
        self.ping_timeout: int = int(os.getenv("PING_TIMEOUT", "1"))
        self.ping_count: int = int(os.getenv("PING_COUNT", "1"))

        # Throttle limits (KB/s)
        self.throttle_down_kb: int = int(os.getenv("THROTTLE_DOWN_KB", "50"))
        self.throttle_up_kb: int = int(os.getenv("THROTTLE_UP_KB", "20"))

        # Docker / Transmission discovery
        self.transmission_filter: str = os.getenv("TRANSMISSION_FILTER", "transmission")
        self.discovery_interval: int = int(os.getenv("DISCOVERY_INTERVAL", "60"))

        # Transmission RPC fallback credentials (used if not discovered from container env)
        self.rpc_user: str = os.getenv("TRANSMISSION_USER", "")
        self.rpc_password: str = os.getenv("TRANSMISSION_PASS", "")

        # Web Dashboard
        self.web_enabled: bool = os.getenv("WEB_ENABLED", "true").lower() in ("true", "1", "yes")
        self.web_port: int = int(os.getenv("WEB_PORT", "9870"))
        self.web_host: str = os.getenv("WEB_HOST", "0.0.0.0")

        # Logging
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    def setup_logging(self) -> logging.Logger:
        """Configure and return the application logger."""
        logging.basicConfig(
            level=getattr(logging, self.log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        logger = logging.getLogger("ps-throttle")
        logger.setLevel(getattr(logging, self.log_level, logging.INFO))
        return logger

    def __repr__(self) -> str:
        return (
            f"Config(ps_ip={self.ps_ip}, check_interval={self.check_interval}s, "
            f"debounce={self.debounce_count}, detection={self.detection_methods}, "
            f"throttle={self.throttle_down_kb}↓/{self.throttle_up_kb}↑ KB/s, "
            f"web_port={self.web_port if self.web_enabled else 'disabled'}, "
            f"filter='{self.transmission_filter}')"
        )
