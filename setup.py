"""
Quick setup script for Resilience System Django project
Run: python setup.py
"""
import os
import sys
import subprocess

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"\n{'='*60}")
    print(f"Step: {description}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}")
        return False

def main():
    print("\n" + "="*60)
    print("Resilience System - Django Setup")
    print("="*60)
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("Error: Python 3.8 or higher is required")
        sys.exit(1)
    
    print(f"Python version: {sys.version}")
    
    # Step 1: Install dependencies
    if not run_command("pip install -r requirements.txt", "Installing dependencies"):
        print("\nFailed to install dependencies. Please check your pip installation.")
        sys.exit(1)
    
    # Step 2: Make migrations
    if not run_command("python manage.py makemigrations", "Creating database migrations"):
        print("\nFailed to create migrations.")
        sys.exit(1)
    
    # Step 3: Run migrations
    if not run_command("python manage.py migrate", "Running database migrations"):
        print("\nFailed to run migrations.")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("Setup completed successfully!")
    print("="*60)
    print("\nNext steps:")
    print("1. Create a superuser: python manage.py createsuperuser")
    print("2. Run the server: python manage.py runserver")
    print("3. Access the app at: http://127.0.0.1:8000/")
    print("4. Access admin at: http://127.0.0.1:8000/admin/")
    print("\n")

if __name__ == "__main__":
    main()


