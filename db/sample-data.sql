INSERT INTO categories (name)
VALUES ('T-Shirts'), ('Shoes'), ('Jackets')
ON CONFLICT (name) DO NOTHING;

INSERT INTO products (category_id, name, price, stock)
VALUES
    ((SELECT category_id FROM categories WHERE name = 'T-Shirts'), 'Basic White T-Shirt', 19.99, 25),
    ((SELECT category_id FROM categories WHERE name = 'Shoes'), 'Running Sneakers', 79.90, 10),
    ((SELECT category_id FROM categories WHERE name = 'Jackets'), 'Denim Jacket', 59.50, 8)
ON CONFLICT (name) DO NOTHING;

INSERT INTO customers (first_name, last_name, email, password_hash, role)
VALUES (
    'Admin',
    'User',
    'admin@example.com',
    'pbkdf2_sha256$100000$0hwwC7rKOXWsidCVDMIgdQ==$MdR02wkMVIIFI47ludrLG3Mc-hhHHdAeTgntdlZ7Ues=',
    'admin'
)
ON CONFLICT (email) DO NOTHING;
