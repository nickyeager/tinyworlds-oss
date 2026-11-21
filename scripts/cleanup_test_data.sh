#!/bin/bash
# Clean up test data and temporary files

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}TinyWorlds - Cleanup Test Data${NC}\n"

# Function to print what's being cleaned
clean_item() {
    echo -e "${YELLOW}▶ $1${NC}"
}

# Clean generated games directories
clean_item "Cleaning generated games..."
if [ -d "generated_games" ]; then
    rm -rf generated_games/*
    echo -e "${GREEN}✓ Cleared generated_games/${NC}"
else
    echo -e "${GREEN}✓ No generated_games directory${NC}"
fi

# Clean test database (optional - uncomment if needed)
# clean_item "Cleaning test database..."
# if [ -f "data/tinyworlds.db" ]; then
#     # Backup first
#     cp data/tinyworlds.db data/tinyworlds.db.backup
#     rm data/tinyworlds.db
#     echo -e "${GREEN}✓ Database backed up and removed${NC}"
#     echo -e "${YELLOW}  Run migrations: alembic upgrade head${NC}"
# fi

# Clean pytest cache
clean_item "Cleaning pytest cache..."
if [ -d ".pytest_cache" ]; then
    rm -rf .pytest_cache
    echo -e "${GREEN}✓ Cleared .pytest_cache${NC}"
else
    echo -e "${GREEN}✓ No pytest cache${NC}"
fi

# Clean __pycache__ directories
clean_item "Cleaning Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo -e "${GREEN}✓ Cleared Python cache${NC}"

# Clean coverage data
clean_item "Cleaning coverage data..."
if [ -d "htmlcov" ]; then
    rm -rf htmlcov
    echo -e "${GREEN}✓ Cleared htmlcov${NC}"
fi
if [ -f ".coverage" ]; then
    rm .coverage
    echo -e "${GREEN}✓ Cleared .coverage${NC}"
fi

# Show what's left
echo -e "\n${BLUE}Current State:${NC}"
echo -e "${YELLOW}Generated Games:${NC}"
ls -la generated_games/ 2>/dev/null || echo "  (empty or doesn't exist)"

echo -e "\n${YELLOW}Database:${NC}"
if [ -f "data/tinyworlds.db" ]; then
    GAME_COUNT=$(sqlite3 data/tinyworlds.db "SELECT COUNT(*) FROM games;" 2>/dev/null || echo "?")
    USER_COUNT=$(sqlite3 data/tinyworlds.db "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "?")
    echo -e "  Users: ${USER_COUNT}"
    echo -e "  Games: ${GAME_COUNT}"
else
    echo "  (no database)"
fi

echo -e "\n${GREEN}✓ Cleanup complete!${NC}\n"
