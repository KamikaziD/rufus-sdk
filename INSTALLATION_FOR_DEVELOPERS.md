# Installation Guide for Developers

This guide explains how to install Ruvon SDK directly from GitHub for testing and development.

---

## 🚀 Quick Install (for Testers)

### Method 1: Install Latest from Main Branch

```bash
# Install core package
pip install git+https://github.com/KamikaziD/ruvon-sdk.git

# Install with all optional dependencies
pip install "ruvon[all] @ git+https://github.com/KamikaziD/ruvon-sdk.git"
```

### Method 2: Install Specific Branch (e.g., feature branch)

```bash
# Install from feature/alembic-migration branch
pip install git+https://github.com/KamikaziD/ruvon-sdk.git@feature/alembic-migration

# With extras
pip install "ruvon[all] @ git+https://github.com/KamikaziD/ruvon-sdk.git@feature/alembic-migration"
```

### Method 3: Install Specific Version/Tag

```bash
# Once you create tagged releases
pip install git+https://github.com/KamikaziD/ruvon-sdk.git@v0.1.0
```

---

## 📦 Available Installation Extras

The package supports optional feature sets via extras:

```bash
# Server features (FastAPI, Uvicorn)
pip install "ruvon[server] @ git+https://github.com/KamikaziD/ruvon-sdk.git"

# PostgreSQL support
pip install "ruvon[postgres] @ git+https://github.com/KamikaziD/ruvon-sdk.git"

# CLI enhancements (Rich formatting)
pip install "ruvon[cli] @ git+https://github.com/KamikaziD/ruvon-sdk.git"

# Performance optimizations (uvloop)
pip install "ruvon[performance] @ git+https://github.com/KamikaziD/ruvon-sdk.git"

# Everything
pip install "ruvon[all] @ git+https://github.com/KamikaziD/ruvon-sdk.git"
```

**What each extra includes:**
- `server`: FastAPI, Uvicorn, SlowAPI (for cloud control plane)
- `postgres`: asyncpg (for PostgreSQL persistence)
- `cli`: Rich (for beautiful CLI output)
- `performance`: uvloop (faster async I/O)
- `all`: All of the above

---

## 🔐 Private Repository Access

If the repository becomes private, testers will need authentication:

### Option A: SSH Key (Recommended)

1. **Generate SSH key** (if you don't have one):
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   ```

2. **Add to GitHub**:
   - Go to GitHub Settings → SSH and GPG keys → New SSH key
   - Copy contents of `~/.ssh/id_ed25519.pub`
   - Paste and save

3. **Install package**:
   ```bash
   pip install git+ssh://git@github.com/KamikaziD/ruvon-sdk.git
   ```

### Option B: Personal Access Token (HTTPS)

1. **Create PAT**:
   - GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Generate new token (classic)
   - Select scope: `repo` (full control of private repositories)
   - Copy token (you'll only see it once!)

2. **Install package**:
   ```bash
   pip install git+https://<USERNAME>:<TOKEN>@github.com/KamikaziD/ruvon-sdk.git
   ```

   Example:
   ```bash
   pip install git+https://john:ghp_xxxxxxxxxxxx@github.com/KamikaziD/ruvon-sdk.git
   ```

### Option C: GitHub CLI (gh)

1. **Install GitHub CLI**: https://cli.github.com/
2. **Authenticate**:
   ```bash
   gh auth login
   ```
3. **Install package** (gh handles auth automatically):
   ```bash
   pip install git+https://github.com/KamikaziD/ruvon-sdk.git
   ```

---

## 🧪 Verify Installation

After installation, verify everything works:

```bash
# Check CLI is available
ruvon --version
ruvon --help

# Test Python import
python -c "from ruvon.builder import WorkflowBuilder; print('✅ Ruvon SDK ready!')"

# Run simple workflow (if you have examples)
cd examples/sqlite_task_manager
python simple_demo.py
```

---

## 🔄 Updating to Latest Version

```bash
# Uninstall old version
pip uninstall ruvon -y

# Install latest
pip install git+https://github.com/KamikaziD/ruvon-sdk.git

# Or force reinstall
pip install --force-reinstall git+https://github.com/KamikaziD/ruvon-sdk.git
```

---

## 📋 Requirements File Method

For teams, create a `requirements.txt`:

```text
# requirements.txt
# Install Ruvon SDK from GitHub
ruvon[all] @ git+https://github.com/KamikaziD/ruvon-sdk.git@main

# Or specific branch for testing
# ruvon[all] @ git+https://github.com/KamikaziD/ruvon-sdk.git@feature/alembic-migration

# Or with SSH (for private repo)
# git+ssh://git@github.com/KamikaziD/ruvon-sdk.git#egg=ruvon[all]
```

Then install:
```bash
pip install -r requirements.txt
```

---

## 🐳 Docker Method

If you want to distribute as a Docker image:

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install Ruvon SDK from GitHub
RUN pip install ruvon[all] @ git+https://github.com/KamikaziD/ruvon-sdk.git

# Verify installation
RUN ruvon --version

WORKDIR /app
CMD ["bash"]
```

Build and distribute:
```bash
docker build -t ruvon-sdk:latest .
docker tag ruvon-sdk:latest your-registry/ruvon-sdk:latest
docker push your-registry/ruvon-sdk:latest
```

---

## 🏷️ Version Management Strategy

### Current (Development Phase)

Right now, developers install from branches:
```bash
# Main branch (most stable)
pip install git+https://github.com/KamikaziD/ruvon-sdk.git@main

# Feature branch (testing new features)
pip install git+https://github.com/KamikaziD/ruvon-sdk.git@feature/alembic-migration
```

### Future (Production Phase)

Once ready for production, use semantic versioning with Git tags:

```bash
# Create release tag
git tag -a v0.1.0 -m "Release v0.1.0 - Initial beta"
git push origin v0.1.0

# Users install specific version
pip install git+https://github.com/KamikaziD/ruvon-sdk.git@v0.1.0
```

**Recommended versioning:**
- `v0.1.0` - First beta release (current state)
- `v0.2.0` - After Alembic migration is merged
- `v0.3.0` - Next major feature
- `v1.0.0` - Production-ready release

---

## 🔧 Development Installation

For developers who want to modify the code:

```bash
# Clone repository
git clone https://github.com/KamikaziD/ruvon-sdk.git
cd ruvon-sdk

# Install in editable mode (changes reflect immediately)
pip install -e .

# Or with all extras
pip install -e ".[all]"

# Or using Poetry
poetry install --with dev
```

---

## 🐛 Troubleshooting

### Error: "Could not find a version that satisfies the requirement"

**Solution**: Make sure you're using the correct syntax with quotes:
```bash
pip install "ruvon[all] @ git+https://github.com/KamikaziD/ruvon-sdk.git"
#          ↑ quotes are important!              ↑
```

### Error: "Permission denied (publickey)"

**Solution**: Set up SSH keys or use HTTPS with token (see Private Repository Access above)

### Error: "No module named 'ruvon'"

**Solution**: The package installs as `ruvon` but imports as `ruvon`:
```python
# Correct
from ruvon.builder import WorkflowBuilder

# Wrong
from ruvon_edge.builder import WorkflowBuilder  # This won't work
```

### Error: "Command 'ruvon' not found"

**Solution**: The CLI might not be in your PATH. Try:
```bash
python -m ruvon_cli.main --help

# Or reinstall with --force-reinstall
pip install --force-reinstall git+https://github.com/KamikaziD/ruvon-sdk.git
```

---

## 📞 Getting Help

If you encounter issues:

1. **Check installed version**:
   ```bash
   pip show ruvon
   ```

2. **Check installed files**:
   ```bash
   pip show -f ruvon
   ```

3. **Reinstall from scratch**:
   ```bash
   pip uninstall ruvon -y
   pip cache purge
   pip install git+https://github.com/KamikaziD/ruvon-sdk.git
   ```

4. **Report issue**: Open GitHub issue with:
   - Python version: `python --version`
   - Pip version: `pip --version`
   - Installation command used
   - Full error message

---

## 🎯 Summary for Testers

**To get started quickly:**

1. **Install package**:
   ```bash
   pip install "ruvon[all] @ git+https://github.com/KamikaziD/ruvon-sdk.git"
   ```

2. **Verify it works**:
   ```bash
   ruvon --version
   python -c "from ruvon.builder import WorkflowBuilder; print('✅ Works!')"
   ```

3. **Run examples** (if available in repo):
   ```bash
   git clone https://github.com/KamikaziD/ruvon-sdk.git
   cd ruvon-sdk/examples/sqlite_task_manager
   python simple_demo.py
   ```

That's it! You're ready to test the Ruvon SDK.

---

**Last Updated**: 2026-02-12
