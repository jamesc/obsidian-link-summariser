# Dev Container Configuration

This directory contains the VS Code Dev Container configuration for the Obsidian Link Summariser project.

## What's Included

### Base Image
- **Python 3.11** development container from Microsoft
- Pre-configured with common Python development tools

### Installed Features
- **uv package manager** - Fast Python package installer and resolver

### VS Code Extensions
The following extensions are automatically installed:
- **Python** - Python language support
- **Pylance** - Fast Python language server
- **Ruff** - Fast Python linter and formatter
- **MyPy Type Checker** - Static type checking
- **GitHub Copilot** - AI pair programmer
- **GitHub Copilot Chat** - Conversational AI assistance
- **Even Better TOML** - TOML language support
- **YAML** - YAML language support

### Editor Configuration
- Format on save enabled with Ruff
- Auto-organize imports on save
- Strict type checking mode
- Pytest integration for testing
- Lint and format arguments configured for project

## Getting Started

### Prerequisites
1. [Docker Desktop](https://www.docker.com/products/docker-desktop) installed and running
2. [Visual Studio Code](https://code.visualstudio.com/) installed
3. [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) installed in VS Code

### Opening the Project

1. **Clone the repository**
   ```bash
   git clone https://github.com/jamesc/obsidian-link-summariser.git
   cd obsidian-link-summariser
   ```

2. **Create `.env` file** (required for devcontainer)
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```
   
   **Important**: The devcontainer mounts your `.env` file as read-only. Make sure it exists before opening the container.

3. **Open in VS Code**
   ```bash
   code .
   ```

4. **Reopen in Container**
   - Press `F1` or `Ctrl+Shift+P` (Windows/Linux) / `Cmd+Shift+P` (Mac)
   - Type "Dev Containers: Reopen in Container"
   - Select the command
   - Wait for the container to build (first time only)

### What Happens on First Build

The container will automatically:
1. Pull the Python 3.11 base image
2. Install the uv package manager
3. Install all VS Code extensions
4. Run `uv sync --all-extras` to install Python dependencies
5. Configure the Python environment

This process takes a few minutes the first time, but subsequent starts are much faster.

## Working in the Container

### Dependencies are Pre-installed
All Python dependencies are installed during container creation via `uv sync --all-extras`.

### Adding New Dependencies
```bash
# Add runtime dependency
uv add <package-name>

# Add dev dependency
uv add --dev <package-name>

# Rebuild container to persist changes
# Use Command Palette: "Dev Containers: Rebuild Container"
```

### Running Commands
All commands work as normal inside the container:
```bash
# Run tests
uv run pytest

# Run linting
uv run ruff check .

# Run formatting
uv run ruff format .

# Run type checking
uv run mypy .

# Run the CLI
uv run summarize-links --help
```

### Environment Variables
The `.env` file from your local workspace is mounted as read-only into the container. This means:
- Your API keys and secrets stay secure on your host machine
- Changes to `.env` require container restart to take effect
- The container cannot modify your `.env` file

## Troubleshooting

### ".env file not found" Error
The devcontainer configuration expects a `.env` file to exist. If you don't have one:
```bash
cp .env.example .env
```
Then rebuild the container.

### Container Build Fails
1. Ensure Docker Desktop is running
2. Check Docker has sufficient resources (4GB+ RAM recommended)
3. Try rebuilding: Command Palette → "Dev Containers: Rebuild Container"

### Extensions Not Working
Some extensions require the container to be fully initialized. Wait for the postCreateCommand to complete, then:
1. Reload the window: Command Palette → "Developer: Reload Window"
2. If issues persist, rebuild the container

### Python Environment Issues
If the Python environment seems broken:
1. Open a terminal in the container
2. Run `uv sync --all-extras` manually
3. Reload the window

## Benefits of Using Dev Containers

✅ **Consistent Environment** - Everyone uses the same Python version, tools, and dependencies

✅ **Fast Onboarding** - New contributors can start coding in minutes

✅ **Isolated Development** - Container environment doesn't affect your host system

✅ **Pre-configured Tools** - All linters, formatters, and type checkers ready to use

✅ **Works Everywhere** - Same environment on Windows, Mac, and Linux

## Alternative: Using Without Dev Container

If you prefer not to use Dev Containers, you can develop locally:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync --all-extras

# Set up your editor with the extensions manually
```

See the main [README.md](../README.md) for full development setup instructions.
