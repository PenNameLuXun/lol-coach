# Web Knowledge Design

## Goal

Provide a framework-level "web knowledge" capability that plugins can use to
fetch current external guidance and display it in a dedicated Qt window.

This is intentionally separate from QA:

- Plugins use it to surface passive reference material during gameplay.
- QA continues to use ad-hoc search for direct question answering.

## Scope

First implementation covers:

- Shared web knowledge manager and query model
- LoL provider:
  - Builds champion guide queries from live match data
  - Supports configurable champion count
- TFT provider:
  - Builds "current meta comps" queries
- Dedicated Qt knowledge window
  - If a secondary monitor exists, show there by default
  - Otherwise stay hidden and show while a hotkey is held

## High-Level Flow

1. `ai_worker` discovers the active plugin context
2. Framework asks the active plugin for web knowledge queries
3. Shared search layer fetches results and excerpts
4. Results are cached for a refresh interval
5. UI receives a bundle and renders it in a dedicated knowledge window

## Shared Framework

New shared types:

- `KnowledgeQuery`
  - `key`
  - `title`
  - `query`
  - `sites`
- `KnowledgeItem`
  - `title`
  - `query`
  - `documents`
- `KnowledgeBundle`
  - `plugin_id`
  - `display_name`
  - `summary`
  - `items`

Shared config:

- `web_knowledge.enabled`
- `web_knowledge.refresh_interval_seconds`
- `web_knowledge.search_engine`
- `web_knowledge.timeout_seconds`
- `web_knowledge.max_results_per_site`
- `web_knowledge.max_pages`
- `web_knowledge.default_sites_text`
- `web_knowledge.hotkey`
- `web_knowledge.window_width`
- `web_knowledge.window_height`

Plugin-specific config:

- `plugin_settings.<plugin>.knowledge_enabled`
- `plugin_settings.<plugin>.knowledge_search_sites_text`
- plugin-specific knobs such as LoL champion count

## Plugin Hooks

Plugins can optionally provide:

- `build_web_knowledge_queries(state, config) -> list[KnowledgeQuery]`
- `build_web_knowledge_summary(state) -> str`

If a plugin does not implement these hooks, the framework skips web knowledge
for that plugin.

## LoL Strategy

LoL can extract champion names from `allPlayers`.

First version:

- Prioritize the local player's champion
- Then append other champions from the match
- Limit by `knowledge_max_champions`
- Build one query per champion:
  - `League of Legends <champion> build guide combo current patch`

## TFT Strategy

TFT first version uses a small set of fixed meta queries:

- `current TFT meta comps patch`
- optionally later:
  - `TFT leveling guide current patch`
  - `TFT econ guide current patch`

## UI Strategy

Dedicated `KnowledgeWindow`:

- Read-only rich text view
- Shows plugin title, query labels, source links, excerpts
- If a secondary monitor exists:
  - move window there and show
- Otherwise:
  - window stays hidden
  - hotkey hold temporarily shows it

## Non-goals

First version does not:

- deeply adapt per-site parsing rules
- merge duplicate content semantically
- annotate patch freshness beyond existing search metadata
- replace QA search
