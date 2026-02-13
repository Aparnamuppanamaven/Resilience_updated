# 🚀 Quick Setup Guide - Resilience System

## ⚠️ IMPORTANT: Python Installation Required

**Python is not currently installed on your system.** You need to install it first before running the Django project.

## Step 1: Install Python (REQUIRED)

1. **Download Python:**
   - Go to: https://www.python.org/downloads/windows/
   - Click "Download Python 3.x.x" (latest version)

2. **Install Python:**
   - Run the downloaded installer
   - ⚠️ **CRITICAL**: Check the box "Add Python 3.x to PATH" at the bottom of the first screen
   - Click "Install Now"
   - Wait for installation to complete

3. **Verify Installation:**
   - Close VS Code completely
   - Reopen VS Code
   - Open terminal in VS Code (Ctrl + ~)
   - Run: `python --version`
   - You should see: `Python 3.x.x`

## Step 2: Run These Commands (After Python is Installed)

Copy and paste these commands **one by one** in VS Code terminal:

```powershell
# Navigate to project folder
cd C:\Users\aparn\Desktop\V1Resilience\Resilience_project

# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Create database migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# (Optional) Create admin user
python manage.py createsuperuser

# Start the server
python manage.py runserver
```

## Step 3: View the Application

After running `python manage.py runserver`, you'll see:
```
Starting development server at http://127.0.0.1:8000/
```

**Open your browser and go to:**
- **Main App**: http://127.0.0.1:8000/
- **Admin Panel**: http://127.0.0.1:8000/admin/

## 🎨 Preview the UI

While you install Python, you can preview the UI by opening:
- `UI_PREVIEW.html` in your browser (I'll create this file)

## Troubleshooting

**If `python` command doesn't work:**
- Try: `py --version` instead
- If that works, use `py` instead of `python` in all commands above

**If you get "execution policy" error:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**If port 8000 is busy:**
```powershell
python manage.py runserver 8001
```
Then access: http://127.0.0.1:8001/


