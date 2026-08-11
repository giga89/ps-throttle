"""
Docker self-discovery module for Transmission containers.

Automatically finds running Docker containers that match the Transmission filter,
extracts their RPC connection details (host, port, credentials) from container
inspection, and provides them for the throttle module.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import docker
from docker.errors import DockerException

logger = logging.getLogger("ps-throttle.discovery")


@dataclass
class TransmissionInstance:
    """Represents a discovered Transmission container."""
    container_id: str
    container_name: str
    host: str
    port: int
    username: str
    password: str

    def __repr__(self) -> str:
        auth = f"{self.username}:***" if self.username else "no-auth"
        return f"Transmission({self.container_name} @ {self.host}:{self.port}, {auth})"


class DockerDiscovery:
    """
    Discovers Transmission instances running as Docker containers.
    
    Uses the Docker socket to:
    1. Find containers whose image/name contains the configured filter string
    2. Extract RPC port from container port mappings
    3. Extract RPC credentials from container environment variables
    
    Re-discovery is performed periodically to handle containers being
    added or removed dynamically.
    """

    # Known environment variable names for Transmission RPC credentials
    # across different Docker images (linuxserver, haugene, etc.)
    CREDENTIAL_ENV_VARS = {
        "username": [
            "TRANSMISSION_RPC_USERNAME",
            "USER",
            "TRANSMISSION_USER",
            "RPC_USERNAME",
        ],
        "password": [
            "TRANSMISSION_RPC_PASSWORD",
            "PASS",
            "TRANSMISSION_PASS",
            "RPC_PASSWORD",
        ],
    }

    # Known env vars that indicate RPC auth is disabled
    AUTH_DISABLED_VARS = [
        "TRANSMISSION_RPC_AUTHENTICATION_REQUIRED",
    ]

    def __init__(self, config):
        self.config = config
        self._client: Optional[docker.DockerClient] = None
        self._instances: list[TransmissionInstance] = []
        self._last_discovery: float = 0
        self._connect()

    def _connect(self):
        """Connect to the Docker daemon."""
        try:
            self._client = docker.from_env()
            self._client.ping()
            logger.info("✅ Connected to Docker daemon")
        except DockerException as e:
            logger.error("❌ Failed to connect to Docker daemon: %s", e)
            logger.error("Make sure /var/run/docker.sock is mounted in the container")
            self._client = None

    @property
    def instances(self) -> list[TransmissionInstance]:
        """Get the current list of discovered instances."""
        return self._instances

    def discover(self, force: bool = False) -> list[TransmissionInstance]:
        """
        Discover Transmission instances.
        
        Only performs actual discovery if the configured interval has elapsed
        since the last discovery, unless force=True.
        
        Returns the list of discovered TransmissionInstance objects.
        """
        now = time.time()
        if not force and (now - self._last_discovery) < self.config.discovery_interval:
            return self._instances

        self._last_discovery = now

        if self._client is None:
            self._connect()
            if self._client is None:
                return self._instances

        try:
            instances = self._find_transmission_containers()
            
            # Log changes
            old_names = {i.container_name for i in self._instances}
            new_names = {i.container_name for i in instances}
            
            added = new_names - old_names
            removed = old_names - new_names

            if added:
                logger.info("🔍 Discovered new Transmission containers: %s", ", ".join(added))
            if removed:
                logger.info("🗑️  Transmission containers removed: %s", ", ".join(removed))
            
            if not instances:
                logger.warning("⚠️  No Transmission containers found matching filter '%s'",
                             self.config.transmission_filter)

            self._instances = instances
            return instances

        except DockerException as e:
            logger.error("Docker API error during discovery: %s", e)
            # Try to reconnect next time
            self._client = None
            return self._instances

    def _find_transmission_containers(self) -> list[TransmissionInstance]:
        """Find and inspect all running containers matching the filter."""
        instances = []
        filter_str = self.config.transmission_filter.lower()

        containers = self._client.containers.list(filters={"status": "running"})

        for container in containers:
            name = container.name.lower()
            image_tags = []
            try:
                image_tags = container.image.tags or []
            except Exception:
                pass
            image_str = " ".join(t.lower() for t in image_tags)

            # Check if container matches filter (by name or image)
            if filter_str not in name and filter_str not in image_str:
                continue

            logger.debug("Found matching container: %s (image: %s)", container.name, image_tags)

            instance = self._inspect_container(container)
            if instance:
                instances.append(instance)

        return instances

    def _inspect_container(self, container) -> Optional[TransmissionInstance]:
        """Extract connection details from a container."""
        try:
            # Get container details
            details = container.attrs

            # Extract port mapping
            port = self._get_rpc_port(details)
            if port is None:
                logger.warning(
                    "Container %s: could not determine RPC port, trying default 9091",
                    container.name
                )
                port = 9091

            # Extract credentials from environment variables
            env_vars = self._parse_env_vars(details)
            username, password = self._get_credentials(env_vars)

            # Determine host - use localhost since we share the network
            # or the host's IP for bridge networking
            host = self._get_host(details)

            return TransmissionInstance(
                container_id=container.short_id,
                container_name=container.name,
                host=host,
                port=port,
                username=username,
                password=password,
            )

        except Exception as e:
            logger.error("Failed to inspect container %s: %s", container.name, e)
            return None

    def _get_rpc_port(self, details: dict) -> Optional[int]:
        """Extract the RPC port from container port mappings."""
        ports = details.get("NetworkSettings", {}).get("Ports", {})

        # Look for mapped port 9091 (standard Transmission RPC)
        for container_port, host_bindings in ports.items():
            port_num = container_port.split("/")[0]
            if port_num == "9091" and host_bindings:
                for binding in host_bindings:
                    host_port = binding.get("HostPort")
                    if host_port:
                        return int(host_port)

        # Fallback: check for common RPC port env var
        env_vars = self._parse_env_vars(details)
        rpc_port = env_vars.get("TRANSMISSION_RPC_PORT")
        if rpc_port:
            try:
                return int(rpc_port)
            except ValueError:
                pass

        return None

    def _parse_env_vars(self, details: dict) -> dict[str, str]:
        """Parse environment variables from container config."""
        env_list = (
            details.get("Config", {}).get("Env", [])
        )
        env_dict = {}
        for entry in env_list:
            if "=" in entry:
                key, _, value = entry.partition("=")
                env_dict[key] = value
        return env_dict

    def _get_credentials(self, env_vars: dict) -> tuple[str, str]:
        """Extract RPC credentials from container environment variables."""
        # First check if auth is explicitly disabled
        for var_name in self.AUTH_DISABLED_VARS:
            value = env_vars.get(var_name, "").lower()
            if value in ("false", "0", "no"):
                logger.debug("RPC authentication is disabled (env: %s=%s)", var_name, value)
                return "", ""

        # Try to find username
        username = ""
        for var_name in self.CREDENTIAL_ENV_VARS["username"]:
            if var_name in env_vars and env_vars[var_name]:
                username = env_vars[var_name]
                logger.debug("Found RPC username from env var: %s", var_name)
                break

        # Try to find password
        password = ""
        for var_name in self.CREDENTIAL_ENV_VARS["password"]:
            if var_name in env_vars and env_vars[var_name]:
                password = env_vars[var_name]
                logger.debug("Found RPC password from env var: %s", var_name)
                break

        # Fallback to global config
        if not username and self.config.rpc_user:
            username = self.config.rpc_user
            logger.debug("Using fallback RPC username from config")
        if not password and self.config.rpc_password:
            password = self.config.rpc_password
            logger.debug("Using fallback RPC password from config")

        return username, password

    def _get_host(self, details: dict) -> str:
        """
        Determine the host to connect to for RPC.
        
        If the container uses host networking, use localhost.
        Otherwise, use the container's mapped port on the host.
        """
        network_mode = details.get("HostConfig", {}).get("NetworkMode", "")

        if network_mode == "host":
            return "127.0.0.1"

        # For bridge/custom networks, connect via host
        # Since ps-throttle runs with host networking, localhost should work
        # for containers with mapped ports
        return "127.0.0.1"
