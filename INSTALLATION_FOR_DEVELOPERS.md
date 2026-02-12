# Installation Guide for Developers

This guide explains how to install Rufus SDK directly from GitHub for testing and development.

---

## 🚀 Quick Install (for Testers)

### Method 1: Install Latest from Main Branch

```bash
# Install core package
pip install git+https://github.com/KamikaziD/rufus-sdk.git

# Install with all optional dependencies
pip install "rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git"
```

### Method 2: Install Specific Branch (e.g., feature branch)

```bash
# Install from feature/alembic-migration branch
pip install git+https://github.com/KamikaziD/rufus-sdk.git@feature/alembic-migration

# With extras
pip install "rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git@feature/alembic-migration"
```

### Method 3: Install Specific Version/Tag

```bash
# Once you create tagged releases
pip install git+https://github.com/KamikaziD/rufus-sdk.git@v0.1.0
```

---

## 📦 Available Installation Extras

The package supports optional feature sets via extras:

```bash
# Server features (FastAPI, Uvicorn)
pip install "rufus[server] @ git+https://github.com/KamikaziD/rufus-sdk.git"

# PostgreSQL support
pip install "rufus[postgres] @ git+https://github.com/KamikaziD/rufus-sdk.git"

# CLI enhancements (Rich formatting)
pip install "rufus[cli] @ git+https://github.com/KamikaziD/rufus-sdk.git"

# Performance optimizations (uvloop)
pip install "rufus[performance] @ git+https://github.com/KamikaziD/rufus-sdk.git"

# Everything
pip install "rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git"
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
   pip install git+ssh://git@github.com/KamikaziD/rufus-sdk.git
   ```

### Option B: Personal Access Token (HTTPS)

1. **Create PAT**:
   - GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Generate new token (classic)
   - Select scope: `repo` (full control of private repositories)
   - Copy token (you'll only see it once!)

2. **Install package**:
   ```bash
   pip install git+https://<USERNAME>:<TOKEN>@github.com/KamikaziD/rufus-sdk.git
   ```

   Example:
   ```bash
   pip install git+https://john:ghp_xxxxxxxxxxxx@github.com/KamikaziD/rufus-sdk.git
   ```

### Option C: GitHub CLI (gh)

1. **Install GitHub CLI**: https://cli.github.com/
2. **Authenticate**:
   ```bash
   gh auth login
   ```
3. **Install package** (gh handles auth automatically):
   ```bash
   pip install git+https://github.com/KamikaziD/rufus-sdk.git
   ```

---

## 🧪 Verify Installation

After installation, verify everything works:

```bash
# Check CLI is available
rufus --version
rufus --help

# Test Python import
python -c "from rufus.builder import WorkflowBuilder; print('✅ Rufus SDK ready!')"

# Run simple workflow (if you have examples)
cd examples/sqlite_task_manager
python simple_demo.py
```

---

## 🔄 Updating to Latest Version

```bash
# Uninstall old version
pip uninstall rufus -y

# Install latest
pip install git+https://github.com/KamikaziD/rufus-sdk.git

# Or force reinstall
pip install --force-reinstall git+https://github.com/KamikaziD/rufus-sdk.git
```

---

## 📋 Requirements File Method

For teams, create a `requirements.txt`:

```text
# requirements.txt
# Install Rufus SDK from GitHub
rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git@main

# Or specific branch for testing
# rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git@feature/alembic-migration

# Or with SSH (for private repo)
# git+ssh://git@github.com/KamikaziD/rufus-sdk.git#egg=rufus[all]
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

# Install Rufus SDK from GitHub
RUN pip install rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git

# Verify installation
RUN rufus --version

WORKDIR /app
CMD ["bash"]
```

Build and distribute:
```bash
docker build -t rufus-sdk:latest .
docker tag rufus-sdk:latest your-registry/rufus-sdk:latest
docker push your-registry/rufus-sdk:latest
```

---

## 🏷️ Version Management Strategy

### Current (Development Phase)

Right now, developers install from branches:
```bash
# Main branch (most stable)
pip install git+https://github.com/KamikaziD/rufus-sdk.git@main

# Feature branch (testing new features)
pip install git+https://github.com/KamikaziD/rufus-sdk.git@feature/alembic-migration
```

### Future (Production Phase)

Once ready for production, use semantic versioning with Git tags:

```bash
# Create release tag
git tag -a v0.1.0 -m "Release v0.1.0 - Initial beta"
git push origin v0.1.0

# Users install specific version
pip install git+https://github.com/KamikaziD/rufus-sdk.git@v0.1.0
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
git clone https://github.com/KamikaziD/rufus-sdk.git
cd rufus-sdk

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
pip install "rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git"
#          ↑ quotes are important!              ↑
```

### Error: "Permission denied (publickey)"

**Solution**: Set up SSH keys or use HTTPS with token (see Private Repository Access above)

### Error: "No module named 'rufus'"

**Solution**: The package installs as `rufus` but imports as `rufus`:
```python
# Correct
from rufus.builder import WorkflowBuilder

# Wrong
from rufus_edge.builder import WorkflowBuilder  # This won't work
```

### Error: "Command 'rufus' not found"

**Solution**: The CLI might not be in your PATH. Try:
```bash
python -m rufus_cli.main --help

# Or reinstall with --force-reinstall
pip install --force-reinstall git+https://github.com/KamikaziD/rufus-sdk.git
```

---

## 📞 Getting Help

If you encounter issues:

1. **Check installed version**:
   ```bash
   pip show rufus
   ```

2. **Check installed files**:
   ```bash
   pip show -f rufus
   ```

3. **Reinstall from scratch**:
   ```bash
   pip uninstall rufus -y
   pip cache purge
   pip install git+https://github.com/KamikaziD/rufus-sdk.git
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
   pip install "rufus[all] @ git+https://github.com/KamikaziD/rufus-sdk.git"
   ```

2. **Verify it works**:
   ```bash
   rufus --version
   python -c "from rufus.builder import WorkflowBuilder; print('✅ Works!')"
   ```

3. **Run examples** (if available in repo):
   ```bash
   git clone https://github.com/KamikaziD/rufus-sdk.git
   cd rufus-sdk/examples/sqlite_task_manager
   python simple_demo.py
   ```

That's it! You're ready to test the Rufus SDK.

---

**Last Updated**: 2026-02-12
