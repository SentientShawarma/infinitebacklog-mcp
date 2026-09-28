![Infinite Backlog MCP](docs/assets/readme-header.svg)

# Infinite Backlog MCP Server

This is a [Model Context Protocol](https://modelcontextprotocol.io/) server for [Infinite Backlog](https://infinitebacklog.net/), the free collection tracker. Infinite Backlog has no public write API, so the tools drive a Playwright Chromium window. After you're signed in, nested extras can still be checked with a read-only `GET /api/user_collections`.

If you're an assistant calling the tools, read [AGENTS.md](AGENTS.md).

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![MCP](https://img.shields.io/badge/protocol-MCP-555555.svg)
![Listed on mcpservers.org](https://mcpservers.org/badge.svg)

## Sign in

You sign in once. After that, the same window remembers you. Your Brave, Chrome, or Edge cookies are not used.

- **In the window.** Leave the username and password empty. A browser window opens. Sign in there yourself.
- **In a file.** Copy [.env.example](.env.example) to `.env` in this folder. Put your username or email in `IB_USERNAME`, and your password in `IB_PASSWORD`.

## What you can do

- Search the game catalog
- Update your collection
- Set ratings and write reviews
- Keep play records
- Add DLC, packs, and other extras to a game you already own



## Tools



### Deterministic (always available)


| Name                            | Description                                                                                                                             | Key inputs                                                                           |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `open_site`                     | Open an Infinite Backlog path in this server's Playwright window. `headless=false` shows the window so you can sign in once.            | `path`, `wait_ms`, `headless`                                                        |
| `search_games`                  | Search the games catalog.                                                                                                               | `query`, `wait_ms`                                                                   |
| `get_page_text`                 | Extract visible page text.                                                                                                              | `max_chars`                                                                          |
| `get_page_html`                 | Read HTML for a selector (default `body`).                                                                                              | `selector`, `max_chars`                                                              |
| `get_links`                     | List links on the current page.                                                                                                         | `max_links`                                                                          |
| `click`                         | Click by CSS selector or `text=...` on an Infinite Backlog page. Blocked for DELETE GAME, DELETE DRAFT, YES/NO, and UNLOCK CUSTOM TAGS. | `selector`, `wait_ms`                                                                |
| `fill`                          | Fill an input. Refuses password and credential selectors.                                                                               | `selector`, `value`                                                                  |
| `evaluate_js`                   | Debug-only page JavaScript. Disabled unless `IB_ALLOW_EVAL_JS=true`.                                                                    | `expression`                                                                         |
| `screenshot`                    | Save a PNG under the OS temp `infinitebacklog-mcp` directory (path is confined).                                                        | `path`, `full_page`                                                                  |
| `login`                         | Type `IB_USERNAME` and `IB_PASSWORD` into the login form. If either is missing, nothing is typed.                                       | `headless`                                                                           |
| `current_url`                   | Return the current URL and title.                                                                                                       | none                                                                                 |
| `close_browser`                 | Close the Playwright window. Brave, Chrome, and Edge stay open.                                                                         | none                                                                                 |
| `list_related_content`          | List related DLC, packs, editions, and extras on a game page.                                                                           | `game_slug`, `wait_ms`                                                               |
| `list_collection_content_menus` | Read Add DLC, owned DLC, addon boxes, and GAME EDITION text on an edit form (login required).                                           | `edit_path`, `wait_ms`                                                               |
| `add_game_content`              | Attach nested extras on the parent edit form. Ticks `addon-*` inputs, not the label.                                                    | `parent_slug`, `names`, `collection_id`                                              |
| `list_collection_game_options`  | Read copies, extra-platform control, progress, acquisition, ratings, reviews, and Play Records (no save).                               | `slug`, `collection_id`                                                              |
| `set_game_rating`               | Set or clear 1-10 overall plus Visual / Gameplay / Story / Audio / Playability.                                                         | `slug`, `score`, sub-ratings, `clear`                                                |
| `add_game_review`               | Draft or publish at `/games/{slug}/add-review`. Publish needs 800+ characters.                                                          | `slug`, `body`, `publish`, `title`                                                   |
| `delete_game_review`            | Delete a **draft** review. Published reviews are out of scope unless named.                                                             | `slug`, `confirm`, `published`                                                       |
| `add_game_platform_copy`        | Add another GAME INFORMATION copy via `button.extra-platform`.                                                                          | `slug`, `platform`, `digital`, `submit`                                              |
| `set_game_progress`             | Set per-copy status, completion, 0-100 bar, and notes.                                                                                  | `slug`, `collection_id`, `status`, `completion`, `progress`, `notes`, `clear_fields` |
| `set_game_acquisition`          | Set or clear ACQUISITION INFO (type, source, date, amount, costs, notes, Digital Service).                                              | `slug`, `collection_id`, acquisition fields, `clear_fields`                          |
| `delete_game_copy`              | Delete one saved copy. Clicks the single `DELETE GAME FOR {platform}` button, then YES.                                                 | `collection_id` (required), `confirm=true` (required)                                |
| `list_play_records`             | Read Play Records categories on `/edit/stats`.                                                                                          | `slug`, `collection_id`                                                              |
| `set_play_record_category`      | Add a category (`keyValue` / `checkbox` / `progress` / `table`).                                                                        | `slug`, `name`, `type`, `layout`                                                     |
| `set_play_record`               | Add or update a row inside a category.                                                                                                  | `slug`, `category`, `action`, `name`, `value`                                        |
| `remove_play_record`            | Remove a row, or a whole category with `confirm=true`.                                                                                  | `slug`, `category`, `row_index`, `confirm`                                           |




### Autonomous (requires `browser-use` and an LLM key)


| Name                   | Description                                                                                                                           | Key inputs                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `run_browser_use_task` | High-level goal on infinitebacklog.net only. The agent plans and executes with vision plus DOM. Best for multi-step or fragile flows. | `task`, `max_steps`, `model`, `headless` |




## Requirements

- Python 3.11 or newer
- Playwright Chromium
- An MCP client (Cursor, Claude Desktop, VS Code, and others)
- An LLM API key only when using `run_browser_use_task`



## Installation

```bash
cd infinitebacklog-mcp
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

Optional autonomous agent:

```bash
pip install -e ".[agent]"
```

Copy [.env.example](.env.example) to `.env` and fill in what you need. Don't commit `.env`.

## Quick start

After install:

```bash
infinitebacklog-mcp
```

Or as a module:

```bash
python -m infinitebacklog_mcp.server
```

Development without installing the console script still works:

```bash
python server.py
```

The MCP server name is `infinitebacklog`. Logging goes to stderr only, which stdio transport requires.

## MCP client configuration

Use the absolute path to this project. Treat API keys and `IB_PASSWORD` as secrets. The process loads `.env` from the project directory and will not override variables you already set.

**Installed command (Cursor / Claude Desktop style):**

```json
{
  "mcpServers": {
    "infinitebacklog": {
      "command": "infinitebacklog-mcp",
      "env": {
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

**Module path (development):**

```json
{
  "mcpServers": {
    "infinitebacklog": {
      "command": "python",
      "args": ["-m", "infinitebacklog_mcp.server"],
      "cwd": "/absolute/path/to/infinitebacklog-mcp",
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "IB_USERNAME": "",
        "IB_PASSWORD": ""
      }
    }
  }
}
```

**Legacy file launch** (still supported):

```json
{
  "mcpServers": {
    "infinitebacklog": {
      "command": "python",
      "args": ["/absolute/path/to/infinitebacklog-mcp/server.py"],
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "IB_USERNAME": "",
        "IB_PASSWORD": ""
      }
    }
  }
}
```

Public pages work without a session. Collection tools need one of the two sign-in paths above.

## Environment variables


| Variable                 | Required                                  | Description                                                                                       |
| ------------------------ | ----------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY`         | For the autonomous tool (one of the four) | OpenAI key for `run_browser_use_task`                                                             |
| `ANTHROPIC_API_KEY`      | Alternative                               | Anthropic key                                                                                     |
| `GOOGLE_API_KEY`         | Alternative                               | Google key                                                                                        |
| `BROWSER_USE_API_KEY`    | Alternative                               | browser-use Cloud key                                                                             |
| `IB_USERNAME`            | For `.env` sign-in                        | Username or email for the Infinite Backlog login form. Leave blank to sign in through Playwright. |
| `IB_PASSWORD`            | For `.env` sign-in                        | Password for that form. Leave blank to sign in through Playwright. Treat it as a secret.          |
| `IB_HEADLESS`            | Optional                                  | Default headless mode when a tool doesn't pass `headless` (`true` / `false`)                      |
| `IB_VIEWPORT_WIDTH`      | Optional                                  | Playwright viewport width (default `1280`, clamped)                                               |
| `IB_VIEWPORT_HEIGHT`     | Optional                                  | Playwright viewport height (default `800`, clamped)                                               |
| `IB_ALLOW_EVAL_JS`       | Optional                                  | Enable the `evaluate_js` debug tool (`true` / `false`, default `false`)                           |
| `IB_CHROMIUM_NO_SANDBOX` | Optional                                  | Pass `--no-sandbox` to Chromium (default `false`; containers only)                                |




## Security

- Unofficial project. Not affiliated with Infinite Backlog.
- Navigation, in-page API fetches, and `run_browser_use_task` stay on `https://infinitebacklog.net`. Other origins are rejected.
- `evaluate_js` is off by default. Screenshots can only be written under the OS temp `infinitebacklog-mcp` directory. Chromium `--no-sandbox` is opt-in via `IB_CHROMIUM_NO_SANDBOX`.
- Generic `fill` refuses password fields. Only `login` types `IB_PASSWORD`, and only into the Infinite Backlog login form.
- Treat API keys and `IB_PASSWORD` as secrets. Don't commit `.env`.
- Assistants using these tools should follow [AGENTS.md](AGENTS.md).



## Development

Project layout:

```text
infinitebacklog-mcp/
├── AGENTS.md              # operating brief for MCP client agents
├── src/infinitebacklog_mcp/
│   ├── server.py          # MCPServer, instructions, main()
│   ├── browser.py         # Playwright lifecycle
│   ├── login.py           # Keycloak username/password form
│   ├── config.py          # constants, .env loading
│   ├── security.py        # origin, cookie, path, and identifier allowlists
│   ├── matching.py        # name / kind matching
│   ├── tools/             # deterministic + agent tools
│   └── ...
├── tests/
├── docs/assets/           # README logos
└── server.py              # compatibility shim
```



## License

MIT. See [LICENSE](LICENSE).