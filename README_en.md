<div align="center">

# Amazon-Bestsellers-Summary

*One-click analysis of Amazon Bestsellers Top50 categories with three-dimensional market insights.*

[![Claude Code Plugin](https://img.shields.io/badge/Claude_Code-Plugin-blue)](https://code.claude.com/claude-code)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-yellow)](https://www.python.org/)

> **Claude-Code-Plugin** | **MCP Server** | **Multi-Agent** | **MIT License**

</div>

---

<div align="center">

**🌐 Language / 语言**

[简体中文](README.md) | [**English**](README_en.md)

</div>

---

## The Problem

Are you struggling with these analysis challenges?

| Scenario | Result |
|----------|--------|
| Manually collecting Amazon Top50 product data | Days of work, scattered data hard to integrate |
| Unsure how to analyze market competition | No systematic framework, superficial analysis |
| Large and messy user review data | Unable to extract valuable user insights |
| Scattered A+ content materials | Hard to summarize competitor content strategies |

**Amazon-Bestsellers-Summary** provides a fully automated solution: from crawling → chunking → three-dimensional analysis → summary report, all in one command.

---

## Core Features

### Three-Dimensional Analysis System

```
┌───────────────────────────────────────────────────────────────┐
│  Marketplace Dimension: Market competition landscape analysis │
│  Reviews Dimension: User sentiment and needs insights         │
│  A+ Content Dimension: Product page content strategy analysis │
└───────────────────────────────────────────────────────────────┘
```

| Dimension | Analysis Content |
|-----------|-----------------|
| **Marketplace** | Price distribution, rating distribution, ranking changes, brand concentration, new product opportunities |
| **Reviews** | Sentiment analysis, user pain points, demand trends, positive/negative keywords |
| **A+ Content** | Image count, copy style, selling point presentation, visual strategy |

---

## Workflow

```mermaid
flowchart LR
    subgraph P1[Phase 1: CRAWL]
        A[MCP Server<br/>Crawl Top50 Product HTML]
    end
    
    subgraph P2[Phase 2: CHUNK]
        B[Chunker Agent<br/>Chunk & Extract<br/>Structured Store]
    end
    
    subgraph P3[Phase 3: ANALYZE]
        C[Marketplace Analyst<br/>Market Analysis]
        D[Reviews Analyst<br/>Review Analysis]
        E[A+ Analyst<br/>Content Strategy]
    end
    
    subgraph P4[Phase 4: SUMMARY]
        F[Summary Report<br/>Consolidated Insights]
    end
    
    A --> B --> C --> F
    B --> D --> F
    B --> E --> F
```

---

## Plugin Structure

```
amazon-bestsellers-summary/
├── .claude-plugin/
│   └── plugin.json          # Plugin metadata
├── agents/                  # Agent definitions
│   ├── amazon-bestsellers-orchestrator.md   # Top-level orchestrator
│   ├── amazon-product-chunker.md            # Data chunking & extraction
│   ├── amazon-bestsellers-marketplace-analyst.md  # Market analysis
│   ├── amazon-bestsellers-reviews-analyst.md       # Review analysis
│   ├── amazon-bestsellers-aplus-analyst.md        # A+ content analysis
│   └── amazon-bestsellers-fine-grained-analyst.md # Fine-grained analysis
├── skills/                  # Skill definitions
│   ├── amazon-extractor/    # Data extraction skills
│   ├── amazon-test-chunker/ # Test chunking skills
│   ├── amazon-bestsellers-aplus-dim/        # A+ dimension skills
│   ├── amazon-bestsellers-marketplace-dim/  # Marketplace dimension skills
│   ├── amazon-bestsellers-reviews-dim/      # Reviews dimension skills
│   └── amazon-bestsellers-fine-grained-dim/ # Fine-grained dimension skills
├── scraper/                 # MCP Server
│   ├── mcp_server.py        # MCP service entry
│   ├── raw_amazon_spider.py # Spider implementation
│   └── requirements.txt     # Python dependencies
└── README.md
```

---

## Installation & Usage

### Method: Launch Orchestrator as Main Session (Supports Multi-Agent Orchestration)

> **Important**: Claude Code subagents cannot nest and spawn other subagents. To allow the orchestrator to dispatch child agents (chunker + four analysts), it must be launched as a **main session**:

```bash
claude --plugin-dir /your/path/to/amazon-bestsellers-summary --agent amazon-bestsellers-summary:amazon-bestsellers-orchestrator --dangerously-skip-permissions
```

Parameter explanation:
- `--plugin-dir` → Points to the plugin root directory (the directory containing `.claude-plugin/plugin.json`)
- `--agent amazon-bestsellers-summary:amazon-bestsellers-orchestrator` → Format is `plugin-name:agent-name`, where plugin-name comes from the `name` field in `plugin.json`
- `--dangerously-skip-permissions` → Skips permission checks, allowing the main session to call all tools (! Required, otherwise Agents will not be created to work)

### Usage Example

**After Method 1 startup**, enter in Claude Code:

```
Please generate an overall report for the womens-hoodies subcategory
```

**After Method 2 startup**, orchestrator is already running as main session, just enter your task:

```
Analyze the Bestsellers Top50 for this category:
https://www.amazon.com/gp/bestsellers/fashion/1040658/
```

The plugin will automatically:
1. Call MCP Server to crawl Top50 product data
2. Spawn chunker agent for chunking and extraction
3. Parallel spawn four analyst agents for dimensional analysis
4. Generate consolidated summary report

---

## Output Example

After analysis, the following will be generated in the workspace directory:

```
workspace/womens-hoodies/
├── chunks/                  # Chunked data
│   ├── 0001_B0XXXXX/       # Product chunks
│   └── global_manifest.json
├── reports/                 # Analysis reports
│   ├── marketplace_dim.md   # Market competition analysis
│   ├── reviews_dim.md       # User review analysis
│   ├── aplus_dim.md         # A+ content analysis
│   └── fine_grained_dim.md  # Fine-grained analysis
└── summary.md               # Summary report
```

---

## Agent Reference

| Agent | Responsibility |
|-------|---------------|
| `amazon-bestsellers-orchestrator` | Top-level orchestrator, coordinates the entire pipeline |
| `amazon-product-chunker` | Data chunking and structured extraction |
| `amazon-bestsellers-marketplace-analyst` | Market competition dimension analysis |
| `amazon-bestsellers-reviews-analyst` | User review dimension analysis |
| `amazon-bestsellers-aplus-analyst` | A+ content dimension analysis |
| `amazon-bestsellers-fine-grained-analyst` | Fine-grained dimension analysis |

---

## Requirements

- **Claude Code** >= 1.0.0
- **Python** >= 3.10
- **Playwright** (for crawler)

---

## FAQ

### Q: Crawler won't start?

Make sure Playwright browser is installed:
```bash
playwright install chromium
```

### Q: How to view installed plugins?

```bash
/plugin
```

### Q: How to reload plugins?

```bash
/reload-plugins
```

---

## Acknowledgments

This plugin is built on the following technologies:

- **[Claude Code](https://code.claude.com)** — Official Anthropic AI coding assistant
- **[MCP Protocol](https://modelcontextprotocol.io)** — Model Context Protocol
- **[Playwright](https://playwright.dev)** — Browser automation framework

---

## License

MIT License
