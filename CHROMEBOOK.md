# Galactic AI on Chromebook

## Requirements
- Chromebook with **Linux (Crostini)** enabled
- At least 4GB RAM (8GB recommended)
- 2GB free storage

## Enable Linux on Chromebook
1. Open **Settings**
2. Go to **Advanced** → **Developers**
3. Click **Turn on** next to "Linux development environment"
4. Follow the setup wizard (creates a Debian Linux container)

## Installation

### Option 1: Auto-Install (Recommended)
```bash
# Download and extract Galactic AI
tar -xzf Galactic-AI-v0.6.0-linux.tar.gz
cd Galactic-AI

# Run the install script
chmod +x install-chromebook.sh
./install-chromebook.sh
```

### Option 2: Manual Install
```bash
# Extract
tar -xzf Galactic-AI-v0.6.0-linux.tar.gz
cd Galactic-AI

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

## Running Galactic AI
```bash
# Activate virtual environment
source venv/bin/activate

# Start Galactic AI
python galactic_core_v2.py
```

## Access Points
- **Control Deck:** http://127.0.0.1:17789
- **Telegram Bot:** Configure in config.yaml

## First-Time Setup
1. Edit `config.yaml` with your API keys
2. Add Telegram bot token (from @BotFather)
3. Run Galactic AI
4. Open Control Deck in Chrome browser

## Tips
- Keep the Linux terminal open while running
- Use `Ctrl+C` to stop Galactic AI
- Virtual environment (`venv`) keeps dependencies isolated
- Update packages: `pip install --upgrade -r requirements.txt`

## Troubleshooting

### "Python not found"
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

### "Permission denied" on install script
```bash
chmod +x install-chromebook.sh
```

### Playwright browser install fails
```bash
playwright install chromium --with-deps
```

### Out of storage
```bash
# Clean pip cache
pip cache purge

# Remove unused Linux packages
sudo apt autoremove
```

## Performance Notes
- ARM Chromebooks (some models) may have limited package compatibility
- x86_64 Chromebooks (most Intel/AMD models) work best
- Close Chrome tabs when running to free RAM
- Consider using a swap file if RAM is limited

---

**Need help?** Open an issue on GitHub with your Chromebook model and error messages.
