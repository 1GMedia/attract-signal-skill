# Attract Signal Skill

A shareable Hermes/Codex skill for finding the meaningful signal inside short-form content: high-performing YouTube Shorts, repeatable hooks, visual mechanics, audience-response patterns, source citations, and content strategy angles that can become original scripts, shot lists, and storyboard prompts.

Default example channel:

```text
https://www.youtube.com/@_The_Clean_Girl/shorts
```

## What It Does

- Scans any YouTube channel Shorts tab with `yt-dlp`.
- Filters winners by likes, defaulting to `10,000+`.
- Collects views, likes, comments, source URLs, thumbnails, and basic metadata.
- Supports `--cookies-from-browser` / `--cookies` for YouTube sign-in or bot checks.
- Produces JSON and Markdown scan artifacts.
- Guides the agent to fetch transcripts, analyze hooks and visual hooks, and turn content signals into original brand-safe strategy concepts.
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

## Agent Usage

After installation, ask Hermes/Codex:

```text
Use attract-signal to scan this channel's Shorts, find videos over 10,000 likes, analyze the trend type, hook, visual hooks, transcript structure, and turn the strongest content signals into an original strategy, scripts, and shot list for my brand with source citations.
```

The skill intentionally tells the agent to cite every source Short and to avoid copying exact scripts, premises, edits, or creator footage.

## Google Docs Output

The skill can publish a finished Markdown report with `gogcli` after user approval:

```bash
gog docs create "YouTube Shorts Trend Brief - Channel Name" --file brief.md --json
```

Writes/shares should always be approved by the user first.
