# ps-throttle 🎮⬇️

**PlayStation Bandwidth Guardian** — Automatically throttles Transmission when your PlayStation is active, restoring full speed when you're done gaming.

> No more manually pausing torrents before gaming. ps-throttle handles it for you.

## How It Works

```
🎮 PS5 turns ON
     ↓
🔍 ps-throttle detects it (DDP/TCP/Ping)
     ↓
📥 Finds all Transmission containers (Docker self-discovery)
     ↓
💾 Saves current speed limits
     ↓
⬇️ Applies throttle (50 KB/s ↓, 20 KB/s ↑)
     ↓
     ... you game ...
     ↓
🎮 PS5 turns OFF / enters standby
     ↓
✅ Restores original speed limits
```

## Key Features

- **🔍 Self-Discovery**: Automatically finds all Transmission Docker containers — no manual configuration needed
- **🎯 Smart Detection**: Distinguishes between PS in **standby** vs **active** using Sony's DDP protocol + TCP port probing
- **💾 Non-Destructive**: Saves and restores original speed limits (doesn't stop containers)
- **🔄 Dynamic**: Detects new/removed Transmission containers in real-time
- **🐳 Docker-Native**: Runs as a lightweight container alongside your stack
- **⚙️ Configurable**: All settings via environment variables

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/ps-throttle.git
cd ps-throttle
```

### 2. Configure

Edit `docker-compose.yml` and set your PlayStation IP:

```yaml
environment:
  PS_IP: "192.168.9.22"  # Your PS IP address
```

### 3. Deploy

```bash
docker compose up -d
```

### 4. Check logs

```bash
docker compose logs -f ps-throttle
```

You should see:
```
🎮 ps-throttle starting up
Configuration: Config(ps_ip=192.168.9.22, check_interval=10s, ...)
🔍 Discovered new Transmission containers: transmission
Monitoring PlayStation at 192.168.9.22 every 10s...
```

## Adding to an Existing Stack

If you already have Transmission running in Docker, just add ps-throttle to your `docker-compose.yml`:

```yaml
services:
  # ... your existing services ...

  ps-throttle:
    build: https://github.com/YOUR_USERNAME/ps-throttle.git
    container_name: ps-throttle
    restart: unless-stopped
    network_mode: host
    cap_add:
      - NET_RAW
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      PS_IP: "192.168.9.22"
      DETECTION_METHODS: "ddp,tcp"
      THROTTLE_DOWN_KB: "50"
      THROTTLE_UP_KB: "20"
```

## PlayStation Detection Methods

ps-throttle uses multiple detection methods, tried in order of reliability:

| Method | How it works | Standby-aware? | Reliability |
|--------|-------------|----------------|-------------|
| **DDP** | Sony's Device Discovery Protocol (UDP 987). Directly reports `AWAKE` vs `STANDBY` | ✅ Yes | ⭐⭐⭐ Best |
| **TCP** | Probes port 9295 (Remote Play). Only open when PS is fully ON | ✅ Yes | ⭐⭐ Good |
| **Ping** | ICMP ping. PS responds even in standby if "Stay Connected" is enabled | ❌ No | ⭐ Fallback |

### Recommended configuration

```yaml
# Best: DDP + TCP (default). Don't use ping alone - can't tell standby from active!
DETECTION_METHODS: "ddp,tcp"
```

### PlayStation Requirements

For DDP detection to work, enable these on your PlayStation:
- **Settings → System → Power Saving → Features Available in Rest Mode**:
  - ✅ Stay Connected to the Internet
  - ✅ Enable Turning on PS from Network

## Self-Discovery

ps-throttle automatically discovers Transmission containers by:

1. **Scanning Docker** for running containers whose image or name contains `transmission`
2. **Extracting RPC port** from container port mappings (default: 9091)
3. **Extracting credentials** from container environment variables:
   - `TRANSMISSION_RPC_USERNAME` / `TRANSMISSION_RPC_PASSWORD`
   - `USER` / `PASS` (LinuxServer.io images)
   - Or falls back to `TRANSMISSION_USER` / `TRANSMISSION_PASS` env vars on ps-throttle itself

Supported Transmission images include:
- `linuxserver/transmission`
- `haugene/transmission-openvpn`
- `transmission/transmission` (official)
- Any image with "transmission" in the name

## Configuration

All settings are configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PS_IP` | `192.168.9.22` | PlayStation IP address |
| `CHECK_INTERVAL` | `10` | Seconds between each check |
| `DEBOUNCE_COUNT` | `5` | Consecutive inactive checks before PS is considered OFF |
| `DETECTION_METHODS` | `ddp,tcp` | Comma-separated detection methods (ddp, tcp, ping) |
| `DDP_PORT` | `987` | UDP port for DDP protocol |
| `DDP_TIMEOUT` | `2.0` | DDP response timeout (seconds) |
| `TCP_PROBE_PORT` | `9295` | TCP port to probe (Remote Play) |
| `TCP_PROBE_TIMEOUT` | `1.5` | TCP probe timeout (seconds) |
| `THROTTLE_DOWN_KB` | `50` | Download limit when PS is active (KB/s) |
| `THROTTLE_UP_KB` | `20` | Upload limit when PS is active (KB/s) |
| `TRANSMISSION_FILTER` | `transmission` | Filter string for Docker container discovery |
| `DISCOVERY_INTERVAL` | `60` | Seconds between container re-discovery |
| `TRANSMISSION_USER` | _(empty)_ | Fallback RPC username |
| `TRANSMISSION_PASS` | _(empty)_ | Fallback RPC password |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  ps-throttle                      │
│                                                   │
│  ┌─────────────┐   ┌──────────────────────────┐  │
│  │ PS Detector  │   │   Docker Discovery       │  │
│  │              │   │                          │  │
│  │ • DDP (987)  │   │ • Scans Docker socket    │  │
│  │ • TCP (9295) │   │ • Finds Transmission     │  │
│  │ • Ping       │   │ • Extracts RPC config    │  │
│  │ • Debounce   │   │ • Auto re-discovery      │  │
│  └──────┬───────┘   └────────────┬─────────────┘  │
│         │                        │                 │
│         ▼                        ▼                 │
│  ┌────────────────────────────────────────────┐   │
│  │           Main Loop (every 10s)            │   │
│  │                                            │   │
│  │  PS active?  ──YES──▶  Throttle all        │   │
│  │  PS inactive? ──YES──▶  Restore all        │   │
│  └────────────────────────────────────────────┘   │
│         │                                          │
│         ▼                                          │
│  ┌────────────────────────────────────────────┐   │
│  │       Transmission Throttler (per instance) │   │
│  │                                            │   │
│  │  • Save original limits                    │   │
│  │  • Apply throttle via RPC                  │   │
│  │  • Restore original limits                 │   │
│  └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
    🎮 PlayStation      📥 Transmission (Docker)
    192.168.9.22        Auto-discovered via socket
```

## Graceful Shutdown

When ps-throttle stops (SIGTERM/SIGINT), it automatically **restores all original speed limits** before exiting. Your Transmission instances will never be left in a throttled state.

## Troubleshooting

### ps-throttle doesn't detect my PlayStation

1. Make sure the PS and Orange Pi are on the same subnet
2. Try setting `LOG_LEVEL: "DEBUG"` to see detection details
3. Check if DDP works: `echo -ne "SRCH * HTTP/1.1\r\ndevice-discovery-protocol-version:00030010\r\n\r\n" | nc -u -w2 192.168.9.22 987`
4. Try TCP probe: `nc -zv 192.168.9.22 9295`

### ps-throttle doesn't find my Transmission containers

1. Check the Docker socket is mounted: `-v /var/run/docker.sock:/var/run/docker.sock:ro`
2. Make sure the container name or image contains "transmission" (or change `TRANSMISSION_FILTER`)
3. Set `LOG_LEVEL: "DEBUG"` to see discovery details

### Detection works but throttle doesn't apply

1. Check if Transmission RPC is accessible
2. Verify credentials: try connecting manually with `transmission-remote`
3. Check ps-throttle logs for authentication errors

## License

MIT License - see [LICENSE](LICENSE) file.
