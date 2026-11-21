#!/bin/bash
# Start the FastAPI backend server

set -e  # Exit on error

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Clear inherited proxy settings so local API traffic goes directly to localhost.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}Error: Virtual environment not found!${NC}"
    echo -e "${YELLOW}Run setup first: ./scripts/setup_environment.sh${NC}"
    exit 1
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source .venv/bin/activate

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo "Please copy .env.example to .env and configure it:"
    echo "  cp .env.example .env"
    exit 1
fi

# Check if SECRET_KEY is set
if grep -q "your-secret-key-here" .env; then
    echo -e "${YELLOW}Warning: SECRET_KEY not configured in .env${NC}"
    echo "Generate a secure key with: openssl rand -hex 32"
fi

# Create data directory if it doesn't exist
mkdir -p data

# Run database migrations
echo -e "${YELLOW}Running database migrations...${NC}"
alembic upgrade head

# Start the server
echo -e "${GREEN}Starting FastAPI server on http://localhost:8001${NC}"
echo -e "${GREEN}API docs available at http://localhost:8001/docs${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop${NC}\n"
uvicorn src.api.main:app --reload --port 8001
