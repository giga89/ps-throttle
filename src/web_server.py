"""
Web server module for ps-throttle.

Provides a lightweight, embedded HTTP server with:
- Web Dashboard (HTML/CSS/JS) showing real-time status of PlayStation,
  limiter state, and discovered Transmission instances.
- REST API (/api/status, /api/health) for JSON monitoring.
"""

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Optional

logger = logging.getLogger("ps-throttle.web")


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ps-throttle | PlayStation Bandwidth Guardian</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #07090e;
      --bg-card: rgba(16, 22, 36, 0.75);
      --bg-card-hover: rgba(23, 32, 54, 0.85);
      --bg-card-subtle: rgba(255, 255, 255, 0.03);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-highlight: rgba(99, 102, 241, 0.3);
      --accent-ps: #0070d1;
      --accent-ps-glow: rgba(0, 112, 209, 0.35);
      --accent-active: #ef4444;
      --accent-active-glow: rgba(239, 68, 68, 0.3);
      --accent-idle: #10b981;
      --accent-idle-glow: rgba(16, 185, 129, 0.25);
      --accent-warning: #f59e0b;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --radius-sm: 8px;
      --radius-md: 14px;
      --radius-lg: 20px;
      --font-main: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg-dark);
      background-image: 
        radial-gradient(at 0% 0%, rgba(0, 112, 209, 0.15) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(99, 102, 241, 0.12) 0px, transparent 50%),
        radial-gradient(at 50% 50%, rgba(15, 23, 42, 0.5) 0px, transparent 100%);
      background-attachment: fixed;
      color: var(--text-main);
      font-family: var(--font-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      padding: 24px 16px;
      line-height: 1.5;
    }

    .container {
      max-width: 1100px;
      margin: 0 auto;
      width: 100%;
    }

    /* Header */
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 28px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border-subtle);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .brand-icon {
      font-size: 32px;
      width: 52px;
      height: 52px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, rgba(0, 112, 209, 0.3), rgba(99, 102, 241, 0.2));
      border: 1px solid rgba(0, 112, 209, 0.4);
      border-radius: var(--radius-md);
      box-shadow: 0 0 20px var(--accent-ps-glow);
    }

    .brand-title {
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.5px;
      background: linear-gradient(135deg, #ffffff 40%, #93c5fd 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .brand-subtitle {
      font-size: 13px;
      color: var(--text-muted);
      font-weight: 500;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .refresh-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: var(--bg-card-subtle);
      border: 1px solid var(--border-subtle);
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 13px;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }

    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background-color: var(--accent-idle);
      box-shadow: 0 0 8px var(--accent-idle);
      animation: pulse 2s infinite ease-in-out;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.8); }
    }

    .btn-refresh {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      padding: 8px 16px;
      border-radius: var(--radius-sm);
      font-family: var(--font-main);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
    }

    .btn-refresh:hover {
      background: rgba(255, 255, 255, 0.1);
      border-color: var(--border-highlight);
      transform: translateY(-1px);
    }

    /* Hero Banner */
    .hero-banner {
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-radius: var(--radius-lg);
      border: 1px solid var(--border-subtle);
      padding: 24px 30px;
      margin-bottom: 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 20px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
      position: relative;
      overflow: hidden;
    }

    .hero-banner::before {
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: 6px;
      background: var(--accent-idle);
      transition: background 0.3s ease;
    }

    .hero-banner.is-throttled::before {
      background: var(--accent-active);
    }

    .hero-banner.is-debouncing::before {
      background: var(--accent-warning);
    }

    .hero-left {
      display: flex;
      align-items: center;
      gap: 20px;
    }

    .status-badge-large {
      padding: 10px 20px;
      border-radius: var(--radius-md);
      font-weight: 700;
      font-size: 15px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }

    .status-badge-large.idle {
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: #34d399;
      box-shadow: 0 0 20px var(--accent-idle-glow);
    }

    .status-badge-large.throttled {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.4);
      color: #f87171;
      box-shadow: 0 0 20px var(--accent-active-glow);
    }

    .status-badge-large.debouncing {
      background: rgba(245, 158, 11, 0.15);
      border: 1px solid rgba(245, 158, 11, 0.4);
      color: #fbbf24;
      box-shadow: 0 0 20px rgba(245, 158, 11, 0.25);
    }

    .hero-headline {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 4px;
    }

    .hero-desc {
      font-size: 14px;
      color: var(--text-muted);
    }

    .hero-stats {
      display: flex;
      align-items: center;
      gap: 24px;
    }

    .hero-stat-item {
      text-align: right;
    }

    .hero-stat-label {
      font-size: 12px;
      text-transform: uppercase;
      color: var(--text-dim);
      font-weight: 600;
      letter-spacing: 0.5px;
    }

    .hero-stat-value {
      font-size: 18px;
      font-weight: 700;
      font-family: var(--font-mono);
      color: var(--text-main);
    }

    /* Grid Layout */
    .grid-2 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 24px;
      margin-bottom: 28px;
    }

    .card {
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 24px;
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
      transition: all 0.2s ease;
    }

    .card:hover {
      border-color: var(--border-highlight);
      background: var(--bg-card-hover);
    }

    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
    }

    .card-title {
      font-size: 16px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text-main);
    }

    .pill {
      font-size: 12px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .pill.green {
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
    }

    .pill.red {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #f87171;
    }

    .pill.blue {
      background: rgba(0, 112, 209, 0.15);
      border: 1px solid rgba(0, 112, 209, 0.3);
      color: #60a5fa;
    }

    .pill.gray {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
    }

    .data-list {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .data-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }

    .data-row:last-child {
      border-bottom: none;
      padding-bottom: 0;
    }

    .data-label {
      font-size: 14px;
      color: var(--text-muted);
      font-weight: 500;
    }

    .data-val {
      font-size: 14px;
      font-weight: 600;
      font-family: var(--font-mono);
      color: var(--text-main);
    }

    /* Transmission Section */
    .section-title {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .instance-counter {
      font-size: 13px;
      font-weight: 600;
      padding: 4px 12px;
      border-radius: 999px;
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid rgba(99, 102, 241, 0.3);
      color: #a5b4fc;
    }

    .instances-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 20px;
      margin-bottom: 28px;
    }

    .instance-card {
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 22px;
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
      position: relative;
      transition: all 0.2s ease;
    }

    .instance-card:hover {
      border-color: var(--border-highlight);
      background: var(--bg-card-hover);
    }

    .instance-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 16px;
    }

    .instance-name {
      font-size: 16px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .instance-endpoint {
      font-size: 12px;
      font-family: var(--font-mono);
      color: var(--text-dim);
    }

    .speed-meters {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin: 16px 0;
    }

    .speed-box {
      background: var(--bg-card-subtle);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: var(--radius-md);
      padding: 12px;
      text-align: center;
    }

    .speed-box.down .speed-val {
      color: #38bdf8;
    }

    .speed-box.up .speed-val {
      color: #a78bfa;
    }

    .speed-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-dim);
      font-weight: 600;
      margin-bottom: 4px;
    }

    .speed-val {
      font-size: 18px;
      font-weight: 700;
      font-family: var(--font-mono);
    }

    .limit-tag {
      font-size: 11px;
      color: var(--text-muted);
      margin-top: 4px;
    }

    .empty-state {
      background: var(--bg-card);
      border: 1px dashed var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 40px 24px;
      text-align: center;
      margin-bottom: 28px;
    }

    .empty-icon {
      font-size: 40px;
      margin-bottom: 12px;
      opacity: 0.6;
    }

    .empty-title {
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 6px;
    }

    .empty-desc {
      font-size: 14px;
      color: var(--text-muted);
      max-width: 500px;
      margin: 0 auto;
    }

    /* Footer */
    footer {
      margin-top: auto;
      padding-top: 20px;
      border-top: 1px solid var(--border-subtle);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      font-size: 13px;
      color: var(--text-dim);
    }

    .footer-link {
      color: var(--text-muted);
      text-decoration: none;
      transition: color 0.2s;
    }

    .footer-link:hover {
      color: #93c5fd;
    }

    @media (max-width: 640px) {
      .hero-banner {
        flex-direction: column;
        align-items: flex-start;
      }
      .hero-stats {
        width: 100%;
        justify-content: space-between;
      }
      .hero-stat-item {
        text-align: left;
      }
      header {
        flex-direction: column;
        align-items: flex-start;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <header>
      <div class="brand">
        <div class="brand-icon">🎮</div>
        <div>
          <h1 class="brand-title">ps-throttle</h1>
          <p class="brand-subtitle">PlayStation Bandwidth Guardian for Transmission</p>
        </div>
      </div>
      <div class="header-actions">
        <div class="refresh-badge">
          <span class="pulse-dot" id="liveDot"></span>
          <span id="refreshTimer">Auto: 3s</span>
        </div>
        <button class="btn-refresh" id="btnRefresh" onclick="fetchStatus()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
          </svg>
          Refresh
        </button>
      </div>
    </header>

    <!-- Hero State Banner -->
    <div class="hero-banner" id="heroBanner">
      <div class="hero-left">
        <div class="status-badge-large idle" id="heroStatusBadge">
          <span id="heroStatusText">🟢 UNTHROTTLED</span>
        </div>
        <div>
          <div class="hero-headline" id="heroHeadline">Full Bandwidth Available</div>
          <div class="hero-desc" id="heroDesc">PlayStation is inactive. Transmission running at full speed.</div>
        </div>
      </div>
      <div class="hero-stats">
        <div class="hero-stat-item">
          <div class="hero-stat-label">PS IP</div>
          <div class="hero-stat-value" id="heroPsIp">---</div>
        </div>
        <div class="hero-stat-item">
          <div class="hero-stat-label">Instances</div>
          <div class="hero-stat-value" id="heroInstanceCount">0</div>
        </div>
      </div>
    </div>

    <!-- 2-Column Overview Cards -->
    <div class="grid-2">
      <!-- PlayStation Monitor Card -->
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">
            <span>🎮</span> PlayStation Detection
          </h2>
          <span class="pill gray" id="psStatusPill">Checking...</span>
        </div>
        <div class="data-list">
          <div class="data-row">
            <span class="data-label">Target IP</span>
            <span class="data-val" id="psIpVal">---</span>
          </div>
          <div class="data-row">
            <span class="data-label">Active Detection Method</span>
            <span class="data-val" id="psMethodVal">---</span>
          </div>
          <div class="data-row">
            <span class="data-label">Detection Methods Configured</span>
            <span class="data-val" id="psMethodsConfig">---</span>
          </div>
          <div class="data-row">
            <span class="data-label">Debounce Status</span>
            <span class="data-val" id="psDebounceVal">0 / 5</span>
          </div>
          <div class="data-row">
            <span class="data-label">Check Interval</span>
            <span class="data-val" id="psIntervalVal">10s</span>
          </div>
        </div>
      </div>

      <!-- Limiter Engine Card -->
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">
            <span>⚡</span> Speed Limiter Engine
          </h2>
          <span class="pill gray" id="limiterStatusPill">Checking...</span>
        </div>
        <div class="data-list">
          <div class="data-row">
            <span class="data-label">Limiter State</span>
            <span class="data-val" id="limiterStateVal">---</span>
          </div>
          <div class="data-row">
            <span class="data-label">Gaming Throttle (Down)</span>
            <span class="data-val" id="throttleDownVal">50 KB/s</span>
          </div>
          <div class="data-row">
            <span class="data-label">Gaming Throttle (Up)</span>
            <span class="data-val" id="throttleUpVal">20 KB/s</span>
          </div>
          <div class="data-row">
            <span class="data-label">Docker Discovery Filter</span>
            <span class="data-val" id="filterVal">transmission</span>
          </div>
          <div class="data-row">
            <span class="data-label">Uptime</span>
            <span class="data-val" id="uptimeVal">0s</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Discovered Transmission Instances -->
    <div class="section-title">
      <span>📦 Discovered Transmission Containers</span>
      <span class="instance-counter" id="instanceCounter">0 Instances</span>
    </div>

    <div id="instancesContainer">
      <div class="empty-state">
        <div class="empty-icon">🔍</div>
        <div class="empty-title">Scanning for Transmission Containers...</div>
        <div class="empty-desc">
          ps-throttle is automatically inspecting Docker for running containers matching the filter.
        </div>
      </div>
    </div>

    <!-- Footer -->
    <footer>
      <div>ps-throttle • PlayStation Bandwidth Guardian</div>
      <div>
        <a class="footer-link" href="https://github.com/giga89/ps-throttle" target="_blank" rel="noopener">GitHub Repository</a>
      </div>
    </footer>
  </div>

  <script>
    function formatBytes(bytes, decimals = 1) {
      if (!bytes || bytes === 0) return '0 KB/s';
      const k = 1024;
      const dm = decimals < 0 ? 0 : decimals;
      const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    function formatUptime(seconds) {
      const d = Math.floor(seconds / (3600*24));
      const h = Math.floor(seconds % (3600*24) / 3600);
      const m = Math.floor(seconds % 3600 / 60);
      const s = Math.floor(seconds % 60);
      const parts = [];
      if (d > 0) parts.push(d + 'd');
      if (h > 0) parts.push(h + 'h');
      if (m > 0) parts.push(m + 'm');
      parts.push(s + 's');
      return parts.join(' ');
    }

    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        render(data);
      } catch (err) {
        console.error('Status fetch error:', err);
        document.getElementById('liveDot').style.backgroundColor = '#ef4444';
      }
    }

    function render(data) {
      document.getElementById('liveDot').style.backgroundColor = 'var(--accent-idle)';

      // PlayStation details
      const psActive = data.ps_active;
      const psDetails = data.ps_details || {};
      const psPill = document.getElementById('psStatusPill');
      
      document.getElementById('psIpVal').textContent = data.ps_ip || '---';
      document.getElementById('heroPsIp').textContent = data.ps_ip || '---';
      
      if (psActive) {
        psPill.className = 'pill red';
        psPill.textContent = '● ACTIVE GAMING';
      } else {
        psPill.className = 'pill green';
        psPill.textContent = '○ INACTIVE / STANDBY';
      }

      document.getElementById('psMethodVal').textContent = psDetails.last_method ? psDetails.last_method.toUpperCase() : 'None';
      document.getElementById('psMethodsConfig').textContent = (psDetails.detection_methods || []).join(', ').toUpperCase() || 'DDP, TCP';
      document.getElementById('psDebounceVal').textContent = `${psDetails.consecutive_inactive || 0} / ${psDetails.debounce_count || 5} checks`;
      document.getElementById('psIntervalVal').textContent = `${psDetails.check_interval || 10}s`;

      // Limiter details
      const isThrottled = data.is_throttled;
      const isDebouncing = !psActive && (psDetails.consecutive_inactive > 0 && psDetails.consecutive_inactive < (psDetails.debounce_count || 5));
      const limiterPill = document.getElementById('limiterStatusPill');
      const heroBanner = document.getElementById('heroBanner');
      const heroStatusBadge = document.getElementById('heroStatusBadge');
      const heroStatusText = document.getElementById('heroStatusText');
      const heroHeadline = document.getElementById('heroHeadline');
      const heroDesc = document.getElementById('heroDesc');

      if (isThrottled) {
        limiterPill.className = 'pill red';
        limiterPill.textContent = '🔴 THROTTLED';
        document.getElementById('limiterStateVal').textContent = 'ACTIVE (Limited)';

        heroBanner.className = 'hero-banner is-throttled';
        heroStatusBadge.className = 'status-badge-large throttled';
        heroStatusText.textContent = '🔴 GAMING ACTIVE • THROTTLED';
        heroHeadline.textContent = 'PlayStation Gaming Detected!';
        heroDesc.textContent = `Transmission bandwidth is throttled to ${data.throttle_config.down_kb} KB/s ↓ to ensure zero gaming lag.`;
      } else if (isDebouncing) {
        limiterPill.className = 'pill yellow';
        limiterPill.textContent = '🟡 DEBOUNCING';
        document.getElementById('limiterStateVal').textContent = 'WAITING CONFIRMATION';

        heroBanner.className = 'hero-banner is-debouncing';
        heroStatusBadge.className = 'status-badge-large debouncing';
        heroStatusText.textContent = '🟡 COOLDOWN / DEBOUNCING';
        heroHeadline.textContent = 'PlayStation Activity Paused';
        heroDesc.textContent = `Confirming console shutdown (${psDetails.consecutive_inactive}/${psDetails.debounce_count}) before restoring full speed...`;
      } else {
        limiterPill.className = 'pill green';
        limiterPill.textContent = '🟢 NORMAL / UNRESTRICTED';
        document.getElementById('limiterStateVal').textContent = 'IDLE (Full Speed)';

        heroBanner.className = 'hero-banner';
        heroStatusBadge.className = 'status-badge-large idle';
        heroStatusText.textContent = '🟢 FULL SPEED • IDLE';
        heroHeadline.textContent = 'PlayStation is Inactive';
        heroDesc.textContent = 'All Transmission instances are downloading at unrestricted full bandwidth.';
      }

      document.getElementById('throttleDownVal').textContent = `${data.throttle_config.down_kb} KB/s`;
      document.getElementById('throttleUpVal').textContent = `${data.throttle_config.up_kb} KB/s`;
      document.getElementById('filterVal').textContent = data.discovery_filter || 'transmission';
      document.getElementById('uptimeVal').textContent = formatUptime(data.uptime_seconds || 0);

      // Transmission Instances
      const instances = data.transmission_instances || [];
      const count = instances.length;
      document.getElementById('heroInstanceCount').textContent = count;
      document.getElementById('instanceCounter').textContent = `${count} Instance${count === 1 ? '' : 's'} Discovered`;

      const instancesContainer = document.getElementById('instancesContainer');

      if (count === 0) {
        instancesContainer.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">⚠️</div>
            <div class="empty-title">No Transmission Containers Found</div>
            <div class="empty-desc">
              ps-throttle is monitoring Docker for containers matching filter <code>${data.discovery_filter || 'transmission'}</code>.<br>
              Make sure your Transmission container is running and <code>/var/run/docker.sock</code> is mounted.
            </div>
          </div>
        `;
      } else {
        let html = '<div class="instances-grid">';
        for (const inst of instances) {
          const isConnected = inst.connected;
          const throttled = inst.throttled;
          const statusPill = isConnected 
            ? (throttled ? '<span class="pill red">🔴 Throttled</span>' : '<span class="pill green">🟢 Normal</span>')
            : '<span class="pill gray">⚠️ Offline</span>';

          const downRate = formatBytes(inst.download_speed || 0);
          const upRate = formatBytes(inst.upload_speed || 0);
          const activeTorrents = inst.active_torrents || 0;
          const totalTorrents = inst.torrent_count || 0;

          html += `
            <div class="instance-card">
              <div class="instance-header">
                <div>
                  <div class="instance-name">
                    <span>📦</span> ${inst.name}
                  </div>
                  <div class="instance-endpoint">${inst.host}:${inst.port}</div>
                </div>
                <div>${statusPill}</div>
              </div>

              <div class="speed-meters">
                <div class="speed-box down">
                  <div class="speed-label">Download</div>
                  <div class="speed-val">${downRate}</div>
                  <div class="limit-tag">${inst.speed_limit_down_enabled ? 'Limit: ' + inst.speed_limit_down + ' KB/s' : 'Unlimited'}</div>
                </div>
                <div class="speed-box up">
                  <div class="speed-label">Upload</div>
                  <div class="speed-val">${upRate}</div>
                  <div class="limit-tag">${inst.speed_limit_up_enabled ? 'Limit: ' + inst.speed_limit_up + ' KB/s' : 'Unlimited'}</div>
                </div>
              </div>

              <div class="data-list" style="margin-top: 14px;">
                <div class="data-row">
                  <span class="data-label">Active Torrents</span>
                  <span class="data-val">${activeTorrents} / ${totalTorrents}</span>
                </div>
                <div class="data-row">
                  <span class="data-label">RPC Authentication</span>
                  <span class="data-val">${inst.auth_enabled ? 'Enabled' : 'None'}</span>
                </div>
                ${inst.error ? `
                <div class="data-row">
                  <span class="data-label" style="color: #f87171;">Status Notice</span>
                  <span class="data-val" style="color: #f87171; font-size: 12px;">${inst.error}</span>
                </div>
                ` : ''}
              </div>
            </div>
          `;
        }
        html += '</div>';
        instancesContainer.innerHTML = html;
      }
    }

    // Initial load
    fetchStatus();

    // Auto-refresh every 3 seconds
    setInterval(fetchStatus, 3000);
  </script>
</body>
</html>
"""


try:
    from http.server import ThreadingHTTPServer as DefaultHTTPServer
except ImportError:
    from http.server import HTTPServer as DefaultHTTPServer


class StatusHTTPServer(DefaultHTTPServer):
    """HTTP Server that holds reference to status_provider callable."""
    def __init__(self, server_address, RequestHandlerClass, status_provider=None):
        self.status_provider = status_provider
        super().__init__(server_address, RequestHandlerClass)


class PSThrottleHTTPRequestHandler(BaseHTTPRequestHandler):
    """Custom HTTP request handler for ps-throttle dashboard and API."""

    def log_message(self, format, *args):
        """Suppress default HTTP request logging to keep console clean."""
        pass

    def _send_response(self, status_code: int, content_type: str, body: bytes):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self):
        """Handle GET requests."""
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            # Serve Web Dashboard
            content = HTML_DASHBOARD.encode("utf-8")
            self._send_response(200, "text/html; charset=utf-8", content)

        elif path == "/api/status":
            # Serve JSON Status
            provider = getattr(self.server, "status_provider", None)
            if provider:
                try:
                    data = provider()
                except Exception as e:
                    logger.error("Error generating status data: %s", e)
                    data = {"error": str(e)}
            else:
                data = {"status": "running"}

            content = json.dumps(data).encode("utf-8")
            self._send_response(200, "application/json", content)

        elif path == "/api/health":
            # Healthcheck
            content = json.dumps({"status": "healthy"}).encode("utf-8")
            self._send_response(200, "application/json", content)

        else:
            # 404 Not Found
            self._send_response(404, "text/plain", b"Not Found")


class PSThrottleWebServer:
    """Manages the background web server thread."""

    def __init__(self, host: str, port: int, status_provider: Callable[[], dict]):
        self.host = host
        self.port = port
        self.status_provider = status_provider
        self.server: Optional[StatusHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self):
        """Start the web server in a background daemon thread."""
        try:
            self.server = StatusHTTPServer(
                (self.host, self.port),
                PSThrottleHTTPRequestHandler,
                status_provider=self.status_provider,
            )
            self.thread = threading.Thread(
                target=self.server.serve_forever,
                name="ps-throttle-web",
                daemon=True,
            )
            self.thread.start()
            logger.info("🌐 Web dashboard listening at http://%s:%d",
                        "localhost" if self.host == "0.0.0.0" else self.host,
                        self.port)
        except Exception as e:
            logger.error("Failed to start web server on %s:%d: %s", self.host, self.port, e)

    def stop(self):
        """Stop the web server cleanly."""
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=1.0)
                logger.info("🌐 Web server stopped")
            except Exception as e:
                logger.warning("Error stopping web server: %s", e)
