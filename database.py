import os
import json
import sqlite3
import config

try:
    import mysql.connector as connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False


class SQLiteCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=()):
        # Convert MySQL %s placeholder to SQLite ? placeholder
        query_sql = query.replace('%s', '?')
        # Handle MySQL specific types if any
        try:
            return self._cursor.execute(query_sql, params)
        except sqlite3.Error as e:
            raise RuntimeError(str(e)) from e

    def fetchone(self):
        res = self._cursor.fetchone()
        if res is not None and isinstance(res, sqlite3.Row):
            return dict(res)
        return res

    def fetchall(self):
        res = self._cursor.fetchall()
        if res is not None:
            return [dict(row) if isinstance(row, sqlite3.Row) else row for row in res]
        return res

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def close(self):
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cursor.close()


class SQLiteConnWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, dictionary=False):
        if dictionary:
            self._conn.row_factory = sqlite3.Row
        else:
            self._conn.row_factory = None
        return SQLiteCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_sqlite_db():
    db_path = os.path.join(config.BASE_DIR, 'car_damage_detection.db')
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    
    cursor = conn.cursor()
    
    # Module 1: Users
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        contact_number TEXT,
        address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Module 2: Vehicles & Insurance
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS vehicles (
        vehicle_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        vin_number TEXT NOT NULL UNIQUE,
        car_brand TEXT NOT NULL,
        model TEXT NOT NULL,
        year INTEGER NOT NULL,
        color TEXT,
        insurance_provider TEXT NOT NULL,
        policy_number TEXT NOT NULL,
        coverage_type TEXT NOT NULL,
        expiry_date TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # Car Models Pricing Master Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS car_models (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL,
        model TEXT NOT NULL,
        part TEXT NOT NULL,
        price INTEGER NOT NULL
    )
    ''')

    # Module 6 & Reports Primary Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        report_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        vehicle_id INTEGER NOT NULL,
        total_parts_cost REAL NOT NULL,
        total_labour_cost REAL NOT NULL,
        total_paint_cost REAL NOT NULL,
        tax_amount REAL NOT NULL,
        total_cost REAL NOT NULL,
        repair_time_hours INTEGER NOT NULL,
        severity_level TEXT NOT NULL,
        overall_status TEXT DEFAULT 'Completed',
        pdf_filename TEXT,
        payment_status TEXT DEFAULT 'Unpaid',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
    )
    ''')

    # Column Migration check for reports.payment_status
    cursor.execute("PRAGMA table_info(reports)")
    reports_cols = [col[1] for col in cursor.fetchall()]
    if 'payment_status' not in reports_cols:
        try:
            cursor.execute("ALTER TABLE reports ADD COLUMN payment_status TEXT DEFAULT 'Unpaid'")
        except Exception as e:
            print(f"Error altering reports table for payment_status: {e}")

    # Module: Payments & Transactions
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        report_id TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT NOT NULL,
        transaction_id TEXT NOT NULL UNIQUE,
        payment_status TEXT DEFAULT 'Success',
        card_last4 TEXT,
        upi_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (report_id) REFERENCES reports(report_id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # Module 3: Uploaded Images
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS uploaded_images (
        image_id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id TEXT NOT NULL,
        view_type TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        annotated_filename TEXT NOT NULL,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (report_id) REFERENCES reports(report_id) ON DELETE CASCADE
    )
    ''')

    # Module 4 & 5: Damage Detection & Severity Results
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS damage_detections (
        detection_id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id TEXT NOT NULL,
        image_id INTEGER,
        part_name TEXT NOT NULL,
        damage_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        confidence REAL NOT NULL,
        bbox_json TEXT NOT NULL,
        part_cost REAL NOT NULL,
        FOREIGN KEY (report_id) REFERENCES reports(report_id) ON DELETE CASCADE
    )
    ''')

    # Module: Customer Feedback & Ratings
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS feedback (
        feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        report_id TEXT,
        rating INTEGER NOT NULL,
        category TEXT DEFAULT 'General',
        comments TEXT NOT NULL,
        status TEXT DEFAULT 'New',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (report_id) REFERENCES reports(report_id) ON DELETE SET NULL
    )
    ''')

    # Module: Notifications
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notifications (
        notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        type TEXT DEFAULT 'info',
        link TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    ''')

    # Seed Car Parts Prices from JSON if empty
    cursor.execute("SELECT COUNT(*) FROM car_models")
    if cursor.fetchone()[0] == 0:
        json_path = os.path.join(config.BASE_DIR, 'car_parts_prices.json')
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                car_parts_prices = json.load(f)
            for brand, models in car_parts_prices.items():
                for model, parts in models.items():
                    for part, price in parts.items():
                        cursor.execute(
                            "INSERT INTO car_models (brand, model, part, price) VALUES (?, ?, ?, ?)",
                            (brand, model, part, price)
                        )
            conn.commit()

    # Seed Default Admin Account if not exists
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        import bcrypt
        admin_pass = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO users (name, email, password, role, contact_number, address) VALUES (?, ?, ?, ?, ?, ?)",
            ('System Admin', 'admin@accidentai.com', admin_pass, 'admin', '9999999999', 'Admin Head Office')
        )
        conn.commit()

    # Seed initial Feedback if empty
    cursor.execute("SELECT COUNT(*) FROM feedback")
    if cursor.fetchone()[0] == 0:
        cursor.execute("SELECT user_id FROM users LIMIT 1")
        sample_u = cursor.fetchone()
        u_id = sample_u[0] if sample_u else 1
        cursor.execute(
            '''
            INSERT INTO feedback (user_id, report_id, rating, category, comments, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (u_id, None, 5, 'AI Accuracy', 'Outstanding damage detection accuracy! It flagged hairline cracks and scratches that the insurance surveyor missed. Cost estimation is very close to workshop quotes.', 'New')
        )
        conn.commit()

    # Seed initial Notification if empty
    cursor.execute("SELECT COUNT(*) FROM notifications")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            '''
            INSERT INTO notifications (user_id, title, message, type, link, is_read)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (None, 'Welcome to AccidentAI', 'Automated AI Damage Detection and Cost Estimator is ready. Register your vehicle to begin inspections.', 'info', '/vehicle/register', 0)
        )
        conn.commit()

    return SQLiteConnWrapper(conn)


def get_db_connection():
    if MYSQL_AVAILABLE:
        try:
            conn = connector.connect(
                host=config.MYSQL_HOST,
                user=config.MYSQL_USER,
                password=config.MYSQL_PASSWORD,
                database=config.MYSQL_DB,
                port=config.MYSQL_PORT
            )
            return conn
        except Exception as e:
            print(f"MySQL unavailable ({e}). Falling back to SQLite database.")
    return get_sqlite_db()
