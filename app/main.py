from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
import os, psycopg, jwt
from psycopg.rows import dict_row
from passlib.context import CryptContext
from datetime import datetime, timedelta

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
ALGO = "HS256"

pwd_cxt = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="users/login")

app = FastAPI()

def get_conn():
    return psycopg.connect(DATABASE_URL, autocommit=True, row_factory=psycopg.rows.dict_row)

def hash_pwd(pwd): return pwd_cxt.hash(pwd)
def verify_pwd(plain, hashed): return pwd_cxt.verify(plain, hashed)
def create_token(data):
    return jwt.encode({**data, "exp": datetime.utcnow() + timedelta(minutes=30)}, SECRET_KEY, algorithm=ALGO)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGO])
        return int(payload.get("sub"))
    except: raise HTTPException(401, "Invalid token")

def get_current_admin(user_id: int = Depends(get_current_user)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT role FROM customers WHERE customer_id = %s", (user_id,))
        if not (user := cur.fetchone()) or user["role"] != "admin":
            raise HTTPException(403, "Admin privileges required")
    return user_id

@app.get("/")
def get_root():
    return { "msg": "Clothing Store v0.1" }

# POST /users (Register)
@app.post("/users", status_code=201)
def register(data: dict):
    first, last, email, pwd = data.get("first_name"), data.get("last_name"), data.get("email"), data.get("password")
    if not all([first, last, email, pwd]): raise HTTPException(400, "Missing fields")
    
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO customers (first_name, last_name, email, password_hash) VALUES (%s, %s, %s, %s) RETURNING customer_id",
                (first, last, email, hash_pwd(pwd))
            )
            return {"customer_id": cur.fetchone()["customer_id"], "msg": "Registered"}
        except psycopg.errors.UniqueViolation: raise HTTPException(400, "Email exists")

# POST /users/login
@app.post("/users/login")
def login(data: dict):
    email, pwd = data.get("email"), data.get("password")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT customer_id, password_hash FROM customers WHERE email = %s", (email,))
        if not (user := cur.fetchone()) or not verify_pwd(pwd, user["password_hash"]):
            raise HTTPException(401, "Invalid credentials")
        return {"access_token": create_token({"sub": str(user["customer_id"])}), "token_type": "bearer"}

# DELETE /users/{id} (Admin only)
@app.delete("/users/{user_id}", status_code=200)
def delete_user(user_id: int, admin_id: int = Depends(get_current_admin)):
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("DELETE FROM customers WHERE customer_id = %s RETURNING customer_id", (user_id,))
            if not cur.fetchone(): raise HTTPException(404, "User not found")
            return {"msg": "User deleted"}
        except psycopg.errors.ForeignKeyViolation:
            raise HTTPException(400, "Cannot delete user with existing orders")

# GET /categories 
@app.get("/categories")
def get_categories():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT category_id, name FROM categories ORDER BY category_id;")
        return cur.fetchall()

# GET /categories/{id}
@app.get("/categories/{category_id}")
def get_category(category_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT category_id, name FROM categories WHERE category_id = %s;", (category_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Category not found")
        return row

# POST /categories (Admin only)
@app.post("/categories", status_code=201)
def create_category(data: dict, admin_id: int = Depends(get_current_admin)):
    name = data.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name'")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("INSERT INTO categories (name) VALUES (%s) RETURNING category_id, name;", (name,))
            return cur.fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(400, "Category already exists")

# PUT /categories/{id} (Admin only)
@app.put("/categories/{category_id}")
def update_category(category_id: int, data: dict, admin_id: int = Depends(get_current_admin)):
    name = data.get("name")
    if not name: raise HTTPException(400, "Missing 'name'")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("UPDATE categories SET name = %s WHERE category_id = %s RETURNING category_id, name", (name, category_id))
            if not (cat := cur.fetchone()): raise HTTPException(404, "Category not found")
            return cat
        except psycopg.errors.UniqueViolation:
            raise HTTPException(400, "Category name already exists")

# DELETE /categories/{id} (Admin only)
@app.delete("/categories/{category_id}", status_code=200)
def delete_category(category_id: int, admin_id: int = Depends(get_current_admin)):
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("DELETE FROM categories WHERE category_id = %s RETURNING category_id", (category_id,))
            if not cur.fetchone(): raise HTTPException(404, "Category not found")
            return {"msg": "Category deleted"}
        except psycopg.errors.ForeignKeyViolation:
            raise HTTPException(400, "Cannot delete category containing products")

# GET /products
@app.get("/products")
def get_products():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT p.product_id, p.name, c.name as category_name, p.price, p.stock 
            FROM products p 
            JOIN categories c ON p.category_id = c.category_id
            ORDER BY p.product_id;
        """)
        return cur.fetchall()

# POST /products (Admin only)
@app.post("/products", status_code=201)
def create_product(data: dict, admin_id: int = Depends(get_current_admin)):
    cat_id, name, price, stock = data.get("category_id"), data.get("name"), data.get("price"), data.get("stock", 0)
    if not all([cat_id, name, price]): raise HTTPException(400, "Missing fields")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO products (category_id, name, price, stock) VALUES (%s, %s, %s, %s) RETURNING product_id, name, price, stock",
                (cat_id, name, price, stock)
            )
            return cur.fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(400, "Product already exists")

# PUT /products/{id} (Admin only)
@app.put("/products/{product_id}")
def update_product(product_id: int, data: dict, admin_id: int = Depends(get_current_admin)):
    # Allow partial updates
    fields = {k: v for k, v in data.items() if k in ["category_id", "name", "price", "stock"]}
    if not fields: raise HTTPException(400, "No valid fields to update")
    
    set_clause = ", ".join([f"{k} = %s" for k in fields.keys()])
    values = list(fields.values()) + [product_id]
    
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(f"UPDATE products SET {set_clause} WHERE product_id = %s RETURNING product_id, name, price, stock", values)
            if not (p := cur.fetchone()): raise HTTPException(404, "Product not found")
            return p
        except psycopg.errors.UniqueViolation:
            raise HTTPException(400, "Product name already exists")

# DELETE /products/{id} (Admin only)
@app.delete("/products/{product_id}", status_code=200)
def delete_product(product_id: int, admin_id: int = Depends(get_current_admin)):
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("DELETE FROM products WHERE product_id = %s RETURNING product_id", (product_id,))
            if not cur.fetchone(): raise HTTPException(404, "Product not found")
            return {"msg": "Product deleted"}
        except psycopg.errors.ForeignKeyViolation:
            raise HTTPException(400, "Cannot delete product associated with orders")

# POST /orders
@app.post("/orders", status_code=201)
def create_order(data: dict, user_id: int = Depends(get_current_user)):
    product_id, quantity = data.get("product_id"), data.get("quantity", 1)
    if not product_id: raise HTTPException(400, "Missing product_id")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, price, stock FROM products WHERE product_id = %s", (product_id,))
        if not (p := cur.fetchone()): raise HTTPException(404, "Product not found")
        if p["stock"] < quantity: raise HTTPException(400, "Not enough stock")

        with conn.transaction():
            cur.execute("INSERT INTO orders (customer_id) VALUES (%s) RETURNING order_id", (user_id,))
            order_id = cur.fetchone()["order_id"]
            cur.execute("INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)", (order_id, product_id, quantity))
            cur.execute("UPDATE products SET stock = stock - %s WHERE product_id = %s", (quantity, product_id))

    return {
        "order_id": order_id, "status": "created", "product_name": p["name"],
        "price_per_unit": p["price"], "quantity": quantity, "total_price": p["price"] * quantity
    }

# GET /orders (Protected)
@app.get("/orders")
def get_orders(user_id: int = Depends(get_current_user)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT o.order_id, o.order_date, SUM(oi.quantity * p.price) as total_amount 
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE o.customer_id = %s
            GROUP BY o.order_id, o.order_date
            ORDER BY o.order_date DESC
        """, (user_id,))
        return cur.fetchall()

# GET /statistics/users
@app.get("/statistics/users")
def get_user_stats(admin_id: int = Depends(get_current_admin)):
    # Return: List of {customer_id, email, total_orders, total_spent}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT 
                c.customer_id, 
                c.email, 
                COUNT(DISTINCT o.order_id) as total_orders, 
                SUM(oi.quantity * p.price) as total_spent
            FROM customers c
            JOIN orders o ON c.customer_id = o.customer_id
            JOIN order_items oi ON o.order_id = oi.order_id
            JOIN products p ON oi.product_id = p.product_id
            GROUP BY c.customer_id, c.email
            ORDER BY total_spent DESC;
        """)
        return cur.fetchall()

# GET /statistics/products
@app.get("/statistics/products")
def get_product_stats(admin_id: int = Depends(get_current_admin)):
    # Return: List of {product_id, name, total_sold, total_revenue}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT 
                p.product_id, 
                p.name, 
                COUNT(oi.order_item_id) as times_ordered, 
                SUM(oi.quantity) as total_units_sold, 
                SUM(oi.quantity * p.price) as total_revenue
            FROM products p
            JOIN order_items oi ON p.product_id = oi.product_id
            GROUP BY p.product_id, p.name
            ORDER BY total_revenue DESC;
        """)
        return cur.fetchall()