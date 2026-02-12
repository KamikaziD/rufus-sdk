# GitHub Installation Quick Reference

## 🎯 For You (Package Maintainer)

### 1. Commit the Package Updates

```bash
# Stage the packaging files
git add pyproject.toml LICENSE MANIFEST.in verify_installation.py INSTALLATION_FOR_DEVELOPERS.md GITHUB_INSTALL_QUICKSTART.md

# Commit
git commit -m "feat: Add pip install from GitHub support

- Updated pyproject.toml with correct repository URL
- Added SQLAlchemy and Alembic to core dependencies
- Created installation guide for developers
- Added MIT LICENSE file
- Added MANIFEST.in for proper package distribution
- Created verify_installation.py script for testers

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# Push to GitHub
git push origin feature/alembic-migration
```

### 2. Merge to Main (when ready)

```bash
# Create PR or merge directly
git checkout main
git merge feature/alembic-migration
git push origin main
```

### 3. (Optional) Create Release Tag

```bash
# Tag current version
git tag -a v0.1.0 -m "Release v0.1.0 - Initial beta with Alembic migrations"
git push origin v0.1.0
```

---

## 👥 For Your Testers

### Quick Install Command

Send testers this one-liner:

```bash
pip install "git+https://github.com/KamikaziD/rufus-sdk.git#egg=rufus-edge[all]"
```

### Verify Installation

```bash
# Clone repo to get verification script
git clone https://github.com/KamikaziD/rufus-sdk.git
cd rufus-sdk
python verify_installation.py
```

Or without cloning:

```bash
# Download and run verification script
curl -O https://raw.githubusercontent.com/KamikaziD/rufus-sdk/main/verify_installation.py
python verify_installation.py
```

---

## 📧 Email Template for Testers

```
Subject: Rufus SDK Beta - Installation Instructions

Hi team,

I'm excited to share the Rufus SDK beta for testing! Here's how to get started:

**Installation (5 minutes):**

1. Install the package:
   pip install "git+https://github.com/KamikaziD/rufus-sdk.git#egg=rufus-edge[all]"

2. Verify it works:
   rufus --version

3. (Optional) Run verification script:
   git clone https://github.com/KamikaziD/rufus-sdk.git
   cd rufus-sdk
   python verify_installation.py

**Documentation:**
- Quickstart Guide: https://github.com/KamikaziD/rufus-sdk/blob/main/QUICKSTART.md
- Full Installation Guide: https://github.com/KamikaziD/rufus-sdk/blob/main/INSTALLATION_FOR_DEVELOPERS.md

**Getting Help:**
- GitHub Issues: https://github.com/KamikaziD/rufus-sdk/issues
- Slack/Discord: [your channel]
- Email: [your email]

**What to Test:**
- Install and verify the package works
- Run the example workflows (examples/sqlite_task_manager/)
- Try creating a simple workflow
- Test with your use case

Please report any issues on GitHub or reach out directly!

Thanks,
[Your Name]
```

---

## 🔐 If Repository is Private

Testers will need GitHub access. Two options:

### Option A: Add as Collaborators
1. Go to: https://github.com/KamikaziD/rufus-sdk/settings/access
2. Click "Add people"
3. Add tester GitHub usernames
4. They install with SSH: `pip install git+ssh://git@github.com/KamikaziD/rufus-sdk.git`

### Option B: Personal Access Token
1. Tester creates PAT: GitHub Settings → Developer settings → Personal access tokens
2. Select scope: `repo`
3. Install with: `pip install git+https://USERNAME:TOKEN@github.com/KamikaziD/rufus-sdk.git`

---

## 🎯 Installation Methods Summary

| Method | Command | Use Case |
|--------|---------|----------|
| **Latest from main** | `pip install git+https://github.com/KamikaziD/rufus-sdk.git` | Most stable |
| **Specific branch** | `pip install git+https://github.com/KamikaziD/rufus-sdk.git@BRANCH` | Test features |
| **Specific version** | `pip install git+https://github.com/KamikaziD/rufus-sdk.git@v0.1.0` | Reproducible |
| **With extras** | `pip install "git+...#egg=rufus-edge[all]"` | Full features |
| **SSH (private)** | `pip install git+ssh://git@github.com/KamikaziD/rufus-sdk.git` | Private repo |

---

## ✅ What Was Set Up

1. ✅ **pyproject.toml** - Updated with correct repo URL and dependencies
2. ✅ **LICENSE** - MIT license file created
3. ✅ **MANIFEST.in** - Ensures all files are included in package
4. ✅ **verify_installation.py** - Script for testers to verify installation
5. ✅ **INSTALLATION_FOR_DEVELOPERS.md** - Comprehensive installation guide
6. ✅ **Package structure** - Already correctly set up with src/rufus/

---

## 🚀 Next Steps

**Immediate:**
1. Commit and push the packaging files (commands above)
2. Test the installation yourself:
   ```bash
   pip install "git+https://github.com/KamikaziD/rufus-sdk.git@feature/alembic-migration#egg=rufus-edge[all]"
   python verify_installation.py
   ```

**Before sharing with testers:**
1. Merge to main branch
2. Verify installation from main works
3. Update README.md with installation instructions
4. (Optional) Create v0.1.0 tag for reproducible installs

**When ready to share:**
1. Send email to testers (template above)
2. Create GitHub issues for tracking feedback
3. Set up Slack/Discord channel for questions
4. Monitor installations and help with issues

---

## 📊 Monitoring Installations

Check who has installed:
- GitHub Insights → Traffic → Clones
- Watch for GitHub issues
- Ask testers to report success/failures

---

## 🔄 Updating Package

When you make changes:

```bash
# Make your changes
git add .
git commit -m "fix: Your fix description"
git push

# Testers update with:
pip install --force-reinstall git+https://github.com/KamikaziD/rufus-sdk.git
```

---

## 📝 Additional Notes

- **Package name**: `rufus-edge` (what pip installs)
- **Import name**: `rufus` (what Python imports)
- **CLI command**: `rufus` (command line tool)
- **Extras available**: `all`, `server`, `postgres`, `cli`, `performance`

---

**Ready to go!** Just commit the files and share the install command with your testers.
