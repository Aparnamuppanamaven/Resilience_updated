# ⚡ Quick Start - External Access

## Fastest Way (ngrok - 5 minutes):

1. **Install ngrok:**
   - Download: https://ngrok.com/download
   - Extract and add to PATH
   - Sign up: https://dashboard.ngrok.com/signup
   - Get authtoken: https://dashboard.ngrok.com/get-started/your-authtoken
   - Configure: `ngrok config add-authtoken YOUR_TOKEN`

2. **Start Server:**
   ```powershell
   RUN_EXTERNAL.bat
   ```

3. **Start Tunnel (in new terminal):**
   ```powershell
   ngrok http 8080
   ```

4. **Copy the HTTPS URL** from ngrok output - that's your public URL! ✅

---

## Alternative: Port Forwarding

1. **Configure router** to forward port 8080 to your computer
2. **Run:** `RUN_EXTERNAL.bat`
3. **Access:** `http://YOUR_PUBLIC_IP:8080`

See `DEPLOYMENT_GUIDE.md` for detailed instructions.
