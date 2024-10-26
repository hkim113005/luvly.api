import sqlite3

db = sqlite3.connect("data.db")

cursor = db.cursor()

if True:
    cursor.execute("DROP TABLE IF EXISTS users")
    cursor.execute("DROP TABLE IF EXISTS users_locations")
    cursor.execute("DROP TABLE IF EXISTS users_matches")
    cursor.execute("DROP TABLE IF EXISTS users_luvs")


create_users = """
CREATE TABLE IF NOT EXISTS users (
user_id CHAR(8) NOT NULL,
email VARCHAR(500),
password_hash TEXT,
PRIMARY KEY (user_id)
)
"""
cursor.execute(create_users)


create_users_locations = """
CREATE TABLE IF NOT EXISTS users_locations (
id TEXT PRIMARY KEY,
user_id CHAR(8) NOT NULL,
latitude REAL NOT NULL,
longitude REAL NOT NULL,
date_time TEXT,
FOREIGN KEY (user_id) REFERENCES users(user_id)
)
"""
cursor.execute(create_users_locations)

create_users_locations_trigger = """
CREATE TRIGGER users_locations_trigger
AFTER INSERT ON users_locations
BEGIN
    UPDATE users_locations SET id = CONCAT(NEW.user_id, '-', NEW.date_time)
    WHERE user_id = NEW.user_id AND date_time = NEW.date_time;
END;
"""
cursor.execute(create_users_locations_trigger)


create_users_matches = """
CREATE TABLE IF NOT EXISTS users_matches (
id INTEGER PRIMARY KEY,
send_id CHAR(8) NOT NULL,
receive_id CHAR(8) NOT NULL,
distance REAL,
date_time TEXT,
FOREIGN KEY (send_id) REFERENCES users(user_id),
FOREIGN KEY (receive_id) REFERENCES users(user_id)
)
"""
cursor.execute(create_users_matches)


create_users_luvs = """
CREATE TABLE IF NOT EXISTS users_luvs (
id INTEGER PRIMARY KEY,
user_id CHAR(8),
luv_id CHAR(8),
date_time TEXT,
FOREIGN KEY (user_id) REFERENCES users(user_id),
FOREIGN KEY (luv_id) REFERENCES users(user_id)
)
"""
cursor.execute(create_users_luvs)


db.commit()

cursor.close()
db.close()