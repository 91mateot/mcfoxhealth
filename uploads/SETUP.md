---
name: setup-guide
---

# Health System — Setup Guide

## 1. Install MCP Servers

```bash
claude mcp add strava -- npx -y @r-huijts/strava-mcp-server
claude mcp add withings -- npx -y @gchallen/withings-mcp
claude mcp list
```

**Strava:** https://www.strava.com/settings/api → Create app, note Client ID/Secret, callback: localhost
**Withings:** https://developer.withings.com/dashboard/ → Create app, callback: http://localhost:3000/callback

## 2. Apple Health Bridge (iOS Shortcut)
Build Shortcut → pull HRV, resting HR, resp rate, sleep → JSON → iCloud/Obsidian Sync → `Inputs/Health/Raw/`

## 3. Daily Commands
```
"morning briefing"
"log workout: push day, bench 4x8 at 185..."
"had rotisserie chicken and brussels sprouts for lunch"
"end of day report"
"weekly review"
```

## 4. Architecture
```
Devices → MCP Servers → Claude Code → Skills → MateoVault → Outputs
```
