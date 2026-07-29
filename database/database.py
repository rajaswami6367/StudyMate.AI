import sqlite3

def init_db():
    # Database connect ya create kar rahe hain
    conn = sqlite3.connect('database/studymate.db')
    cursor = conn.cursor()
    
    # Users table bana rahe hain agar pehle se nahi hai toh
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database aur Users table successfully ban gayi hai! 🎉")

if __name__ == "__main__":
    init_db()