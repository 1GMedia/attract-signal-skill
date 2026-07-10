---
name: attract-signal
description: "Use when scanning short-form channels or current Reddit conversations for content signals: high-performing videos, audience pain points, solution requests, money talk, hot discussions, seeking alternatives, exact customer language, citations, hooks, repeatable formats, and brand-specific content strategy briefs, scripts, shot lists, storyboards, or Google Docs."
license: MIT
metadata:
  version: 2.0.0
  author: 1GMedia
  platforms: [linux, macos, windows]
  required_commands: [yt-dlp]
  portable_skill: true
  install_targets:
    hermes: ~/.hermes/skills/attract-signal
    codex: ~/.codex/skills/attract-signal
    claude: ~/.claude/skills/attract-signal
  hermes:
    tags: [youtube, shorts, reddit, audience-research, trend-analysis, content-strategy, scriptwriting, citations]
    related_skills: [last30days, youtube-content, gogcli, google-workspace]
---

# Attract Signal

## Overview

This skill turns short-form content sources into reusable content-intelligence briefs. It supports YouTube Shorts, TikTok, Instagram Reels, X video, and other short-form exports. It is designed for competitive/trend research where the user wants to find high-performing short-form content, understand why it worked, and translate the underlying signal into original brand strategy without copying the original. It is industry-agnostic by default: do not assume tattoo, beauty, SaaS, local services, restaurants, ecommerce, coaching, fitness, or any other niche unless the user provides that context.

This is a portable skill for Hermes, Codex, and Claude. Keep the workflow agent-neutral: local Markdown and CSV outputs are universal; Google Docs/Sheets publishing is an optional enhancement when `gogcli` is installed and authenticated.

Default example channel for testing:

```text
https://www.youtube.com/@_The_Clean_Girl/shorts
```

The standard threshold is **10,000+ likes**, but the user can change it. Always cite source Shorts links in the output.

## When to Use

Use this skill when the user asks to:

- Scan one or more short-form sources for winners, including YouTube Shorts channels and normalized TikTok, Instagram Reels, X video, or platform exports.
- Filter Shorts by likes/views/engagement.
- Analyze hooks, visual hooks, formats, content trends, and transcript patterns.
- Create a signal and trend breakdown that can become original scripts, shot lists, Google Docs, or storyboards.
- Build a source-cited content signal library.
- Create an industry-agnostic or brand-specific 14-day content testing sprint.

Don't use this for long-form YouTube summaries only; use `youtube-content` directly for single-video transcript transforms.

## Related Skills / Tools

- Bundled `scripts/fetch_transcript.py` — fetches transcripts from individual Shorts or videos.
- `youtube-content` — optional fallback transcript skill if already installed.
- `gogcli` — preferred Google CLI for writing the default Google Docs copy (`brew install openclaw/tap/gogcli`).
- `google-workspace` — optional Google Workspace fallback if `gog`/`gogcli` is not installed or not authenticated and the host agent provides that skill/tool.
- `image_generate` tool — use later to generate storyboard frames after the script/shot list is approved.
- `last30days` — preferred independent evidence collector for current Reddit threads and comments. Keep it separately installed and updateable; Attract Signal consumes its output instead of vendoring its engine.

## Deep Reddit Research Mode

Use this mode when the user wants Reddit audience research, voice-of-customer language, content gaps, or current conversations translated into content strategy.

Before starting a saved-audience run, call `reddit_signal.py alerts list --pending` and summarize any unacknowledged local alerts in chat. Do not acknowledge them automatically.

1. Run the independently installed `last30days` skill for the topic and include Reddit. Follow its own setup, source-health, research, and citation contract exactly. Use a scout pass to resolve terminology, dedicated subreddits, category peers, and competitors; use the saved `query-plan.json` for a deeper follow-up pass when the first corpus is limited.
2. Locate the raw Markdown artifact from the Last30Days footer, or use normalized Reddit JSON containing titles, bodies, communities, dates, engagement, comments, and URLs.
3. Run Reddit Intelligence v2. Repeat `--input` to merge scout/deep artifacts or public/ScrapeCreators lanes:

```bash
python3 $SKILL_DIR/scripts/reddit_signal.py research \
  --topic "<topic>" \
  --input ~/Documents/Last30Days/<topic>-raw.md \
  --quality balanced \
  --out-dir ~/Documents/AttractSignal/reports/<topic>
```

The command writes structured JSON, reviewable Markdown, a self-contained HTML dashboard, conversation and opportunity CSVs, a query plan, and a 14-day sprint CSV. The sprint stays empty when the corpus is insufficient.

4. Use the five conversation lenses only after the relevance gate. A popular post cannot become `Hot Discussions` unless it is first relevant to the requested topic.
5. Read `references/reddit-deep-research-prompt.md` completely before additional agent synthesis. Keep every evidence URL beside the resulting angle.

The old analyzer remains available for compatibility:

```bash
python3 $SKILL_DIR/scripts/analyze_reddit_conversations.py \
  ~/Documents/Last30Days/<topic>-raw.md \
  --topic "<topic>" \
  --out reddit-conversation-signals.json \
  --markdown reddit-conversation-signals.md
```

Add `--engine v2` to delegate that compatibility command to Reddit Intelligence v2. Use `--legacy` to force the v1 output during the transition.

The five conversation lenses are multi-label:

- Pain Points
- Solution Requests
- Money Talk
- Hot Discussions
- Seeking Alternatives

Keep the integration one-way and update-safe: Last30Days owns discovery/freshness; Attract Signal owns conversation analysis and content transformation. Do not copy the Last30Days engine into this repository.

### Saved audiences, monitoring, and dashboard

```bash
python3 $SKILL_DIR/scripts/reddit_signal.py audience save \
  --id <audience-id> \
  --topic "<topic>" \
  --input "~/Documents/Last30Days/<topic>*-raw.md" \
  --cadence-hours 168

python3 $SKILL_DIR/scripts/reddit_signal.py watch run --due
python3 $SKILL_DIR/scripts/reddit_signal.py alerts list --pending
python3 $SKILL_DIR/scripts/reddit_signal.py dashboard open --audience-id <audience-id>
python3 $SKILL_DIR/scripts/reddit_signal.py doctor
```

On macOS, `watch install --interval-hours 24` creates an opt-in `launchd` job. Never install a schedule unless the user explicitly asks. On Linux or Windows, schedule `watch run --due` with cron or Task Scheduler.

### Optional OpenAI semantic routing

The v2 pipeline is safe and useful without an API key. With `OPENAI_API_KEY`, it uses the official Responses API and strict JSON Schemas for uncertain relevance and conversation intelligence. It queries `/v1/models` before selecting models. Do not assume a GPT-5.6 Sol API ID and never use ChatGPT/Codex authentication as an API credential.

Install the optional SDK when semantic routing is wanted:

```bash
python3 -m pip install 'openai>=2,<3'
```

Optional model aliases:

```text
ATTRACT_SIGNAL_MODEL_FILTER
ATTRACT_SIGNAL_MODEL_ANALYSIS
ATTRACT_SIGNAL_MODEL_SOL
ATTRACT_SIGNAL_MODEL_SYNTHESIS
ATTRACT_SIGNAL_EMBEDDING_MODEL
ATTRACT_SIGNAL_MAX_MODEL_CALLS
```

When a configured Sol model is unavailable, v2 records and uses a verified high-reasoning fallback. Deep mode uses background Responses for theme synthesis; balanced mode reserves high-reasoning calls for ambiguous evidence.

## Setup

Install metadata/transcript dependencies if missing:

```bash
python3 -m pip install -U yt-dlp youtube-transcript-api
```

Default Google Docs backend for delivery:

```bash
brew install openclaw/tap/gogcli
gog --version
```

If Homebrew is unavailable, use a host-agent Google Workspace tool or Docker install path from the `gogcli` skill when available.

The default report workflow writes a local Markdown file first, then creates a Google Doc copy with `gog docs create --file`. Reports should normalize every channel into Avatar, Promise, Proof, and Path, then build Hooks -> Meats -> CTAs -> 14-day tests. If `gog` is missing or unauthenticated, keep the local Markdown and tell the user exactly what failed. Use `--no-google-doc` only for local-only tests or CI.

For shell examples, resolve the installed skill path once:

```bash
# Hermes
export SKILL_DIR="${HERMES_HOME:-$HOME/.hermes}/skills/attract-signal"

# Codex
export SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/attract-signal"

# Claude Code
export SKILL_DIR="$HOME/.claude/skills/attract-signal"
```

## Workflow

### 1. Confirm source and target inputs

Ask for these inputs when they are missing:

```text
Source inspiration links:
- YouTube Shorts channel URL
- Instagram/Reels profile URL
- TikTok profile URL
- X/video profile URL

Target brand links:
- brand website URL
- product page URL
- Instagram/TikTok/YouTube accounts if available
```

Then ask only the minimum strategy intake needed to set defaults:

```text
What is your main website or store URL? Optional, but if you skip this I will use more generic language.
Which best describes you: creator, product_brand, service, b2b_saas, education, or other?
In one sentence, what are you trying to get viewers to do or get?
Who is this channel mainly for?
If I cannot infer it: do you prefer face_led, product_led, or faceless videos?
```

Map `business_type` to internal defaults when the user does not provide explicit overrides:

| business_type | default path | default proof/meats | default style |
| --- | --- | --- | --- |
| `creator` | `sub` | Story + Demonstration | `face_led` |
| `product_brand` | `click` | Demonstration + Testimonial | `product_led` |
| `service` | `book_call` | Demonstration + Testimonial | `face_led` |
| `b2b_saas` | `book_call` | Demonstration + Education | `face_led` |
| `education` | `opt_in` | Education + Story | `face_led` |

The shortest acceptable prompt is:

```text
Share a source YouTube/Instagram/TikTok/X channel to analyze, plus your brand website or product URL if you want a strategy for your own brand.
```

Default scan values:

```text
channel_shorts_url = https://www.youtube.com/@_The_Clean_Girl/shorts
min_likes = 10000
max_videos = 50
sort = channel/default order unless user says newest/popular
target_brand_url = optional, but required for product-mode claims unless brand.yaml supplies verified product details
```

If the user provides only a source channel, generate a generic/creator-style signal report. If the user provides a brand website or product page, open/research it first, then populate `brand.yaml` fields from verified page text. Never infer product names, offers, discount codes, ingredients, safety claims, or prices without a provided/verified source URL.

### 2. Collect Shorts metadata

Use the helper script in this skill:

```bash
python3 $SKILL_DIR/scripts/scan_shorts.py \
  "https://www.youtube.com/@_The_Clean_Girl/shorts" \
  --min-likes 10000 \
  --max-videos 50 \
  --out ~/youtube-shorts-research/clean-girl-shorts.json \
  --markdown ~/youtube-shorts-research/clean-girl-shorts.md
```

If YouTube returns `Sign in to confirm you’re not a bot`, rerun with one of:

```bash
python3 $SKILL_DIR/scripts/scan_shorts.py \
  "https://www.youtube.com/@_The_Clean_Girl/shorts" \
  --min-likes 10000 \
  --max-videos 50 \
  --cookies-from-browser chrome \
  --out ~/youtube-shorts-research/clean-girl-shorts.json \
  --markdown ~/youtube-shorts-research/clean-girl-shorts.md

python3 $SKILL_DIR/scripts/scan_shorts.py \
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
python3 $SKILL_DIR/scripts/fetch_transcript.py "SHORTS_URL" --timestamps
```

If this skill is installed without the bundled script for some reason, use the host agent's YouTube transcript skill/tool as a fallback when available.

If transcript is unavailable:

- Try again with no language preference.
- Use title, description, visible captions, and audio/visual observation if the user provides video access.
- Mark `transcript_status: unavailable` instead of inventing words.

### 4. Combine multi-channel signals when needed

If the user gives multiple channels, run one scan per channel, then combine them:

```bash
python3 $SKILL_DIR/scripts/analyze_signals.py \
  channel-1.json channel-2.json \
  --out signals.json \
  --top 25
```

The combined output ranks signals across channels with `cross_channel_signal_score` and preserves every `source_url`.

### 4b. Import non-YouTube platforms from exports

YouTube Shorts is the only built-in live scraper. For TikTok, Instagram Reels, X video, or other platforms, normalize user-provided CSV/JSON exports:

```bash
python3 $SKILL_DIR/scripts/import_platform.py \
  --platform mixed \
  --input platform-export.csv \
  --source-name "Competitor multi-platform export" \
  --out platform-normalized.json
```

Then include `platform-normalized.json` in `analyze_signals.py` alongside YouTube scans. This gives cross-platform normalization and platform-specific strategy recommendations without pretending to scrape restricted platforms.

### 5. Generate the strategy report

For generic industry-agnostic strategy:

```bash
python3 $SKILL_DIR/scripts/generate_report.py \
  --signals signals.json \
  --transcripts-dir transcripts \
  --out attract-signal-report.md \
  --calendar content-sprint.csv
```

This creates both:

- `attract-signal-report.md` locally
- a native Google Doc copy, with metadata saved as `attract-signal-report.google-doc.json`
- `content-sprint.csv`, a 14-day test sprint matrix

For brand-specific strategy, pass a simple `brand.yaml`:

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

Then run:

```bash
python3 $SKILL_DIR/scripts/generate_report.py \
  --signals signals.json \
  --brand brand.yaml \
  --transcripts-dir transcripts \
  --out attract-signal-report.md \
  --calendar content-sprint.csv \
  --doc-title "Attract Signal Brief - <Brand>"
```

For local-only testing, add:

```bash
--no-google-doc
```

Transcript files should be named `<video_id>.json` and generated with:

```bash
python3 $SKILL_DIR/scripts/fetch_transcript.py "SHORTS_URL" --timestamps > transcripts/VIDEO_ID.json
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
# Short-Form Content Signal Brief: <source/channel>

## Strategy Spine
- Avatar: <primary viewer and optional secondary viewer>
- Promise: <why the channel exists in one sentence>
- Proof: <two dominant meats: Demonstration, Testimonial, Education, Story>
- Path: <sub, click, opt_in, buy, apply>
- Channel style: <face_led, product_led, faceless>

## Top Winners
| Rank | Source | Views | Likes | Trend type | Hook type | Strategy angle |
|---|---:|---:|---|---|---|---|

## Hook Library
- Top 5 raw hooks:
- Generalized hook templates:
- 2 ready-to-read hook lines for each top template:
- Winner-adjacent variations:
- Pattern tags: Curiosity, Challenge, Spectacle, Transformation, Social Proof, Narrative
- If the top 5 collapse into the same pattern/template, branch the dominant pattern into 3-5 sub-templates using title/transcript cues, then rotate those sub-templates through the 14-day sprint.
- For comedy/open-mic reports, turn Narrative collapse into joke sub-templates such as Shock Answer, Roast Escalation, Underdog Reversal, Instant Character, Backfire Bit, Crowd-Work Premise, and Tag Ladder.

## Repeating Visual Patterns
- Visual formulas:
- Editing rhythm:
- Common props/products/settings:
- Common emotions:
- Common CTAs/loop endings:

## Meats, Style, And CTA System
- Primary meats:
- Channel style adjustment:
- Product mode, when click/buy or product-led:
  - show product
  - show application/use
  - show result
- Product names, offer claims, URLs, and discount codes must come from `brand.yaml` or a verified product page. Do not invent product names, fake brands, fake coupon codes, or unsupported claims.
- For comedy/open-mic reports, convert `Story` meat into a bit skeleton: setup, assumption, turn, tag.
- Short CTA variants by path, with IDs like `cta_sub_1` or `cta_apply_1`:

## Script Drafts
For each concept:
- Title / working caption
- Hook from library
- Meat
- Payoff
- CTA
- On-screen text
- Voiceover/dialogue
- Source inspiration links

## 14-Day Sprint Matrix
| Day | Test mix | Hook template | Script line 0-2s | Pattern tag | Meat | Product step | Style ID | CTA variant ID | Source |
|---:|---|---|---|---|---|---|---|---|---|

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

### 8. Default delivery: local Markdown plus Google Doc

The expected final deliverable is both a **local Markdown file** and a **Google Doc copy** containing the trend brief, citations, scripts, shot lists, and storyboard prompts. Draft locally first as Markdown; the report generator now publishes that Markdown to Google Docs by default when `gogcli` is installed and authenticated.

Preferred report-and-publish helper:

```bash
python3 $SKILL_DIR/scripts/generate_report.py \
  --signals signals.json \
  --brand brand.yaml \
  --transcripts-dir transcripts \
  --out attract-signal-report.md \
  --calendar content-sprint.csv \
  --doc-title "Attract Signal Brief - <Brand or Channel>"
```

Use `--open-doc` when the user explicitly wants the generated Doc opened in the browser. The standalone publisher remains available for already-generated Markdown:

```bash
python3 $SKILL_DIR/scripts/publish_doc.py \
  --file attract-signal-report.md \
  --title "Attract Signal Brief - <Brand>"
```

Direct `gogcli` flow for the current `gog` CLI:

```bash
gog docs create "Short-Form Signal Brief - <Channel>" --file brief.md --json
# parse the returned doc ID, then verify the created file:
gog drive get <docId> --json --select id,name,mimeType,webViewLink,owners
```

If a blank Doc already exists and the agent needs to append a local Markdown draft:

```bash
gog docs write <docId> --append --file brief.md --json
# verify the created file:
gog drive get <docId> --json --select id,name,mimeType,webViewLink,owners
```

If `gog` is unavailable, keep the local Markdown artifact and tell the user exactly what OAuth/install step is missing; use a host-agent Google Workspace flow only when explicitly requested and available. Never share, permission-change, or overwrite Google Docs without user approval.

### 9. Google Sheets sprint export

After the user approves a Sheets write:

```bash
python3 $SKILL_DIR/scripts/export_calendar_sheets.py \
  --calendar content-sprint.csv \
  --title "Attract Signal Sprint - <Brand>"
```

### 10. Reusable signal library

Save top signals for compounding strategy memory:

```bash
python3 $SKILL_DIR/scripts/signal_library.py add --signals signals.json --top-only
python3 $SKILL_DIR/scripts/signal_library.py list
python3 $SKILL_DIR/scripts/signal_library.py search "challenge"
```

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
6. **Skipping the local artifact.** Always write the local Markdown first; the Google Doc is a copy of that source file.

## Verification Checklist

- [ ] Channel Shorts URL and threshold recorded.
- [ ] Every analyzed Short includes a source link citation.
- [ ] Likes/views/comments are either real metadata or explicitly marked unknown.
- [ ] Baselines, normalized engagement, signal score, and signal reason are present when metadata allows.
- [ ] Transcript status is recorded for every video.
- [ ] Individual breakdowns include trend type, hook, visual hooks, and signal pattern.
- [ ] Channel-level synthesis starts with Avatar, Promise, Proof, and Path.
- [ ] Hook library includes raw hooks, templates, ready-to-read hook lines, pattern tags, and winner-adjacent variants.
- [ ] If a single hook pattern dominates, the report branches it into distinct sub-templates and rotates them in the sprint.
- [ ] Script and shot-list sections use creator-facing script lines plus builder notes for Hook -> Meat -> Payoff -> CTA.
- [ ] Product brands with `product_mode` show product, application, and result inside the meat.
- [ ] Reports stay industry-agnostic unless the user supplies brand context.
- [ ] 14-day sprint matrix uses 70/20/10, compact style/CTA IDs, `script_line_0_2`, product steps, and source links.
- [ ] Thumbnail concepts and storyboard/image-generation prompts avoid copying source creators.
- [ ] Non-YouTube platform data came from user-provided exports and is labeled by platform.
- [ ] Reusable signal library updates are local unless the user explicitly asks to share/export them.
- [ ] The local Markdown exists.
- [ ] The default Google Doc copy was created when `gog` auth was available, or the missing auth/install step was clearly reported.
- [ ] The returned Doc URL/ID was verified.
