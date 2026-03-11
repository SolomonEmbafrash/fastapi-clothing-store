from fastapi import FastAPI, HTTPException
import os, psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()
print(load_dotenv())

print("Solomon")


DATABASE_URL = os.getenv("DATABASE_URL")
print(DATABASE_URL)
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
    
app = FastAPI()
print(app)

def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(DATABASE_URL, autocommit=True, row_factory=psycopg.rows.dict_row)

@app.get("/")
def get_root():
    return { "msg": "Clothing Store v0.1" }

# GET /productDetails 
@app.get("/productDetails")
def get_productDetails():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT p.name AS product_name,c.name AS category_name,p.price,p.stock  FROM products p INNER JOIN categories c ON p.category_id = c.category_id;")
            return cur.fetchall()
    except Exception as e:
        print(e)
        raise


class OrderCreate(BaseModel):
    user_id: int
    product_id: int
    quantity: int
#----------------------------
@app.post("/orders")
def post_orders(order: OrderCreate):
    try:
          with get_conn() as conn:
                with conn.cursor() as cur:
                  # 1️⃣ Fetch product and lock row
                    cur.execute("""
                        SELECT name, price, stock
                        FROM products
                        WHERE product_id = %s
                        FOR UPDATE
                    """, (order.product_id,))
                    product = cur.fetchone()  

                    if not product:
                        raise HTTPException(status_code=404, detail="Product not found")

                    if product["stock"] < order.quantity:
                        raise HTTPException(status_code=400, detail="Not enough stock")

                    total_price = product["price"] * order.quantity 
                    print('viansh')
                    print(total_price)  

                    # 2️⃣ Create order
                    cur.execute("""
                                INSERT INTO orders (user_id, total_price)
                                VALUES (%s, %s)
                                RETURNING order_id""", (order.user_id, total_price))
                    order_id = cur.fetchone()["order_id"]

                    # 3️⃣ Create order item
                    cur.execute("""
                                INSERT INTO order_items (order_id, product_id, quantity, price)
                                VALUES (%s, %s, %s, %s)
                                """, (
                                order_id,
                                order.product_id,
                                order.quantity,
                                product["price"]
                                ))
                    # 4️⃣ Decrease stock
                    cur.execute("""
                                UPDATE products
                                SET stock = stock - %s
                                WHERE product_id = %s
                                """, (order.quantity, order.product_id))
                conn.commit()
                return {
                        "order_id": order_id,
                        "user_id": order.user_id,
                        "order_item": {
                            "product_name": product["name"],
                            "price": product["price"],
                            "quantity": order.quantity,
                            "total_price": total_price
                        }
                    }
    except HTTPException: 
        raise
    except Exception as e:
        print("Order error:", e)
        raise HTTPException(
            status_code=500,
        )

        #----------------------------

@app.get("/statistics/users")
def user_statistics():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
                    select c.customer_id,
            c.first_name||last_name as customer_name,
            COUNT(o.order_id) AS total_orders,
            SUM(o.total_price) AS total_money_spent,
            AVG(o.total_price) AS avg_order_value
        FROM customers c
        INNER JOIN orders o 
            ON c.customer_id = o.user_id
        GROUP BY c.customer_id,customer_name
        ORDER BY total_money_spent DESC;

        """)
        return cur.fetchall()
    
@app.get("/statistics/products")
def product_statistics():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
                p.product_id,
                p.name AS product_name,
                COUNT(DISTINCT oi.order_id) AS order_count,
                SUM(oi.quantity) AS units_sold,
                SUM(oi.quantity * oi.price) AS turnover,
                ROUND(AVG(oi.price), 2) AS avg_selling_price
            FROM products p
            INNER JOIN order_items oi ON p.product_id = oi.product_id
            INNER JOIN orders o ON oi.order_id = o.order_id
            GROUP BY p.product_id, p.name
            ORDER BY turnover DESC;
        """)
        return cur.fetchall()