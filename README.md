# Attract Signal Skill

A shareable Hermes/Codex skill for industry-agnostic short-form content signal intelligence: high-performing YouTube Shorts, repeatable hooks, proof/meat types, CTA paths, visual mechanics, source citations, and 14-day content test sprints.

Default example channel:

```text
https://www.youtube.com/@_The_Clean_Girl/shorts
```

## What It Does

- Scans one or more YouTube channel Shorts tabs with `yt-dlp`.
- Imports TikTok, Instagram Reels, X video, or other short-form exports from CSV/JSON.
- Filters winners by likes, defaulting to `10,000+`.
- Collects views, likes, comments, source URLs, thumbnails, baselines, normalized engagement, relative performance, and signal scores.
- Compares signal strength across platforms when normalized exports are provided.
- Supports `--cookies-from-browser` / `--cookies` for YouTube sign-in or bot checks.
- Produces JSON, local Markdown, Google Doc, and CSV strategy artifacts.
- Normalizes every report into Avatar, Promise, Proof, and Path, even when `brand.yaml` is missing.
- Makes the hook library the center of the report with raw hooks, reusable templates, ready-to-read hook lines, pattern tags, and winner-adjacent variations.
- Guides the agent to fetch transcripts, analyze hooks and visual hooks, and turn content signals into original brand-safe strategy tests for any industry.
- Generates thumbnail concepts, storyboard prompts, image-generation direction, and source-cited script/shot-list templates.
- Generates a 14-day sprint matrix using a 70/20/10 mix of proven hooks, winner-adjacent hooks, and new experiments, with compact style/CTA IDs.
- Maintains an optional local signal library for reusable pattern memory.
- Creates a Google Docs copy by default through `gogcli` after the local Markdown report is written.
- Supports optional Google Sheets calendar export through `gogcli`.

## Requirements

```bash
python3 -m pip install -U yt-dlp youtube-transcript-api
```

Default Google Docs publishing:

```bash
brew install openclaw/tap/gogcli
gog auth status
```

If `gog` is not installed or authenticated, report generation still writes the local Markdown/CSV files and prints the Google publishing error. Use `--require-google-doc` when you want that publishing step to fail the run.

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

## Import TikTok, Instagram, Or X Exports

Direct platform scraping is intentionally not bundled yet. For TikTok, Instagram Reels, and X video, export metrics to CSV/JSON and normalize them:

```bash
python3 skills/media/attract-signal/scripts/import_platform.py \
  --platform mixed \
  --input examples/platform-export.example.csv \
  --source-name "Example multi-platform export" \
  --out ./platform-normalized.json
```

Then include the normalized JSON with YouTube scans:

```bash
python3 skills/media/attract-signal/scripts/analyze_signals.py \
  ./youtube-channel.json ./platform-normalized.json \
  --out ./signals.json
```

## Generate A Strategy Report

Generic, industry-agnostic report:

```bash
python3 skills/media/attract-signal/scripts/generate_report.py \
  --signals ./signals.json \
  --transcripts-dir ./transcripts \
  --out ./attract-signal-report.md \
  --calendar ./content-sprint.csv
```

This writes `./attract-signal-report.md`, creates a Google Doc copy by default, and writes Google Doc metadata beside the report as `./attract-signal-report.google-doc.json`, and exports a 14-day sprint matrix CSV.

Brand-specific report:

```bash
python3 skills/media/attract-signal/scripts/generate_report.py \
  --signals ./signals.json \
  --brand examples/brand.example.yaml \
  --transcripts-dir ./transcripts \
  --out ./attract-signal-report.md \
  --calendar ./content-sprint.csv \
  --doc-title "Attract Signal Brief - Example Brand"
```

For a local-only run:

```bash
python3 skills/media/attract-signal/scripts/generate_report.py \
  --signals ./signals.json \
  --brand examples/brand.example.yaml \
  --transcripts-dir ./transcripts \
  --out ./attract-signal-report.md \
  --calendar ./content-sprint.csv \
  --no-google-doc
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
primary_path: sub
channel_style: face_led
product_mode: false
product_name: ""
product_url: ""
discount_code: ""
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
Use attract-signal. Source inspiration: https://www.youtube.com/@_The_Clean_Girl/shorts. Target brand: https://kobeesco.com/. Build a 14-day product-led sprint with source citations.
```

```text
Use attract-signal to scan this channel's Shorts, find videos over 10,000 likes, analyze the trend type, hook, visual hooks, transcript structure, and turn the strongest content signals into an original strategy, scripts, and shot list for my brand with source citations.
```

```text
Analyze these 5 channels for content signals and make me a 14-day test sprint for my brand.
```

```text
Use attract-signal for a skincare brand, a restaurant, or a SaaS founder. Keep the strategy industry-specific only after I provide brand context.
```

The skill intentionally tells the agent to cite every source Short and to avoid copying exact scripts, premises, edits, or creator footage.

Input contract:

- Source inspiration can be a YouTube Shorts channel, Instagram/Reels profile, TikTok profile, X video profile, or exported platform CSV/JSON.
- Target brand context can be a website URL, product page URL, or `brand.yaml`.
- If the target is a Shopify/product brand, verify the product page before naming the product, using claims, or writing CTAs.
- If no target brand URL/config is provided, keep the report creator-style and generic rather than inventing a product.

## Google Docs Output

Report generation now creates both outputs by default:

1. Local Markdown report at the `--out` path.
2. Native Google Doc copy through `gog docs create --file`.

Control the Google Doc from `generate_report.py`:

```bash
python3 skills/media/attract-signal/scripts/generate_report.py \
  --signals ./signals.json \
  --brand examples/brand.example.yaml \
  --out ./attract-signal-report.md \
  --calendar ./content-sprint.csv \
  --doc-title "Attract Signal Brief - Brand Name" \
  --open-doc
```

The standalone publisher remains available when you already have a Markdown file:

```bash
python3 skills/media/attract-signal/scripts/publish_doc.py \
  --file ./attract-signal-report.md \
  --title "Attract Signal Brief - Brand Name"
```

Export a generated 14-day sprint matrix to Google Sheets after approval:

```bash
python3 skills/media/attract-signal/scripts/export_calendar_sheets.py \
  --calendar ./content-sprint.csv \
  --title "Attract Signal Sprint - Brand Name"
```

Build a reusable local signal library:

```bash
python3 skills/media/attract-signal/scripts/signal_library.py add --signals ./signals.json --top-only
python3 skills/media/attract-signal/scripts/signal_library.py search "challenge"
```


Sprint CSV columns include:

```text
day, test_type, hook_template, script_line_0_2, pattern_tag, meat_type, product_step, style_id, primary_path, cta_variant_id, source_url
```

For a Shopify or DTC product brand, set:

```yaml
offer: drain cleaner bundle
product_name: Magic Foam
product_url: https://gocleangirl.com/products/magic-foam
primary_path: click
channel_style: product_led
product_mode: true
```

That makes the report use product-led proof, short click/buy CTAs, product/faceless style options, and a sprint row that forces the meat to show product, application, and result. Product names, offer claims, URLs, and discount codes should come from `brand.yaml` or a verified product page, not from invented placeholders.

Creating the default Doc is part of the report workflow. Any sharing, permission changes, or edits to existing Docs should still be approved by the user first.

## Sample Report Sections

Generated reports include:

- Executive Summary
- Strategy Spine
- Hook Library
- Meats, Style, And CTA System
- Top Signals
- Source Evidence
- Hook Taxonomy
- Visual Pattern Taxonomy
- Platform Comparison
- Transcript Insights
- Brand Strategy Opportunities
- Script Drafts
- Shot Lists
- Thumbnail Concepts
- Storyboard Prompts
- Optional Image Generation Workflow
- Signal Library Next Step
- 14-Day Sprint Matrix
