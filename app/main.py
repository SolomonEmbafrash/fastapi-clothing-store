from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator

import jwt
import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, EmailStr, Field

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
ALGORITHM = "HS256"

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it to your .env file or environment.")

app = FastAPI(title="FastAPI Clothing Store", version="1.0.0")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")


# ---------- Database ----------
def get_conn() -> Generator[psycopg.Connection, None, None]:
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


# ---------- Password hashing ----------
def hash_password(password: str, iterations: int = 100_000) -> str:
    salt = os.urandom(16)
    derived_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{base64.urlsafe_b64encode(salt).decode()}$"
        f"{base64.urlsafe_b64encode(derived_key).decode()}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_str, salt_b64, hash_b64 = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected_hash = base64.urlsafe_b64decode(hash_b64.encode())
        actual_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return hmac.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


# ---------- Auth helpers ----------
def create_access_token(user_id: int, role: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "exp": expires_at}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    conn: psycopg.Connection = Depends(get_conn),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT customer_id, first_name, last_name, email, role
            FROM customers
            WHERE customer_id = %s
            """,
            (user_id,),
        )
        user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_current_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user


# ---------- Pydantic models ----------
class MessageResponse(BaseModel):
    message: str


class UserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    customer_id: int
    first_name: str
    last_name: str
    email: EmailStr
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CategoryOut(BaseModel):
    category_id: int
    name: str


class ProductCreate(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=150)
    price: Decimal = Field(gt=0)
    stock: int = Field(ge=0, default=0)


class ProductUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=150)
    price: Decimal | None = Field(default=None, gt=0)
    stock: int | None = Field(default=None, ge=0)


class ProductOut(BaseModel):
    product_id: int
    category_id: int
    category_name: str
    name: str
    price: Decimal
    stock: int


class OrderCreate(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, default=1)


class OrderCreated(BaseModel):
    order_id: int
    status: str
    product_name: str
    price_per_unit: Decimal
    quantity: int
    total_price: Decimal


class OrderSummary(BaseModel):
    order_id: int
    order_date: datetime
    total_amount: Decimal


class UserStats(BaseModel):
    customer_id: int
    email: EmailStr
    total_orders: int
    total_spent: Decimal


class ProductStats(BaseModel):
    product_id: int
    name: str
    times_ordered: int
    total_units_sold: int
    total_revenue: Decimal


# ---------- Routes ----------
@app.get("/", response_model=dict)
def get_root():
    return {"message": "Clothing Store API is running"}


@app.get("/health", response_model=dict)
def health_check(conn: psycopg.Connection = Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        result = cur.fetchone()
    return {"status": "ok", "database": result["ok"] == 1}


@app.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, conn: psycopg.Connection = Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM customers WHERE email = %s", (payload.email,))
        if cur.fetchone():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists")

        cur.execute(
            """
            INSERT INTO customers (first_name, last_name, email, password_hash, role)
            VALUES (%s, %s, %s, %s, 'customer')
            RETURNING customer_id, first_name, last_name, email, role
            """,
            (
                payload.first_name,
                payload.last_name,
                payload.email,
                hash_password(payload.password),
            ),
        )
        user = cur.fetchone()
        conn.commit()
        return user


@app.post("/users/login", response_model=TokenResponse)
def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT customer_id, email, password_hash, role
            FROM customers
            WHERE email = %s
            """,
            (form_data.username,),
        )
        user = cur.fetchone()

    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = create_access_token(user["customer_id"], user["role"])
    return TokenResponse(access_token=token)


@app.get("/users/me", response_model=UserOut)
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@app.delete("/users/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: int,
    admin_user: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    if user_id == admin_user["customer_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Admin cannot delete themself")

    with conn.cursor() as cur:
        cur.execute("DELETE FROM customers WHERE customer_id = %s RETURNING customer_id", (user_id,))
        deleted = cur.fetchone()
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        conn.commit()
    return MessageResponse(message="User deleted")


@app.get("/categories", response_model=list[CategoryOut])
def get_categories(conn: psycopg.Connection = Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT category_id, name FROM categories ORDER BY category_id")
        return cur.fetchall()


@app.get("/categories/{category_id}", response_model=CategoryOut)
def get_category(category_id: int, conn: psycopg.Connection = Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT category_id, name FROM categories WHERE category_id = %s", (category_id,))
        category = cur.fetchone()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


@app.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    _: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute("SELECT category_id FROM categories WHERE LOWER(name) = LOWER(%s)", (payload.name,))
        if cur.fetchone():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category already exists")

        cur.execute(
            "INSERT INTO categories (name) VALUES (%s) RETURNING category_id, name",
            (payload.name,),
        )
        category = cur.fetchone()
        conn.commit()
        return category


@app.put("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    payload: CategoryCreate,
    _: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE categories SET name = %s WHERE category_id = %s RETURNING category_id, name",
            (payload.name, category_id),
        )
        category = cur.fetchone()
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        conn.commit()
        return category


@app.delete("/categories/{category_id}", response_model=MessageResponse)
def delete_category(
    category_id: int,
    _: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM categories WHERE category_id = %s RETURNING category_id", (category_id,))
        deleted = cur.fetchone()
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        conn.commit()
    return MessageResponse(message="Category deleted")


@app.get("/products", response_model=list[ProductOut])
def get_products(conn: psycopg.Connection = Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.product_id, p.category_id, c.name AS category_name, p.name, p.price, p.stock
            FROM products p
            JOIN categories c ON c.category_id = p.category_id
            ORDER BY p.product_id
            """
        )
        return cur.fetchall()


@app.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    _: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute("SELECT category_id FROM categories WHERE category_id = %s", (payload.category_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

        cur.execute(
            """
            INSERT INTO products (category_id, name, price, stock)
            VALUES (%s, %s, %s, %s)
            RETURNING product_id, category_id, name, price, stock
            """,
            (payload.category_id, payload.name, payload.price, payload.stock),
        )
        product = cur.fetchone()
        conn.commit()

        cur.execute("SELECT name FROM categories WHERE category_id = %s", (product["category_id"],))
        category = cur.fetchone()

    return {**product, "category_name": category["name"]}


@app.put("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    _: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided to update")

    if "category_id" in updates:
        with conn.cursor() as cur:
            cur.execute("SELECT category_id FROM categories WHERE category_id = %s", (updates["category_id"],))
            if not cur.fetchone():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    columns = []
    values = []
    for field_name, value in updates.items():
        columns.append(f"{field_name} = %s")
        values.append(value)
    values.append(product_id)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE products
            SET {', '.join(columns)}
            WHERE product_id = %s
            RETURNING product_id, category_id, name, price, stock
            """,
            values,
        )
        product = cur.fetchone()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        conn.commit()

        cur.execute("SELECT name FROM categories WHERE category_id = %s", (product["category_id"],))
        category = cur.fetchone()

    return {**product, "category_name": category["name"]}


@app.delete("/products/{product_id}", response_model=MessageResponse)
def delete_product(
    product_id: int,
    _: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE product_id = %s RETURNING product_id", (product_id,))
        deleted = cur.fetchone()
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        conn.commit()
    return MessageResponse(message="Product deleted")


@app.post("/orders", response_model=OrderCreated, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    current_user: dict = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT product_id, name, price, stock FROM products WHERE product_id = %s",
            (payload.product_id,),
        )
        product = cur.fetchone()

        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        if product["stock"] < payload.quantity:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough stock")

        try:
            cur.execute(
                "INSERT INTO orders (customer_id) VALUES (%s) RETURNING order_id, order_date",
                (current_user["customer_id"],),
            )
            order = cur.fetchone()
            cur.execute(
                "INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)",
                (order["order_id"], payload.product_id, payload.quantity),
            )
            cur.execute(
                "UPDATE products SET stock = stock - %s WHERE product_id = %s",
                (payload.quantity, payload.product_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    total_price = product["price"] * payload.quantity
    return OrderCreated(
        order_id=order["order_id"],
        status="created",
        product_name=product["name"],
        price_per_unit=product["price"],
        quantity=payload.quantity,
        total_price=total_price,
    )


@app.get("/orders", response_model=list[OrderSummary])
def get_orders(
    current_user: dict = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT o.order_id, o.order_date, SUM(oi.quantity * p.price) AS total_amount
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE o.customer_id = %s
            GROUP BY o.order_id, o.order_date
            ORDER BY o.order_date DESC, o.order_id DESC
            """,
            (current_user["customer_id"],),
        )
        return cur.fetchall()


@app.get("/statistics/users", response_model=list[UserStats])
def get_user_statistics(
    _: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                c.customer_id,
                c.email,
                COUNT(DISTINCT o.order_id) AS total_orders,
                COALESCE(SUM(oi.quantity * p.price), 0) AS total_spent
            FROM customers c
            LEFT JOIN orders o ON o.customer_id = c.customer_id
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN products p ON p.product_id = oi.product_id
            GROUP BY c.customer_id, c.email
            ORDER BY total_spent DESC, c.customer_id ASC
            """
        )
        return cur.fetchall()


@app.get("/statistics/products", response_model=list[ProductStats])
def get_product_statistics(
    _: dict = Depends(get_current_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                p.product_id,
                p.name,
                COUNT(oi.order_item_id) AS times_ordered,
                COALESCE(SUM(oi.quantity), 0) AS total_units_sold,
                COALESCE(SUM(oi.quantity * p.price), 0) AS total_revenue
            FROM products p
            LEFT JOIN order_items oi ON oi.product_id = p.product_id
            GROUP BY p.product_id, p.name
            ORDER BY total_revenue DESC, p.product_id ASC
            """
        )
        return cur.fetchall()
