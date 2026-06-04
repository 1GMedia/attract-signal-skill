---
name: attract-signal
description: "Use when scanning YouTube Shorts or short-form channels for content signals: high-performing videos, transcript/metadata citations, trend types, hooks, visual hooks, repeatable formats, and brand-specific content strategy briefs, scripts, shot lists, storyboards, or Google Docs."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
required_commands:
  - yt-dlp
metadata:
  hermes:
    tags: [youtube, shorts, trend-analysis, content-strategy, scriptwriting, citations]
    related_skills: [youtube-content, gogcli, google-workspace]
---

# Attract Signal

## Overview

This skill turns YouTube Shorts channels into reusable content-intelligence briefs. It is designed for competitive/trend research where the user wants to find high-performing Shorts, understand why they worked, and translate the underlying signal into original brand strategy without copying the original. It is industry-agnostic by default: do not assume tattoo, beauty, SaaS, local services, restaurants, ecommerce, coaching, fitness, or any other niche unless the user provides that context.

Default example channel for testing:

```text
https://www.youtube.com/@_The_Clean_Girl/shorts
```

The standard threshold is **10,000+ likes**, but the user can change it. Always cite source Shorts links in the output.

## When to Use

Use this skill when the user asks to:

- Scan one or more YouTube channels' Shorts for winners.
- Filter Shorts by likes/views/engagement.
- Analyze hooks, visual hooks, formats, content trends, and transcript patterns.
- Create a signal and trend breakdown that can become original scripts, shot lists, Google Docs, or storyboards.
- Build a source-cited content signal library.
- Create an industry-agnostic or brand-specific 30-day content strategy.

Don't use this for long-form YouTube summaries only; use `youtube-content` directly for single-video transcript transforms.

## Related Skills / Tools

- Bundled `scripts/fetch_transcript.py` — fetches transcripts from individual Shorts or videos.
- `youtube-content` — optional fallback transcript skill if already installed.
- `gogcli` — preferred Google CLI for later writing briefs/scripts into Google Docs (`brew install openclaw/tap/gogcli`).
- `google-workspace` — existing Hermes Google Workspace fallback if `gog`/`gogcli` is not installed or not authenticated.
- `image_generate` tool — use later to generate storyboard frames after the script/shot list is approved.

## Setup

Install metadata/transcript dependencies if missing:

```bash
python3 -m pip install -U yt-dlp youtube-transcript-api
```

Optional Google Docs backend for delivery:

```bash
brew install openclaw/tap/gogcli
gog --version
```

If Homebrew is unavailable, use the `google-workspace` skill or Docker install path from the `gogcli` skill.

## Workflow

### 1. Confirm scan inputs only if missing

Default values:

```text
channel_shorts_url = https://www.youtube.com/@_The_Clean_Girl/shorts
min_likes = 10000
max_videos = 50
sort = channel/default order unless user says newest/popular
brand_context = optional; if missing, use industry-neutral placeholders
```

Only ask a question if the channel, brand niche, or output target materially changes the work. Otherwise run the default.

### 2. Collect Shorts metadata

Use the helper script in this skill:

```bash
python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/attract-signal/scripts/scan_shorts.py \
  "https://www.youtube.com/@_The_Clean_Girl/shorts" \
  --min-likes 10000 \
  --max-videos 50 \
  --out ~/youtube-shorts-research/clean-girl-shorts.json \
  --markdown ~/youtube-shorts-research/clean-girl-shorts.md
```

If YouTube returns `Sign in to confirm you’re not a bot`, rerun with one of:

```bash
python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/attract-signal/scripts/scan_shorts.py \
  "https://www.youtube.com/@_The_Clean_Girl/shorts" \
  --min-likes 10000 \
  --max-videos 50 \
  --cookies-from-browser chrome \
  --out ~/youtube-shorts-research/clean-girl-shorts.json \
  --markdown ~/youtube-shorts-research/clean-girl-shorts.md

python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/attract-signal/scripts/scan_shorts.py \
  "https://www.youtube.com/@_The_Clean_Girl/shorts" \
  --min-likes 10000 \
  --max-videos 50 \
  --cookies /path/to/youtube-cookies.txt \
  --out ~/youtube-shorts-research/clean-girl-shorts.json \
  --markdown ~/youtube-shorts-research/clean-girl-shorts.md
```

The script uses `yt-dlp` to read channel Shorts and per-video metadata. It also adds channel baseline stats, normalized engagement, relative performance, `signal_score`, and `signal_reason`. YouTube may hide likes or throttle metadata; if `like_count` is missing for many videos, do one of:

1. Retry with fewer videos (`--max-videos 20`).
2. Retry with `--cookies-from-browser chrome` or a Netscape cookie file if YouTube asks for sign-in/bot confirmation.
3. Use YouTube Data API directly if the user has a key/OAuth, but first verify the local CLI surface (`gog schema` / `gog --help`) before assuming a `gog yt` command exists. Note: YouTube Data API gives views/comments; public like counts may be unavailable depending on API behavior/privacy.
4. Fall back to view threshold and mark likes as unavailable.

### 3. Fetch transcripts for shortlisted Shorts

For each source URL selected by the scanner, use this skill's bundled transcript script:

```bash
python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/attract-signal/scripts/fetch_transcript.py "SHORTS_URL" --timestamps
```

If this skill is installed without the bundled script for some reason, use the `youtube-content` skill's transcript script as a fallback.

If transcript is unavailable:

- Try again with no language preference.
- Use title, description, visible captions, and audio/visual observation if the user provides video access.
- Mark `transcript_status: unavailable` instead of inventing words.

### 4. Combine multi-channel signals when needed

If the user gives multiple channels, run one scan per channel, then combine them:

```bash
python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/attract-signal/scripts/analyze_signals.py \
  channel-1.json channel-2.json \
  --out signals.json \
  --top 25
```

The combined output ranks signals across channels with `cross_channel_signal_score` and preserves every `source_url`.

### 5. Generate the strategy report

For generic industry-agnostic strategy:

```bash
python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/attract-signal/scripts/generate_report.py \
  --signals signals.json \
  --transcripts-dir transcripts \
  --out attract-signal-report.md \
  --calendar content-calendar.csv
```

For brand-specific strategy, pass a simple `brand.yaml`:

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

Then run:

```bash
python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/attract-signal/scripts/generate_report.py \
  --signals signals.json \
  --brand brand.yaml \
  --transcripts-dir transcripts \
  --out attract-signal-report.md \
  --calendar content-calendar.csv
```

Transcript files should be named `<video_id>.json` and generated with:

```bash
python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/attract-signal/scripts/fetch_transcript.py "SHORTS_URL" --timestamps > transcripts/VIDEO_ID.json
```

### 6. Analyze each winning Short

For every Short above threshold, produce this breakdown:

```markdown
## Source: <title>
- Source link: <URL>
- Channel: <channel>
- Published: <date if available>
- Views: <view_count or unknown>
- Likes: <like_count or unknown>
- Comments: <comment_count or unknown>
- Engagement notes: <likes/views ratio if both known; otherwise what is known>

### Transcript / Spoken Structure
- 0-2s: <opening line or caption>
- 2-5s: <setup/escalation>
- 5-12s: <payoff/demo/proof>
- CTA/end: <ending line or loop>

### Trend Type
Choose one or more:
- transformation / before-after
- satisfying process / cleaning reset
- problem-solution
- product demo / tool reveal
- routine / ritual
- aesthetic aspiration
- myth-busting / mistake correction
- listicle / quick tips
- storytime / confession
- challenge / comparison
- social proof / results
- other: <name it>

### Hook
- Verbal hook: <first sentence/caption/promise>
- Curiosity gap: <what question it creates>
- Emotional trigger: <relief, disgust, aspiration, surprise, urgency, etc.>
- Specificity: <numbers, time, room/product/problem named>

### Visual Hooks
- First frame: <what viewer sees immediately>
- Motion: <scrub, pour, wipe, reveal, hand entering frame, jump cut, etc.>
- Contrast: <dirty/clean, clutter/empty, dull/shiny, chaos/order>
- Text overlay: <exact or summarized overlay>
- Pattern interrupt: <unexpected object, speed ramp, close-up, sound sync>

### Signal Pattern
- Core mechanic: <repeatable content formula>
- Why it likely worked: <viewer psychology>
- Original-brand angle: <how to adapt without copying>
- Avoid copying: <what not to reuse verbatim>
```

### 7. Synthesize channel-level trends

After individual analyses, make a channel/trend brief:

```markdown
# YouTube Shorts Trend Brief: <channel>

## Top Winners
| Rank | Source | Views | Likes | Trend type | Hook type | Strategy angle |
|---|---:|---:|---|---|---|---|

## Repeating Patterns
- Hook formulas:
- Visual formulas:
- Editing rhythm:
- Common props/products/settings:
- Common emotions:
- Common CTAs/loop endings:

## Content Opportunities for <user brand>
1. <original concept inspired by pattern> — cite source(s)
2. ...

## Script Drafts
For each concept:
- Title / working caption
- 0-2s hook
- Beat-by-beat script with timestamps
- On-screen text
- Voiceover/dialogue
- CTA
- Source inspiration links

## Shot Lists
For each concept:
| Shot | Duration | Framing | Action | Props | Overlay | Notes |

## Storyboard Prompts
For each key frame:
- Frame prompt for image generation
- Camera/framing
- Lighting/style
- Brand notes
- Source reference link(s)
```

### 8. Default delivery: write to Google Docs

For now, the expected final deliverable is a **Google Doc** containing the trend brief, citations, scripts, shot lists, and storyboard prompts. Draft locally first as Markdown, then publish the Markdown to Google Docs with `gogcli` after Google auth is working and the user has approved the write.

Preferred `gogcli` flow for the current `gog` CLI:

```bash
gog docs create "YouTube Shorts Trend Brief - <Channel>" --file brief.md --json
# parse the returned doc ID, then verify the created file:
gog drive get <docId> --json --select id,name,mimeType,webViewLink,owners
```

If a blank Doc already exists and the agent needs to append a local Markdown draft:

```bash
gog docs write <docId> --append --file brief.md --json
# verify the created file:
gog drive get <docId> --json --select id,name,mimeType,webViewLink,owners
```

If `gog` is unavailable, use `google-workspace`'s `GAPI docs create` / `GAPI docs append` flow. Never create, edit, or share Google Docs without user approval. If Google auth is not set up, stop after the local Markdown artifact and tell the user exactly what OAuth/install step is missing.

## Ethical / Brand Safety Rules

- Extract patterns; do not copy exact scripts, claims, edit sequences, or distinctive creative expressions.
- Keep citations beside every source-inspired idea.
- Rewrite into the user's brand voice, products, audience, and proof points.
- If a source makes a claim, do not repeat it as factual for the user's brand unless the user can substantiate it.
- Do not download or reuse creator footage/assets unless the user has rights.

## Common Pitfalls

1. **Likes are hidden or missing.** Mark them unknown and filter by available metrics instead of fabricating likes.
2. **Shorts tab pagination can be flaky.** Retry with lower `--max-videos`, update `yt-dlp`, or use browser/manual sampling for the first page.
3. **Metadata-only extraction can hit format errors.** The scanner uses `--ignore-no-formats-error` for per-video JSON so unavailable video formats do not block metadata collection.
4. **Transcripts often fail for Shorts.** Use available captions only; otherwise describe visual/audio structure from metadata or browser observation and label transcript as unavailable.
5. **Confusing inspiration with copying.** Always translate source patterns into new concepts and cite references.
6. **Creating Google Docs too early.** Draft locally first; ask for approval before using `gog docs create/write` or `google-workspace` writes.

## Verification Checklist

- [ ] Channel Shorts URL and threshold recorded.
- [ ] Every analyzed Short includes a source link citation.
- [ ] Likes/views/comments are either real metadata or explicitly marked unknown.
- [ ] Baselines, normalized engagement, signal score, and signal reason are present when metadata allows.
- [ ] Transcript status is recorded for every video.
- [ ] Individual breakdowns include trend type, hook, visual hooks, and signal pattern.
- [ ] Channel-level synthesis produces original brand angles, not copied scripts.
- [ ] Reports stay industry-agnostic unless the user supplies brand context.
- [ ] 30-day calendar rows include source links.
- [ ] Any Google Doc write was approved and the returned Doc URL/ID was verified.
