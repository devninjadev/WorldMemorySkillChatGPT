# World Memory Autopilot

World Memory Autopilot is a ChatGPT skill for hourly feed monitoring and six-hour World Memory integration backed by a registered Notion v2 ledger.

## Required dependency

- `Notion ChatGPT plugin` (the Notion connector for ChatGPT) is required. Install and connect it to ChatGPT, then grant it access to the Notion workspace that will hold the World Memory Hub and databases.
- Python 3.10 or later is required for the packaged deterministic helpers. The market adapter can install its pinned `yfinance`, `pandas`, `numpy`, and `xlrd` dependencies into an isolated runtime directory when they are not already available.
- Outbound HTTPS access is required for configured RSS feeds and public market-data sources.
- ChatGPT scheduled automations are required only for unattended hourly monitoring; manual runs do not require a schedule.

World Memory setup and operational runs must stop if the Notion ChatGPT plugin is unavailable or cannot access the target workspace.

## Install

Download the `world-memory-autopilot-v0.9.5.zip` asset from the GitHub release and install or import it as a ChatGPT skill. The archive contains one top-level `world-memory-autopilot` folder.

## Repository layout

- `world-memory-autopilot/SKILL.md`: core agent workflow and safety contract
- `world-memory-autopilot/scripts/`: deterministic validation, scheduling, feed, storage, and market-data helpers
- `world-memory-autopilot/references/`: storage, source, analysis, and market-data contracts
- `world-memory-autopilot/tests/`: regression and hardening tests

## Version

This repository snapshot is release `v0.9.5`.
