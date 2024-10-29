from fastapi import FastAPI
from pydantic import BaseModel

import mysql.connector

from werkzeug.security import check_password_hash, generate_password_hash

from geopy.distance import geodesic


app = FastAPI()
DISTANCE = 20


class User(BaseModel):
    user_id: str | None = None
    email: str
    password: str

class Match(BaseModel):
    send_id: str
    receive_id: str
    distance: float
    date_time: str

class UserLuv(BaseModel):
    user_id: str
    luv_email: str
    date_time: str

class Location(BaseModel):
    user_id: str
    latitude: str
    longitude: str
    date_time: str

class Response(BaseModel):
    status: str
    user_id: str | None = None


def get_db():
    return mysql.connector.connect(
        host="luvlydatabase.c5wy4cuwaohj.us-west-1.rds.amazonaws.com",
        user="admin",
        password="hyungjae1130",
        database="luvly"
    )


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/login", response_model=Response)
async def login(user: User):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT * FROM users WHERE email = '{user.email}'")
    user_ = cursor.fetchone()

    cursor.close()
    db.close()

    if not user_:
        return {"status": "401", "user_id": None}
    if not check_password_hash(user_[2], user.password):
        return {"status": "402", "user_id": None}
    
    return {"status": "200", "user_id": user_[0]}


@app.post("/register", response_model=Response)
async def register(user: User):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT * FROM users WHERE email = '{user.email}'")
    user_ = cursor.fetchone()

    if user_:
        cursor.close()
        db.close()
        return {"status": "403"}
    
    cursor.execute("SELECT COUNT(*) FROM users")
    user_id = cursor.fetchone()[0]
    if not user_id:
        user_id = 0

    cursor.execute(f"""INSERT INTO users (user_id, email, password_hash) 
                       VALUES(LPAD('{user_id}', 8, '0'), '{user.email}', '{generate_password_hash(user.password)}');""")
    
    db.commit()
    cursor.close()
    db.close()
    
    return {"status": "200", "user_id": str(user_id).zfill(8)}


@app.get("/get_matches/{user_id}", response_model=list[Match])
async def get_matches(user_id: str):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"""
                   SELECT send_id, receive_id, distance, date_time
                   FROM users_matches
                   WHERE receive_id = '{user_id}'
                   """)
    
    matches = cursor.fetchall()

    cursor.close()
    db.close()
    
    return [{"send_id": match[0], "receive_id": match[1], "distance": match[2], "date_time": match[3]} for match in matches]


@app.post("/update_luv", response_model=Response)
async def update_luv(user_luv: UserLuv):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT * FROM users WHERE email = '{user_luv.luv_email}'")
    luv = cursor.fetchone()
    if not luv:
        cursor.close()
        db.close()
        return {"status": "403"}
    
    # Update users_luvs
    cursor.execute(f"""INSERT IGNORE INTO users_luvs (user_id, luv_id, date_time) 
                       VALUES('{user_luv.user_id}', '{luv[0]}', '{user_luv.date_time}');""")
    
    # Update users_matches
    cursor.execute(f"DELETE FROM users_matches WHERE send_id = '{user_luv.user_id}'")

    cursor.execute(f"""
                    SELECT user_id, latitude, longitude
                    FROM users_locations
                    WHERE user_id = '{user_luv.user_id}'
                    ORDER BY date_time DESC
                    LIMIT 1;
                    """)
    send_id, send_latitude, send_longitude = cursor.fetchone()

    cursor.execute(f"""
                    SELECT user_id, latitude, longitude
                    FROM users_locations
                    WHERE user_id = '{luv[0]}'
                    ORDER BY date_time DESC
                    LIMIT 1;
                    """)
    receive_id, receive_latitude, receive_longitude = cursor.fetchone()

    distance = geodesic((send_latitude, send_longitude), (receive_latitude, receive_longitude)).meters

    if distance < DISTANCE:
        cursor.execute(f"INSERT IGNORE INTO users_matches (send_id, receive_id, distance, date_time) VALUES('{send_id}', '{receive_id}', {distance}, '{user_luv.date_time}')")

    db.commit()
    cursor.close()
    db.close()

    return {"status": "200"}


@app.post("/update_location", response_model=Response)
async def update_location(location: Location):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM users_locations WHERE user_id = '{location.user_id}'")
    count = cursor.fetchone()[0]

    # Deleting oldest location
    if count >= 30:
        cursor.execute(f"""
                       DELETE FROM users_locations
                       WHERE user_id = '{location.user_id}'
                       ORDER BY date_time ASC
                       LIMIT 1;
                       """)
        
    # Update Location
    cursor.execute(f"""
                    INSERT IGNORE INTO users_locations (user_id, latitude, longitude, date_time) 
                    VALUES ('{location.user_id}', {location.latitude}, {location.longitude}, '{location.date_time}')
                    """)
    
    # Getting most recent location of all users 
    cursor.execute("""
                   SELECT user_id, latitude, longitude
                   FROM users_locations AS ul
                   WHERE date_time = (
                   SELECT MAX(date_time)
                   FROM users_locations
                   WHERE user_id = ul.user_id
                   )
                   """)
    all_users = cursor.fetchall()

    # Delete existing matches for the current user 
    cursor.execute(f"DELETE FROM users_matches WHERE receive_id = '{location.user_id}'")

    for send_user in all_users:
        send_id, send_latitude, send_longitude = send_user
        if send_id == location.user_id:
            continue  # Skip calculating distance to self
        
        distance = geodesic((location.latitude, location.longitude), (send_latitude, send_longitude)).meters
        
        # Store the calculated distance in the users_matches table if less than 20 meters and the other user loves this user
        if distance < DISTANCE:
            cursor.execute(f"""
                            SELECT *
                            FROM users_luvs
                            WHERE user_id = '{send_id}'
                            ORDER BY date_time DESC
                            LIMIT 1;
                            """)
            
            match = cursor.fetchone()
            if match and match[2] == location.user_id:
                cursor.execute(f"""
                                INSERT IGNORE INTO users_matches (send_id, receive_id, distance, date_time)
                                VALUES ('{send_id}', '{location.user_id}', {distance}, '{location.date_time}')
                                """)
                
    # Delete matches where current user is sender
    cursor.execute(f"DELETE FROM users_matches WHERE send_id = '{location.user_id}'")

    cursor.execute(f"""
                    SELECT *
                    FROM users_luvs
                    WHERE user_id = '{location.user_id}'
                    ORDER BY date_time DESC
                    LIMIT 1;
                    """)
    match = cursor.fetchone()
    if match and match[2] != location.user_id:
        receive_id = match[2]

        cursor.execute(f"""
                        SELECT user_id, latitude, longitude
                        FROM users_locations
                        WHERE user_id = '{receive_id}'
                        ORDER BY date_time DESC
                        LIMIT 1;
                        """)
        receive_id, receive_latitude, receive_longitude = cursor.fetchone()

        distance = geodesic((location.latitude, location.longitude), (receive_latitude, receive_longitude)).meters

        if distance < DISTANCE:
            cursor.execute(f"INSERT IGNORE INTO users_matches (send_id, receive_id, distance, date_time) VALUES('{location.user_id}', '{receive_id}', {distance}, '{location.date_time}')")

    db.commit()
    cursor.close()
    db.close()

    return {"status": "200"}