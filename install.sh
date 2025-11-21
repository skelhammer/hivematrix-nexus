#!/bin/bash
#
# HiveMatrix Nexus - Installation Script
# Handles setup of frontend gateway and UI
#

set -e  # Exit on error

APP_NAME="nexus"
APP_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PARENT_DIR="$(dirname "$APP_DIR")"
HELM_DIR="$PARENT_DIR/hivematrix-helm"

echo "=========================================="
echo "  Installing HiveMatrix Nexus"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Check Python version
echo -e "${YELLOW}Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found${NC}"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo -e "${GREEN}✓ Found Python $PYTHON_VERSION${NC}"
echo ""

# Create virtual environment
echo -e "${YELLOW}Creating virtual environment...${NC}"
if [ -d "pyenv" ]; then
    echo "  Virtual environment already exists"
else
    python3 -m venv pyenv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi
echo ""

# Activate virtual environment
source pyenv/bin/activate

# Upgrade pip
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip > /dev/null 2>&1
echo -e "${GREEN}✓ pip upgraded${NC}"
echo ""

# Install dependencies
if [ -f "requirements.txt" ]; then
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    pip install -r requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
    echo ""
fi

# Create instance directory if needed
if [ ! -d "instance" ]; then
    echo -e "${YELLOW}Creating instance directory...${NC}"
    mkdir -p instance
    echo -e "${GREEN}✓ Instance directory created${NC}"
    echo ""
fi

# === NEXUS-SPECIFIC SETUP ===
echo -e "${YELLOW}Running Nexus-specific setup...${NC}"

# 1. Create .flaskenv configuration
echo "Creating configuration files..."

cat > .flaskenv <<EOF
FLASK_APP=run.py
FLASK_ENV=development
SERVICE_NAME=nexus

# Core Service
CORE_SERVICE_URL=http://localhost:5000

# Keycloak
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=hivematrix
KEYCLOAK_CLIENT_ID=core-client

# Session
SECRET_KEY=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)

# SSL Configuration (disable for self-signed certs)
VERIFY_SSL=False
EOF

echo -e "${GREEN}✓ Configuration files created${NC}"
echo ""

# 2. Create static assets directory
if [ ! -d "static" ]; then
    echo "Creating static assets directory..."
    mkdir -p static/{css,js,images}
    echo -e "${GREEN}✓ Static directories created${NC}"
    echo ""
fi

# 3. Create templates directory
if [ ! -d "templates" ]; then
    echo "Creating templates directory..."
    mkdir -p templates
    echo -e "${GREEN}✓ Templates directory created${NC}"
    echo ""
fi

# 4. Sync configuration from Helm (if Helm is installed)
if [ -d "$HELM_DIR" ] && [ -f "$HELM_DIR/config_manager.py" ]; then
    echo "Syncing configuration from Helm..."
    cd "$HELM_DIR"
    source pyenv/bin/activate 2>/dev/null || true

    # Update Helm's master config with Nexus settings
    python -c "
from config_manager import ConfigManager
cm = ConfigManager()
cm.update_app_config('nexus', {
    'port': 8000,
    'environment': 'development'
})
" 2>/dev/null || true

    cd "$APP_DIR"
    echo -e "${GREEN}✓ Configuration synced${NC}"
    echo ""
fi

echo -e "${GREEN}✓ Nexus-specific setup complete${NC}"
echo ""

echo "=========================================="
echo -e "${GREEN}  Nexus installed successfully!${NC}"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  Port: 8000"
echo "  Core Service: http://localhost:5000"
echo "  Keycloak: http://localhost:8080"
echo ""
echo "Next steps:"
echo "  1. Ensure Core and Keycloak are running"
echo "  2. Start Nexus: python run.py"
echo "  3. Or use Helm to start all services"
echo "  4. Access at: http://localhost:8000"
echo ""
