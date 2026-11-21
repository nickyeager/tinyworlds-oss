# TinyWorlds FastAPI Backend

Production-ready FastAPI backend for the TinyWorlds voice-to-game generation platform.

## Features

- **User Authentication**: JWT-based authentication with bcrypt password hashing
- **Game Projects**: CRUD operations for managing user game projects
- **Async Database**: SQLAlchemy 2.0 async with support for SQLite (dev) and PostgreSQL (production)
- **Clean Architecture**: Repository pattern, service layer, and dependency injection
- **Comprehensive Tests**: 100+ test cases covering all layers
- **Database Migrations**: Alembic for schema versioning
- **API Documentation**: Auto-generated OpenAPI docs at `/docs`

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and update:

```bash
cp .env.example .env
```

Generate a secret key:

```bash
openssl rand -hex 32
```

Update `.env`:

```bash
SECRET_KEY=your-generated-secret-key
DATABASE_URL=sqlite+aiosqlite:///./data/tinyworlds.db
```

### 3. Run Database Migrations

```bash
# Create initial migration
alembic revision --autogenerate -m "Initial migration"

# Apply migrations
alembic upgrade head
```

### 4. Start the Server

```bash
# Development server with auto-reload
uvicorn src.api.main:app --reload --port 8000

# Production
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

### 5. Test the API

Visit [http://localhost:8000/docs](http://localhost:8000/docs) for interactive API documentation.

## API Endpoints

### Authentication

- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - Login and get JWT token
- `GET /api/v1/auth/me` - Get current user info

### Game Projects

- `POST /api/v1/projects` - Create new project
- `GET /api/v1/projects` - List user's projects
- `GET /api/v1/projects/{id}` - Get project details
- `PATCH /api/v1/projects/{id}` - Update project
- `DELETE /api/v1/projects/{id}` - Delete project

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=src/api --cov-report=html

# Run specific test file
pytest tests/api/test_auth.py

# Run specific test
pytest tests/api/test_auth.py::TestUserRegistration::test_register_new_user
```

## Project Structure

```
src/api/
├── main.py                  # FastAPI app entry point
├── dependencies.py          # Shared dependencies
├── core/
│   ├── config.py           # Settings management
│   ├── database.py         # Database configuration
│   └── security.py         # Auth utilities
├── models/                  # SQLAlchemy models
│   ├── user.py
│   └── game_project.py
├── schemas/                 # Pydantic schemas
│   ├── user.py
│   ├── auth.py
│   └── game_project.py
├── repositories/            # Data access layer
│   ├── base_repository.py
│   ├── user_repository.py
│   └── project_repository.py
├── services/                # Business logic
│   ├── auth_service.py
│   └── project_service.py
└── routes/                  # API endpoints
    ├── auth.py
    └── projects.py
```

## Architecture

The API follows a clean layered architecture:

1. **Routes**: Handle HTTP requests/responses, authentication
2. **Services**: Business logic and orchestration
3. **Repositories**: Database operations and queries
4. **Models**: SQLAlchemy database models
5. **Schemas**: Pydantic request/response validation

This structure makes the code:
- Easy to test (each layer is isolated)
- Easy to extend (add new features without touching existing code)
- Easy to maintain (clear separation of concerns)

## Database Migrations

### Create a Migration

After modifying models:

```bash
alembic revision --autogenerate -m "Description of changes"
```

### Apply Migrations

```bash
# Upgrade to latest
alembic upgrade head

# Upgrade one version
alembic upgrade +1

# Downgrade one version
alembic downgrade -1
```

### View Migration History

```bash
alembic history
alembic current
```

## Switching to PostgreSQL

When ready to deploy:

1. Install PostgreSQL and create database:

```bash
createdb tinyworlds
```

2. Update `.env`:

```bash
DATABASE_URL=postgresql+asyncpg://user:password@localhost/tinyworlds
```

3. Run migrations:

```bash
alembic upgrade head
```

No code changes needed!


## Authentication Flow

1. User registers: `POST /api/v1/auth/register`
2. User logs in: `POST /api/v1/auth/login` → receives JWT token
3. Frontend stores token (localStorage or memory)
4. Frontend includes token in requests: `Authorization: Bearer <token>`
5. Backend validates token and extracts user info

## Security Best Practices

- Passwords hashed with bcrypt
- JWT tokens expire after 30 minutes (configurable)
- CORS configured for frontend origins
- User can only access their own projects
- SQL injection prevented by SQLAlchemy parameterization

## Common Tasks

### Create a new user programmatically

```python
from src.api.services.auth_service import AuthService
from src.api.schemas.user import UserCreate

auth_service = AuthService()
user = await auth_service.create_user(
    db,
    UserCreate(email="user@example.com", password="password123")
)
```

### Query projects

```python
from src.api.repositories.project_repository import ProjectRepository

repo = ProjectRepository()
projects = await repo.get_by_user(db, user_id=1, skip=0, limit=10)
```

## Troubleshooting

### "No module named 'src'"

Make sure you're running commands from the project root:

```bash
cd /path/to/tinyworlds
python -m pytest
```

### Database locked (SQLite)

SQLite doesn't handle concurrent writes well. For production, use PostgreSQL.

### Import errors in tests

Ensure pytest is installed and you have `__init__.py` files in all directories.

## Development

### Adding a new endpoint

1. Add schema in `schemas/`
2. Add repository methods in `repositories/`
3. Add service methods in `services/`
4. Add route in `routes/`
5. Include router in `main.py`
6. Write tests in `tests/api/`

### Adding a new model

1. Create model in `models/`
2. Import in `models/__init__.py`
3. Create schemas in `schemas/`
4. Create repository in `repositories/`
5. Generate migration: `alembic revision --autogenerate`
6. Apply migration: `alembic upgrade head`

## License

MIT
