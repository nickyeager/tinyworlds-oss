#!/bin/bash
# Setup script for TinyWorlds development environment
# This script sets up the Python environment and installs all dependencies

set -e  # Exit on error

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TinyWorlds - Environment Setup${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Check Python version
echo -e "${YELLOW}▶ Checking Python version...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.12"

if python3 -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)"; then
    echo -e "${GREEN}✓ Python ${PYTHON_VERSION} found${NC}"
else
    echo -e "${RED}✗ Python 3.12+ required, found ${PYTHON_VERSION}${NC}"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo -e "\n${YELLOW}▶ Creating virtual environment...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "\n${GREEN}✓ Virtual environment already exists${NC}"
fi

# Activate virtual environment
echo -e "\n${YELLOW}▶ Activating virtual environment...${NC}"
source .venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"

# Upgrade pip
echo -e "\n${YELLOW}▶ Upgrading pip...${NC}"
pip install --upgrade pip > /dev/null 2>&1
echo -e "${GREEN}✓ pip upgraded to $(pip --version | awk '{print $2}')${NC}"

# Install dependencies
echo -e "\n${YELLOW}▶ Installing dependencies from requirements.txt...${NC}"
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
else
    echo -e "${RED}✗ requirements.txt not found${NC}"
    exit 1
fi

# Setup .env file
echo -e "\n${YELLOW}▶ Checking .env configuration...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}⚠ .env not found, copying from .env.example${NC}"
        cp .env.example .env
        echo -e "${GREEN}✓ .env created from .env.example${NC}"
        echo -e "${YELLOW}⚠ Please update .env with your actual configuration${NC}"
    else
        echo -e "${RED}✗ Neither .env nor .env.example found${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ .env file exists${NC}"
fi

# Check SECRET_KEY
if grep -q "your-secret-key-here" .env 2>/dev/null; then
    echo -e "${YELLOW}⚠ SECRET_KEY not configured${NC}"
    echo -e "${YELLOW}  Generate one with: openssl rand -hex 32${NC}"
fi

# Create data directory
echo -e "\n${YELLOW}▶ Creating data directory...${NC}"
mkdir -p data
echo -e "${GREEN}✓ Data directory ready${NC}"

# Run database migrations
echo -e "\n${YELLOW}▶ Running database migrations...${NC}"
if alembic current > /dev/null 2>&1; then
    CURRENT_REVISION=$(alembic current 2>/dev/null | awk '{print $1}')
    if [ "$CURRENT_REVISION" = "003" ]; then
        echo -e "${GREEN}✓ Database already at latest migration (003)${NC}"
    else
        alembic upgrade head
        echo -e "${GREEN}✓ Database migrations applied${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Running migrations for the first time...${NC}"
    alembic upgrade head
    echo -e "${GREEN}✓ Database migrations applied${NC}"
fi

# Verify installation
echo -e "\n${YELLOW}▶ Verifying installation...${NC}"

# Check key imports
python3 -c "
from src.api.models import Game, GameVersion, User
from src.api.repositories import GameRepository
from src.api.core.db_types import UUID, JSON
print('✓ All imports successful')
" 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Installation verified${NC}"
else
    echo -e "${RED}✗ Import verification failed${NC}"
    exit 1
fi

# Summary
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}✓ Environment Setup Complete${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo "Setup Summary:"
echo "  ✓ Python ${PYTHON_VERSION}"
echo "  ✓ Virtual environment: .venv"
echo "  ✓ Dependencies installed"
echo "  ✓ Database migrations: 003"
echo "  ✓ Data directory created"

echo -e "\nNext Steps:"
echo "  1. Activate environment: source .venv/bin/activate"
echo "  2. Configure .env with your settings"
echo "  3. Start API: ./scripts/start_api.sh"
echo "  4. Run tests: ./scripts/run_e2e_tests.sh"

echo -e "\n${GREEN}Ready to start developing!${NC}\n"
