# FastAPI Clothing Store

A simple clothing store backend built with FastAPI and PostgreSQL.

## What is fixed in this version
- Database schema now matches the API code
- Login and registration work correctly
- Admin authorization works correctly
- Docker Compose now starts both the API and PostgreSQL
- Sample data is included
- `.env.example` is included
- Request validation uses Pydantic models

## Quick local run with Docker

### 1. Copy the environment file
On Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

### 2. Start the project
```powershell
docker compose up --build
```

### 3. Open Swagger UI
Open:
```text
http://localhost:8080/docs
```

## Demo accounts
Admin account from sample data:
- Email: `admin@example.com`
- Password: `admin123`

## Recommended screenshot sequence for your report
1. Project folder opened in VS Code or File Explorer
2. `.env` file created from `.env.example`
3. `docker compose up --build` running successfully
4. `http://localhost:8080/docs` opened in browser
5. `GET /health` returning success
6. `POST /users` creating a normal customer
7. `POST /users/login` logging in as admin
8. Authorize button in Swagger with the bearer token
9. `POST /categories` creating a category as admin
10. `POST /products` creating a product as admin
11. `POST /orders` creating an order as customer
12. `GET /orders` showing the user order list
13. `GET /statistics/users` as admin
14. `GET /statistics/products` as admin

## Reset the database if needed
If you want to start from scratch again:
```powershell
docker compose down -v
docker compose up --build
```

## Optional local migration script
If you already have PostgreSQL running separately, you can also run:
```powershell
python db_migration.py
```
