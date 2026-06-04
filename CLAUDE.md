# Attract Signal Repo Guidance

Use the canonical skill at `skills/media/attract-signal/SKILL.md`.

This repository is intended to work across Hermes, Codex, and Claude. Do not fork the workflow per agent. Keep the core skill instructions and Python scripts portable, then use `./install.sh hermes`, `./install.sh codex`, `./install.sh claude`, or `./install.sh all` to copy the same skill folder into the target agent's skill directory.

Local Markdown and CSV outputs are the universal deliverables. Google Docs and Google Sheets publishing are optional `gogcli` enhancements; if `gog` is missing or unauthenticated, keep the local artifacts and report the missing install/auth step.

Never invent product names, offers, prices, coupon codes, ingredients, safety claims, or performance claims. Product-specific report language must come from `brand.yaml` or a verified website/product URL.
