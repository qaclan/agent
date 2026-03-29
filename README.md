<p align="center">
  <img src="logo.png" alt="QAClan" width="500">
</p>

A standalone CLI and Web tool for QA test management and execution. Manage projects, features, scripts, suites, environments, and test runs — all stored locally in SQLite.

Built with Python, Click, and Rich. Harnessing the power of Playwright for browser test recording and execution.

## Getting Started

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Start the web UI

```bash
qaclan serve
```

Open `http://localhost:7823` in your browser.

Options:

```bash
qaclan serve --port 9000       # Custom port
```

## Data Storage

All data is stored locally at `~/.qaclan/`:

```
~/.qaclan/
├── qaclan.db      <- SQLite database
├── scripts/       <- Recorded/imported script files
└── config.json    <- Active project setting
```

## License

[Business Source License 1.1](LICENSE)
