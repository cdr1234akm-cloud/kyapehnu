# 🔐 Environment Setup Guide

## What Changed?

Your hardcoded API key has been removed from the code and moved to a `.env` file.

### ✅ Files Created/Updated:

1. **`.env`** - Local environment variables (added to .gitignore, won't be committed)
2. **`.env.example`** - Template showing what environment variables you need
3. **`.gitignore`** - Updated to protect `.env` file
4. **`requirements.txt`** - Added `python-dotenv` package
5. **`backend/main.py`** - Now loads API key from environment

---

## 🚀 Setup Instructions

### 1. Install python-dotenv
```bash
pip install python-dotenv
# Or reinstall from requirements:
pip install -r requirements.txt
```

### 2. Configure Your `.env` File

The `.env` file already has your API key. For production, replace it:

```bash
# .env (in project root)
GROQ_API_KEY=your_actual_key_here
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```

### 3. Test It Works
```bash
python backend/main.py
```

---

## 🔒 Security Checklist

- [x] API key removed from main.py
- [x] `.env` added to `.gitignore` (won't be committed)
- [x] `.env.example` created (safe to commit, shows structure)
- [x] Code loads from environment variables

### Before Committing:
```bash
# Remove cached files if they were previously committed
git rm --cached backend/main.py
git rm --cached .env  # if exists in git
git add .
git commit -m "chore: remove hardcoded API keys, use environment variables"
git push
```

---

## 📝 Environment Variables Reference

| Variable | Source | Required |
|----------|--------|----------|
| `GROQ_API_KEY` | https://console.groq.com/keys | ✅ Yes |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary Dashboard | ❌ Optional |
| `CLOUDINARY_API_KEY` | Cloudinary Dashboard | ❌ Optional |
| `CLOUDINARY_API_SECRET` | Cloudinary Dashboard | ❌ Optional |

---

## 💡 Best Practices

✅ **DO:**
- Keep `.env` in `.gitignore` 
- Commit `.env.example` (shows needed variables)
- Use environment variables for all secrets
- Never hardcode API keys

❌ **DON'T:**
- Commit `.env` file to git
- Paste keys in code
- Share `.env` files
- Use same keys across environments

---

## ✨ You Can Now Commit!

```bash
git status  # Should NOT show .env
git add .
git commit -m "refactor: use environment variables for API keys"
```

The `.env` file is protected and won't be committed. ✅
