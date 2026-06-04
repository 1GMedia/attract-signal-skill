# Attract Signal Skill

A shareable Hermes/Codex skill for industry-agnostic short-form content signal intelligence: high-performing YouTube Shorts, repeatable hooks, visual mechanics, audience-response patterns, source citations, and strategy angles that can become original scripts, shot lists, storyboard prompts, and 30-day content calendars.

Default example channel:

```text
https://www.youtube.com/@_The_Clean_Girl/shorts
```

## What It Does

- Scans one or more YouTube channel Shorts tabs with `yt-dlp`.
- Filters winners by likes, defaulting to `10,000+`.
- Collects views, likes, comments, source URLs, thumbnails, baselines, normalized engagement, relative performance, and signal scores.
- Supports `--cookies-from-browser` / `--cookies` for YouTube sign-in or bot checks.
- Produces JSON, Markdown, and CSV strategy artifacts.
- Guides the agent to fetch transcripts, analyze hooks and visual hooks, and turn content signals into original brand-safe strategy concepts for any industry.
- Supports optional Google Docs delivery through `gogcli`.

## Requirements

```bash
python3 -m pip install -U yt-dlp youtube-transcript-api
```

Optional Google Docs publishing:

```bash
brew install openclaw/tap/gogcli
gog auth status
```

## Install The Skill

From this repository:

```bash
./install.sh
```

That copies:

```text
skills/media/attract-signal
```

to:

```text
~/.hermes/skills/media/attract-signal
```

## Run The Scanner Directly

```bash
python3 skills/media/attract-signal/scripts/scan_shorts.py \
  "https://www.youtube.com/@_The_Clean_Girl/shorts" \
  --min-likes 10000 \
  --max-videos 20 \
  --cookies-from-browser chrome \
  --out ./clean-girl-shorts.json \
  --markdown ./clean-girl-shorts.md
```

If YouTube blocks metadata with a sign-in or bot check, use one of:

```bash
--cookies-from-browser chrome
--cookies /path/to/youtube-cookies.txt
```

## Analyze Multiple Channels

Run one scan per channel, then combine them:

```bash
python3 skills/media/attract-signal/scripts/analyze_signals.py \
  ./channel-1.json ./channel-2.json \
  --out ./signals.json \
  --top 25
```

## Generate A Strategy Report

Generic, industry-agnostic report:

```bash
python3 skills/media/attract-signal/scripts/generate_report.py \
  --signals ./signals.json \
  --transcripts-dir ./transcripts \
  --out ./attract-signal-report.md \
  --calendar ./content-calendar.csv
```

Brand-specific report:

```bash
python3 skills/media/attract-signal/scripts/generate_report.py \
  --signals ./signals.json \
  --brand examples/brand.example.yaml \
  --transcripts-dir ./transcripts \
  --out ./attract-signal-report.md \
  --calendar ./content-calendar.csv
```

Transcript files should be JSON files from `fetch_transcript.py`, named by video ID:

```bash
python3 skills/media/attract-signal/scripts/fetch_transcript.py \
  "https://www.youtube.com/shorts/VIDEO_ID" \
  --timestamps > ./transcripts/VIDEO_ID.json
```

`brand.yaml` fields are intentionally industry-neutral:

```yaml
brand_name: Example Brand
industry: local service business
audience: busy homeowners who want trustworthy help
offer: a clear, reliable service package
tone: helpful, direct, practical, and warm
proof_points:
  - before-and-after results
constraints:
  - film with a phone
filming_resources:
  - owner on camera
forbidden_claims:
  - guaranteed results
```

## Agent Usage

After installation, ask Hermes/Codex:

```text
Use attract-signal to scan this channel's Shorts, find videos over 10,000 likes, analyze the trend type, hook, visual hooks, transcript structure, and turn the strongest content signals into an original strategy, scripts, and shot list for my brand with source citations.
```

```text
Analyze these 5 channels for content signals and make me a 30-day content strategy for my brand.
```

```text
Use attract-signal for a skincare brand, a restaurant, or a SaaS founder. Keep the strategy industry-specific only after I provide brand context.
```

The skill intentionally tells the agent to cite every source Short and to avoid copying exact scripts, premises, edits, or creator footage.

## Google Docs Output

The skill can publish a finished Markdown report with `gogcli` after user approval:

```bash
gog docs create "YouTube Shorts Trend Brief - Channel Name" --file brief.md --json
```

Writes/shares should always be approved by the user first.
