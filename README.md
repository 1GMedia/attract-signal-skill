# Attract Signal Skill

A shareable Hermes, Codex, and Claude skill for industry-agnostic content signal intelligence: high-performing short-form content plus current Reddit audience conversations; repeatable hooks, proof/meat types, CTA paths, visual mechanics, voice-of-customer language, source citations, and 14-day content test sprints.

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
- Makes the hook library the center of the report with raw hooks, reusable templates, ready-to-read hook lines, pattern tags, winner-adjacent variations, and sub-template branching when one pattern dominates.
- Guides the agent to fetch transcripts, analyze hooks and visual hooks, and turn content signals into original brand-safe strategy tests for any industry.
- Generates thumbnail concepts, storyboard prompts, image-generation direction, and source-cited script/shot-list templates.
- Generates a 14-day sprint matrix using a 70/20/10 mix of proven hooks, winner-adjacent hooks, and new experiments, with compact style/CTA IDs and rotated sub-templates.
- Maintains an optional local signal library for reusable pattern memory.
- Creates a Google Docs copy by default through `gogcli` after the local Markdown report is written.
- Supports optional Google Sheets calendar export through `gogcli`.
- Consumes Last30Days Reddit Markdown or normalized JSON without copying its independently updateable research engine.
- Surfaces Pain Points, Solution Requests, Money Talk, Hot Discussions, and Seeking Alternatives.
- Ranks Reddit threads by relevance, recency, engagement, urgency, and commercial intent while preserving exact language and URLs.
- Converts cited Reddit findings into content gaps, hooks, scripts, shot lists, and sprint inputs through a reusable deep-research prompt.

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

Recommended, using the open agent skills CLI from Vercel Labs. This is the clean publishing path: `npx` runs the installer CLI, while this GitHub repo stays the source of truth for the skill.

```bash
npx skills add 1GMedia/attract-signal-skill --skill attract-signal -g -a codex -a claude-code -a hermes-agent
```

Install to every supported agent detected by the CLI:

```bash
npx skills add 1GMedia/attract-signal-skill --all
```

List the skill before installing:

```bash
npx skills add 1GMedia/attract-signal-skill --list
```

Manual fallback from this repository, useful when `npx` is unavailable or you want to copy the skill from a local checkout:

```bash
./install.sh hermes
./install.sh codex
./install.sh claude
./install.sh all
```

Install targets:

| target | install path |
| --- | --- |
| `hermes` / `hermes-agent` | `~/.hermes/skills/attract-signal` |
| `codex` | `~/.codex/skills/attract-signal` |
| `claude` / `claude-code` | `~/.claude/skills/attract-signal` |
| `all` | installs the same skill folder to all three paths |

The same `SKILL.md` and scripts are used everywhere. Local Markdown/CSV files are the universal outputs; Google Docs and Google Sheets publishing are optional `gogcli` enhancements.

## Publishing Model

`attract-signal` is intentionally packaged as a single-skill GitHub repo. Do not publish a separate npm package for the skill itself unless a custom installer is needed later. The public install surface should stay:

```bash
npx skills add 1GMedia/attract-signal-skill --skill attract-signal -g -a codex -a claude-code -a hermes-agent
```

Future Attract skills can live in their own standalone repos first, then be mirrored into a catalog repo such as `1GMedia/attract-skills`:

```text
skills/
  content/attract-signal/SKILL.md
  web/attract-mirror/SKILL.md
  automation/attract-atomize/SKILL.md
```

That future catalog would let people browse and install multiple Attract skills from one place:

```bash
npx skills add 1GMedia/attract-skills --list
npx skills add 1GMedia/attract-skills --skill attract-signal -g -a codex
```

Recommended rule: individual repos remain the source of truth; the catalog repo vendors or syncs released copies for discovery.

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

## Analyze Reddit Conversations With Last30Days

Keep `last30days` installed as its own skill so it can continue tracking the upstream project. Run it for the research topic, then pass the raw Markdown artifact from its footer into Reddit Intelligence v2:

```bash
python3 skills/media/attract-signal/scripts/reddit_signal.py research \
  --topic "<topic>" \
  --input ~/Documents/Last30Days/<topic>-raw.md \
  --quality balanced \
  --out-dir ./reddit-intelligence
```

Repeat `--input` to merge scout/deep passes or public/ScrapeCreators artifacts. The v2 output includes:

- a hard relevance gate that runs before engagement or conversation lenses
- corpus sufficiency status (`ready`, `limited`, or `insufficient`)
- five GummySearch-style conversation lenses plus purchase intent and jobs-to-be-done
- recurring semantic themes with independent-thread support
- exact audience language and immutable Reddit citations
- SQLite history, saved audiences, local alerts, and run-over-run snapshots
- a self-contained searchable HTML dashboard
- Markdown, JSON, conversation CSV, opportunity CSV, query-plan JSON, and 14-day sprint CSV artifacts

Without `OPENAI_API_KEY`, v2 uses precision-first deterministic mode. With a real API key and the optional `openai` package, it discovers available models through `/v1/models` and uses strict-schema Responses API calls. It never assumes a GPT-5.6 Sol model ID and never uses ChatGPT/Codex authentication as an API credential.

```bash
python3 -m pip install -r requirements-reddit-ai.txt
```

Save and monitor an audience locally:

```bash
python3 skills/media/attract-signal/scripts/reddit_signal.py audience save \
  --id tattoo-booking \
  --topic "tattoo studio booking software" \
  --input "~/Documents/Last30Days/tattoo-studio-booking*-raw.md" \
  --cadence-hours 168

python3 skills/media/attract-signal/scripts/reddit_signal.py watch run --due
python3 skills/media/attract-signal/scripts/reddit_signal.py dashboard open --audience-id tattoo-booking
```

Run the machine-readable acceptance harness against a manually labeled JSONL corpus:

```bash
python3 skills/media/attract-signal/scripts/evaluate_reddit_intelligence.py \
  path/to/reddit-eval-gold.jsonl \
  --out ./reddit-eval-report.json
```

The harness fails until the corpus contains at least 300 examples and the documented precision, recall, lens, purchase-intent, and high-engagement-negative gates pass. Do not claim GummySearch replacement quality from smoke fixtures alone.

The v1 analyzer remains available for one major release:

```bash
python3 skills/media/attract-signal/scripts/analyze_reddit_conversations.py \
  ~/Documents/Last30Days/<topic>-raw.md \
  --topic "<topic>" \
  --out ./reddit-conversation-signals.json \
  --markdown ./reddit-conversation-signals.md
```

Add `--engine v2` to delegate the old command shape to v2, or `--legacy` to force the historical report. Both analyzers accept normalized Reddit JSON, including Last30Days `items_by_source.reddit` payloads.

The legacy analyzer produces:

- an audience and subreddit map
- ranked conversations
- five evidence lenses: Pain Points, Solution Requests, Money Talk, Hot Discussions, and Seeking Alternatives
- exact audience language with source URLs
- buying and switching signals
- a content opportunity matrix

For semantic synthesis and the content handoff, use:

```text
skills/media/attract-signal/references/reddit-deep-research-prompt.md
```

This boundary is intentional: Last30Days owns current evidence collection; Attract Signal owns audience interpretation and content creation. Updating either skill does not overwrite the other.

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
business_type: service
brand_url: https://example.com
industry: local service business
audience: busy homeowners who want trustworthy help
offer: a clear, reliable service package
tone: helpful, direct, practical, and warm
proof_points:
  - before-and-after results
primary_path: ""
channel_style: ""
product_mode: ""
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

After installation, ask your agent:

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

Minimal intake:

1. Main website/store URL, optional but recommended.
2. Business type: `creator`, `product_brand`, `service`, `b2b_saas`, `education`, or `other`.
3. One-sentence viewer goal or offer.
4. Avatar label, such as consumers, founders, developers, creators, or local buyers.
5. Preferred channel style only when it cannot be inferred: `face_led`, `product_led`, or `faceless`.

Business type presets set defaults only when the field is blank:

| business_type | default path | default proof/meats | default style |
| --- | --- | --- | --- |
| `creator` | `sub` | Story + Demonstration | `face_led` |
| `product_brand` | `click` | Demonstration + Testimonial | `product_led` |
| `service` | `book_call` | Demonstration + Testimonial | `face_led` |
| `b2b_saas` | `book_call` | Demonstration + Education | `face_led` |
| `education` | `opt_in` | Education + Story | `face_led` |

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
business_type: product_brand
offer: Magic Foam cleaning foam
product_name: Magic Foam
product_url: https://gocleangirl.com/products/magic-foam
```

That makes the report default to product-led proof, short click/buy CTAs, product/faceless style options, and a sprint row that forces the meat to show product, application, and result. Product names, offer claims, URLs, and discount codes should come from `brand.yaml` or a verified product page, not from invented placeholders.

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
