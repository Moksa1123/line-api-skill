# line-api-skill

**Stop guessing LINE's API. Look it up.**

An [Agent Skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
that turns the entire LINE Platform documentation into a queryable database, so your
AI assistant answers from the spec instead of from memory.

<p>
  <img src="https://img.shields.io/badge/endpoints-121-success?style=flat-square" alt="121 endpoints">
  <img src="https://img.shields.io/badge/fields-1584-blue?style=flat-square" alt="1584 fields">
  <img src="https://img.shields.io/badge/dataset-3675%20rows-orange?style=flat-square" alt="3675 rows">
  <img src="https://img.shields.io/badge/platforms-8-9cf?style=flat-square" alt="8 platforms">
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square" alt="zero dependencies">
</p>

```
121 endpoints · 1,584 request/response fields · 295 response fields
233 error codes · 247 webhook fields · 136 Flex components · 44 URL schemes
35 LIFF APIs across 58 SDK versions · 80 mobile SDK types · 92 official FAQs
```

English · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

---

## The Problem

LINE's API punishes small mistakes in ways that are hard to trace.

`chatBarText` is capped at 14 characters. A carousel column's `text` allows 120
characters — but only 60 once you add a thumbnail or a title. Rich menu images upload
to `api-data.line.me`, not `api.line.me`. A reply token dies after one minute and one
use. Bubbles in one carousel must all share the same width.

None of that is guessable, and an assistant working from memory will confidently get
it wrong. This skill makes it check first.

## Quick Start

```bash
git clone https://github.com/Moksa1123/line-api-skill
cd line-api-skill
python tools/install-skill.py claude-code --global
```

Then just ask, in your own words:

```
You:   Build me a LINE bot that replies to orders with a Flex card

Agent: (looks up the endpoint, the Flex schema and the field limits,
        writes the code, validates the JSON offline before sending)
```

## Install

```bash
python tools/install-skill.py --list                   # see all platforms
python tools/install-skill.py claude-code --global
python tools/install-skill.py cursor                   # into the current project
python tools/install-skill.py claude-ai --to ./build    # zip to upload
```

8 platforms — Claude Code, Claude.ai, Cursor, Codex CLI, Gemini CLI, Devin Desktop
(ex-Windsurf), GitHub Copilot, Continue. Three install shapes, depending on how each
platform loads a skill: the full directory, a single flattened rule file, or a zip for
web upload. Upgrades delete what the previous version left behind — an installer that
leaves last year's wrong dataset beside this year's right one is worse than no
installer.

## Use

You normally never run the tools yourself. The skill teaches the agent the loop:

```
1. look it up        search.py     endpoint, field, limit, enum, error, FAQ
2. write the JSON    (the agent)   straight from the shapes it just read
3. validate offline  validate.py   type, required, typos, enum, caps, deprecated
4. only then send    lineapi.py    correct host, correct headers
```

Drive it by hand when you want to:

```bash
python scripts/search.py "carousel"                  # auto-detects the domain
python scripts/search.py "get bot info" --domain response
python scripts/search.py "圖文選單" --domain all      # Chinese queries work too
python scripts/validate.py message.json --as push
python scripts/signature.py verify --secret <s> --body-file b.json --signature <sig>
python scripts/lineapi.py info
```

The validator points at the exact path:

```
❌ $.contents.body.layout               missing required property 'layout'
❌ $.contents.body.contents[0].weight   'extra-bold' invalid — use: regular, bold
⚠️  $.template.columns                  columns have inconsistent action counts
```

### Auditing code you already have

Point the reviewer at an existing integration and it checks the code against the
same dataset — is this endpoint real, is the host right, is the signature computed
over the raw body and compared in constant time, is this message JSON valid, is this
API still alive:

```bash
python scripts/review.py ./src
python scripts/review.py app.py --min-severity error   # only what must be fixed
python scripts/review.py ./src --format json           # for CI
```

```
❌ [signature-body] app.py:14   signature computed over re-serialized JSON
   → use the raw bytes (Flask: request.get_data() | Express: express.raw())
❌ [wrong-host]      app.py:29   /v2/bot/message/{}/content must use api-data.line.me
⚠️  [message-json]    app.py:21   unknown property 'quickreply' (did you mean quickReply?)
```

Nine rules, each with a fix and a link to the official page it comes from. Clean code
reports nothing — a test asserts zero findings across this repo's own examples.

## What's Covered

| Area | What you can look up |
|---|---|
| Messaging API | 97 endpoints, rate limits, retry keys, quota, insight |
| Message objects | 11 types, quick reply, 4 templates, 9 action objects |
| Flex Message | containers, 9 components, every property, size limits |
| Rich menu | object shape, image spec, aliases, per-user linking |
| Webhook | 20 events, 247 typed fields, signature verification |
| LINE Login | OAuth 2.0 + OIDC, scopes, ID token verification |
| LIFF | 35 APIs, introduced-in version, tree-shakable modules |
| LINE MINI App | verified vs unverified, service messages, in-app purchase |
| URL schemes | 44 schemes, and the three platform limits people trip on |
| Mobile SDKs | 80 iOS/Android types with links into the generated reference |

Plus LINE's 57 official glossary terms, 92 FAQ entries, curated troubleshooting, and a
list of what LINE has discontinued (LINE Notify ended 2025-03-31) so the assistant
never recommends a dead API.

## Tools

| Tool | What it does |
|---|---|
| `search.py` | BM25 over 25 domains; Chinese queries auto-expand to English terms |
| `validate.py` | Offline message/Flex validation — types, required, typos, enums, caps |
| `signature.py` | Webhook signature; channel access tokens incl. a pure-Python RS256 JWT |
| `lineapi.py` | Zero-dependency Messaging API client; routes `api-data.line.me` for you |
| `review.py` | Audits code you already have: dead APIs, wrong host, signature handling, typo'd endpoints, bad message JSON |
| `test_line.py` | 45 offline tests + 6 live tests |

## How the Data Is Built

```
https://developers.line.biz/llms.txt        github.com/line/line-openapi
        ↓ tools/fetch_sources.py                    ↓
231 official pages (most have an .md variant)   10 OpenAPI specs
        ↓ tools/build_dataset.py
line-api/data/*.csv    ← cross-checked: docs endpoints ⊇ OpenAPI endpoints
```

Four independent guards, each of which has caught real mistakes:

| Guard | Checks |
|---|---|
| `test_line.py` | data integrity, search, validator, signature, JWT |
| `audit_coverage.py` | every documented field made it into the dataset |
| `check_links.py` | every doc URL resolves (detects the SPA's fake 200s) |
| `check_docs.py` | the numbers in this README match the actual data |

The scraped pages live in `.docs-cache/`, which is **git-ignored and never
published** — that content belongs to LY Corporation. This repository ships only the
derived dataset and its own writing.

To refresh against the latest docs:

```bash
python tools/fetch_sources.py
python tools/build_dataset.py
python tools/audit_coverage.py
python tools/check_links.py --md
python tools/check_docs.py
python line-api/scripts/test_line.py
```

## License

MIT for the code in this repository.

LINE, LINE Messaging API, LIFF and LINE MINI App are trademarks of LY Corporation.
This project is not affiliated with LY Corporation; the dataset is an organised
reading of its public documentation and public OpenAPI specifications.
