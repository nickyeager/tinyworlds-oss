#!/bin/bash
# Start both backend and frontend development servers
# Usage: ./scripts/start_dev.sh

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Clear inherited proxy settings so local dev services talk directly to localhost.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

# Load Node.js version manager (nvm, fnm, or volta)
if [ -s "$HOME/.nvm/nvm.sh" ]; then
    export NVM_DIR="$HOME/.nvm"
    source "$NVM_DIR/nvm.sh"
elif [ -s "$HOME/.fnm/fnm" ]; then
    eval "$(~/.fnm/fnm env)"
elif [ -s "$HOME/.volta/bin/volta" ]; then
    export VOLTA_HOME="$HOME/.volta"
    export PATH="$VOLTA_HOME/bin:$PATH"
fi

# Ensure common paths are available (for homebrew, local bins, etc.)
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

# Store PIDs for cleanup
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo -e "\n${YELLOW}Shutting down servers...${NC}"

    # Kill backend and its children
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo -e "${YELLOW}Stopping backend (PID: $BACKEND_PID)${NC}"
        kill "$BACKEND_PID" 2>/dev/null || true
    fi

    # Kill frontend and its children
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo -e "${YELLOW}Stopping frontend (PID: $FRONTEND_PID)${NC}"
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi

    # Kill any remaining background jobs
    jobs -p 2>/dev/null | xargs kill 2>/dev/null || true

    # Clean up any orphaned processes on our ports
    sleep 1
    lsof -ti :8001 2>/dev/null | xargs kill 2>/dev/null || true
    lsof -ti :3000 2>/dev/null | xargs kill 2>/dev/null || true

    echo -e "${GREEN}Servers stopped.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  TinyWorlds Development Server${NC}"
echo -e "${BLUE}================================================${NC}\n"

# Check for virtual environment - create if missing
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}Virtual environment created${NC}"
fi

# Activate virtual environment
source .venv/bin/activate

# Install/upgrade Python dependencies
echo -e "${YELLOW}Checking Python dependencies...${NC}"
if [ ! -f ".venv/.deps_installed" ] || [ "requirements.txt" -nt ".venv/.deps_installed" ]; then
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    touch .venv/.deps_installed
    echo -e "${GREEN}Python dependencies installed${NC}"
fi

# Check for .env - create from example if missing
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo -e "${YELLOW}Creating .env from .env.example...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}Please edit .env to add your API keys${NC}"
    else
        echo -e "${RED}Error: .env file not found and no .env.example to copy!${NC}"
        exit 1
    fi
fi

# Detect package manager (pnpm preferred, npm fallback)
if command -v pnpm &> /dev/null; then
    PKG_MGR="pnpm"
elif command -v npm &> /dev/null; then
    PKG_MGR="npm"
else
    echo -e "${RED}Error: Neither pnpm nor npm found. Please install Node.js${NC}"
    exit 1
fi
echo -e "${GREEN}Using package manager: $PKG_MGR${NC}"

# Check for frontend dependencies
if [ ! -d "web/node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    (cd web && $PKG_MGR install)
fi

# Create data directory
mkdir -p data

# Run database migrations
echo -e "${YELLOW}Running database migrations...${NC}"
alembic upgrade head 2>/dev/null || echo -e "${YELLOW}Migrations skipped (may already be up to date)${NC}"

echo -e "\n${GREEN}Starting servers...${NC}\n"

# Start backend
echo -e "${GREEN}[Backend]${NC} Starting on http://localhost:8001"
echo -e "${GREEN}[Backend]${NC} API docs: http://localhost:8001/docs"
uvicorn src.api.main:app --reload --port 8001 2>&1 | sed 's/^/[Backend] /' &
BACKEND_PID=$!

# Give backend a moment to start
sleep 2

# Start frontend
echo -e "${GREEN}[Frontend]${NC} Starting on http://localhost:3000"
(cd web && $PKG_MGR run dev 2>&1 | sed 's/^/[Frontend] /') &
FRONTEND_PID=$!

echo -e "\n${BLUE}================================================${NC}"
echo -e "${GREEN}  Backend:  ${NC}http://localhost:8001"
echo -e "${GREEN}  Frontend: ${NC}http://localhost:3000"
echo -e "${GREEN}  API Docs: ${NC}http://localhost:8001/docs"
echo -e "${BLUE}================================================${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop both servers${NC}\n"

# Wait for either process to exit
wait -n $BACKEND_PID $FRONTEND_PID 2>/dev/null || true

# If we get here, one process died - check which and report
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo -e "${RED}Backend server stopped unexpectedly${NC}"
fi
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo -e "${RED}Frontend server stopped unexpectedly${NC}"
fi

# Cleanup will be called by trap
