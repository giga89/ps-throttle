"""
PlayStation detection module.

Uses a multi-layered approach to detect if a PlayStation is actively in use:
1. DDP (Device Discovery Protocol) - Sony's protocol that reports AWAKE/STANDBY
2. TCP port probe (port 9295) - Remote Play port, only open when PS is fully ON
3. Ping - basic reachability check (fallback, less reliable for standby detection)

The PS is considered "active" only if at least one detection method confirms it's ON
(not just in standby). Includes debounce logic to avoid false triggers.
"""

import json
import logging
import os
import socket
import struct
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger("ps-throttle.detector")

PLAYACTOR_JS = "/usr/local/lib/node_modules/playactor/dist/cli/index.js"


# DDP (Device Discovery Protocol) constants
DDP_SEARCH_MSG = (
    "SRCH * HTTP/1.1\r\n"
    "device-discovery-protocol-version:00030010\r\n"
    "\r\n"
)

# PS5 uses a slightly different version string
DDP_SEARCH_MSG_PS5 = (
    "SRCH * HTTP/1.1\r\n"
    "device-discovery-protocol-version:00030010\r\n"
    "\r\n"
)


@dataclass
class DetectionResult:
    """Result from a single detection cycle."""
    is_active: bool = False
    method: str = ""
    details: str = ""


@dataclass
class PSState:
    """Tracks PlayStation state with debounce logic."""
    is_active: bool = False
    consecutive_inactive: int = 0
    last_active_method: str = ""
    last_check_time: float = 0.0
    ps_info: dict = field(default_factory=dict)


class PSDetector:
    """
    Detects PlayStation activity using multiple methods.
    
    The detector tries methods in order of reliability:
    1. PlayActor CLI (official Remote Play protocol - AWAKE vs STANDBY + metadata)
    2. DDP protocol (directly reports console state)
    3. TCP port probe (reliable - port 9295 only open when ON)
    4. Ping (least reliable - PS responds even in standby)
    """

    def __init__(self, config):
        self.config = config
        self.state = PSState()
        self._methods = {
            "playactor": self._check_playactor,
            "ddp": self._check_ddp,
            "tcp": self._check_tcp_port,
            "ping": self._check_ping,
        }

    def _check_playactor(self) -> DetectionResult:
        """
        Use PlayActor CLI (official Remote Play discovery) to check console state.
        Returns AWAKE, STANDBY, or offline, plus metadata (firmware, device id, name).
        """
        try:
            if os.path.exists(PLAYACTOR_JS):
                cmd = ["node", PLAYACTOR_JS, "check", "--ip", self.config.ps_ip]
            else:
                cmd = ["playactor", "check", "--ip", self.config.ps_ip]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=4.0
            )
            raw = (proc.stdout or "").strip()
            if raw.startswith("{") and raw.endswith("}"):
                data = json.loads(raw)
                extras = data.get("extras", {})
                status = extras.get("status") or data.get("status", "")
                name = data.get("name", "PlayStation 5")
                fw = data.get("systemVersion", "")
                ps_id = data.get("id", "")
                
                self.state.ps_info = {
                    "name": name,
                    "status": status,
                    "system_version": fw,
                    "id": ps_id,
                    "ip": self.config.ps_ip,
                    "type": data.get("type", "PS5"),
                    "updated_at": time.time()
                }

                if status == "AWAKE":
                    return DetectionResult(
                        is_active=True,
                        method="playactor",
                        details=f"Console is AWAKE ({name}, fw: {fw})"
                    )
                elif status == "STANDBY":
                    return DetectionResult(
                        is_active=False,
                        method="playactor",
                        details=f"Console is in STANDBY ({name})"
                    )
        except subprocess.TimeoutExpired:
            logger.debug("PlayActor check timed out")
        except FileNotFoundError:
            logger.debug("playactor command not found in PATH")
        except Exception as e:
            logger.debug("PlayActor check exception: %s", e)

        return DetectionResult(is_active=False, method="playactor", details="No playactor response")

    def check(self) -> bool:
        """
        Check if the PlayStation is actively in use.
        
        Returns True if PS is active, False if inactive.
        Uses debounce logic: PS must be detected as inactive for
        `debounce_count` consecutive checks before being considered OFF.
        """
        result = self._detect()
        self.state.last_check_time = time.time()

        if result.is_active:
            # PS is active
            if not self.state.is_active:
                logger.info(
                    "🎮 PlayStation detected as ACTIVE via %s: %s",
                    result.method, result.details
                )
            self.state.is_active = True
            self.state.consecutive_inactive = 0
            self.state.last_active_method = result.method
            return True
        else:
            # PS appears inactive - apply debounce
            self.state.consecutive_inactive += 1
            if self.state.consecutive_inactive >= self.config.debounce_count:
                if self.state.is_active:
                    logger.info(
                        "💤 PlayStation detected as INACTIVE after %d consecutive checks",
                        self.state.consecutive_inactive
                    )
                self.state.is_active = False
                return False
            else:
                # Still within debounce window - keep previous state
                if self.state.is_active:
                    logger.debug(
                        "PlayStation inactive check %d/%d (debouncing, still treated as active)",
                        self.state.consecutive_inactive, self.config.debounce_count
                    )
                return self.state.is_active

    def _detect(self) -> DetectionResult:
        """Try each configured detection method in order."""
        for method_name in self.config.detection_methods:
            method_name = method_name.strip()
            method = self._methods.get(method_name)
            if method is None:
                logger.warning("Unknown detection method: %s", method_name)
                continue

            try:
                result = method()
                if result.is_active:
                    return result
                if method_name in ("ddp", "playactor") and "STANDBY" in result.details:
                    return result
            except Exception as e:
                logger.debug("Detection method %s failed: %s", method_name, e)

        return DetectionResult(is_active=False, method="none", details="All methods negative")

    def _check_ddp(self) -> DetectionResult:
        """
        Use PlayStation Device Discovery Protocol (DDP) to check console status.
        
        Sends a UDP broadcast/unicast to the PS IP on port 987.
        The PS responds with an HTTP-like message containing a 'status' field
        that reads either '200 Ok' (AWAKE) or '620 Server Standby' (STANDBY).
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.config.ddp_timeout)

        try:
            # Send DDP search message directly to the PS IP
            sock.sendto(
                DDP_SEARCH_MSG.encode("utf-8"),
                (self.config.ps_ip, self.config.ddp_port)
            )

            # Wait for response
            data, addr = sock.recvfrom(1024)
            response = data.decode("utf-8", errors="replace")

            logger.debug("DDP response from %s: %s", addr, response.strip())

            # Parse the response
            if "200 Ok" in response:
                # Extract running app if available
                app_name = ""
                for line in response.split("\r\n"):
                    if line.lower().startswith("running-app-name:"):
                        app_name = line.split(":", 1)[1].strip()
                        break

                details = f"Console is AWAKE"
                if app_name:
                    details += f", running: {app_name}"

                return DetectionResult(is_active=True, method="ddp", details=details)

            elif "620" in response:
                return DetectionResult(
                    is_active=False, method="ddp",
                    details="Console is in STANDBY"
                )
            else:
                return DetectionResult(
                    is_active=False, method="ddp",
                    details=f"Unknown DDP response: {response[:100]}"
                )
        except socket.timeout:
            logger.debug("DDP: No response from %s (timeout)", self.config.ps_ip)
            return DetectionResult(is_active=False, method="ddp", details="No response (timeout)")
        except Exception as e:
            logger.debug("DDP check failed: %s", e)
            return DetectionResult(is_active=False, method="ddp", details=str(e))
        finally:
            sock.close()

    def _check_tcp_port(self) -> DetectionResult:
        """
        Probe TCP port 9295 (Remote Play).
        
        This port is only open when the PlayStation is fully powered on,
        NOT in standby mode. This makes it a reliable indicator.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.config.tcp_probe_timeout)

        try:
            result = sock.connect_ex((self.config.ps_ip, self.config.tcp_probe_port))
            if result == 0:
                return DetectionResult(
                    is_active=True, method="tcp",
                    details=f"Port {self.config.tcp_probe_port} is OPEN (PS is ON)"
                )
            else:
                return DetectionResult(
                    is_active=False, method="tcp",
                    details=f"Port {self.config.tcp_probe_port} is closed/filtered"
                )
        except socket.timeout:
            return DetectionResult(
                is_active=False, method="tcp",
                details=f"Port {self.config.tcp_probe_port} timeout"
            )
        except Exception as e:
            return DetectionResult(is_active=False, method="tcp", details=str(e))
        finally:
            sock.close()

    def _check_ping(self) -> DetectionResult:
        """
        Simple ping check.
        
        Note: PS in standby may still respond to ping if 'Stay Connected to 
        Internet' is enabled. This is the least reliable method and should only
        be used as a fallback.
        """
        try:
            result = subprocess.run(
                [
                    "ping",
                    "-c", str(self.config.ping_count),
                    "-W", str(self.config.ping_timeout),
                    self.config.ps_ip,
                ],
                capture_output=True,
                text=True,
                timeout=self.config.ping_timeout + 2,
            )

            if result.returncode == 0:
                return DetectionResult(
                    is_active=True, method="ping",
                    details=f"Ping response from {self.config.ps_ip}"
                )
            else:
                return DetectionResult(
                    is_active=False, method="ping",
                    details="No ping response"
                )
        except subprocess.TimeoutExpired:
            return DetectionResult(
                is_active=False, method="ping", details="Ping timeout"
            )
        except FileNotFoundError:
            logger.warning("ping command not found")
            return DetectionResult(is_active=False, method="ping", details="ping not found")
        except Exception as e:
            return DetectionResult(is_active=False, method="ping", details=str(e))
