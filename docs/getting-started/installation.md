# Installation

## Requirements

- Python 3.11 or higher
- OpenAI API key

## Using uv (Recommended)

[uv](https://github.com/astral-sh/uv) is the recommended package manager for fast, reliable installs.

```bash
# Clone the repository
git clone https://github.com/fabrizioamort/RLM-RAG.git
cd RLM-RAG

# Install with all extras
uv sync --extra dev --extra docs --extra mkdocs --extra ui

# Or install minimal
uv sync
```

## Using pip

```bash
# Clone the repository
git clone https://github.com/fabrizioamort/RLM-RAG.git
cd RLM-RAG

# Install in editable mode
pip install -e ".[dev]"

# With documentation support
pip install -e ".[dev,docs,mkdocs]"

# With Streamlit UI
pip install -e ".[dev,ui]"
```

## Configuration

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Add your OpenAI API key:

```
OPENAI_API_KEY=sk-your-api-key-here
```

## Verify Installation

```bash
# Run tests
uv run pytest

# Run example
uv run python examples/rlm_manual_test.py
```

## Optional Dependencies

| Extra | Purpose | Install |
|-------|---------|---------|
| `dev` | Testing, linting, type checking | `uv sync --extra dev` |
| `docs` | PDF and DOCX document support | `uv sync --extra docs` |
| `mkdocs` | Documentation generation | `uv sync --extra mkdocs` |
| `ui` | Streamlit inspector UI | `uv sync --extra ui` |
