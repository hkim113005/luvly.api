from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import mysql.connector
import resend
import os
import random
import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from geopy.distance import geodesic

import firebase_admin
from firebase_admin import credentials
from firebase_admin import messaging


app = FastAPI()


server_key = 'luvly-9-firebase-adminsdk-anmuf-e5f094432b.json'

cred = credentials.Certificate(server_key)
firebase_admin.initialize_app(cred)


DISTANCE = 20
COOLDOWN_TIME = 5

# Initialize Resend
resend.api_key = "re_HscFn33y_89LC49ZHxNpMjDRRqvgeynmY"


class User(BaseModel):
    user_id: str = None
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
    user_id: str = None

class VerifyUser(BaseModel):
    user_id: str = None
    email: str
    password: str
    verification_code: str

class Token(BaseModel):
    user_id: str = None
    token: str


def get_db():
    db = mysql.connector.connect(
        host="luvlydatabase.c5wy4cuwaohj.us-west-1.rds.amazonaws.com",
        user="admin",
        password="hyungjae1130",
        database="luvly"
    )
    db.start_transaction(isolation_level="READ COMMITTED")
    return db



def send_verification_email(email: str, verification_code: str):
    try:
        email_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #333333; text-align: center; margin-bottom: 20px;">Email Verification</h2>
            <p style="color: #666666; font-size: 16px; line-height: 1.5; margin-bottom: 20px;">Thank you for registering! To complete your account verification, please enter this code in the app:</p>
            <div style="background-color: #f5f5f5; padding: 15px; border-radius: 4px; text-align: center; margin-bottom: 20px;">
                <span style="font-size: 24px; font-weight: bold; color: #333333; letter-spacing: 2px;">{verification_code}</span>
            </div>
            <p style="color: #666666; font-size: 14px; text-align: center;">If you didn't request this verification, please ignore this email.</p>
        </div>
        """
        resend.Emails.send({
            "from": "verification@luvly-app.org",
            "to": email,
            "subject": "Please verify your Luvly account",
            "html": email_body
        })
        return True
    except Exception as e:
        print(f"Failed to send verification email: {e}")
        return False


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/login", response_model=Response)
async def login(user: User):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT user_id, password_hash FROM users WHERE email = '{user.email}'")
    user_ = cursor.fetchone()


    if not user_:
        return {"status": "401", "user_id": None}
    if not check_password_hash(user_[1], user.password):
        return {"status": "402", "user_id": None}
    #check if user is verified
    cursor.execute(f"SELECT * FROM verification WHERE email = '{user.email}'")
    is_verified = cursor.fetchone()[3]
    
    cursor.close()
    db.close()
    if not is_verified:
        return {"status": "405", "user_id": None}  # Email not verified
    
    return {"status": "200", "user_id": user_[0]}


@app.post("/register", response_model=Response)
async def register(user: User):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT user_id FROM users WHERE email = '{user.email}'")
    user_ = cursor.fetchone()

    if user_:
        cursor.close()
        db.close()
        return {"status": "403"}

    # Generate verification code
    verification_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    
    
    #store user in verification database
    cursor.execute(f"""INSERT INTO verification (email, verification_code, is_verified) 
                      VALUES ('{user.email}', '{verification_code}', FALSE)""")
    
    db.commit()
    cursor.close()
    db.close()

    # Send verification email
    if send_verification_email(user.email, verification_code):
        return {"status": "200"}
    else:
        return {"status": "406"}  # Failed to send verification email


@app.post("/verify_email", response_model=Response)
async def verify_email(verifyUser: VerifyUser):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT * FROM verification WHERE email = '{verifyUser.email}'")
    user = cursor.fetchone()

    if not user:
        cursor.close()
        db.close()
        return {"status": "401"}  # User not found

    if user[3]:  # Already verified
        cursor.close()
        db.close()
        return {"status": "407"}

    if user[2] != verifyUser.verification_code:  # Check verification code
        cursor.close()
        db.close()
        return {"status": "408"}  # Invalid verification code

    cursor.execute("SELECT COUNT(user_id) FROM users")
    user_id = cursor.fetchone()[0]
    if not user_id:
        user_id = 0

    # Update user as verified and update user_id
    cursor.execute(f"UPDATE verification SET is_verified = TRUE WHERE email = '{verifyUser.email}'")
    # Store user
    cursor.execute(f"""INSERT INTO users (user_id, email, password_hash) 
                       VALUES(LPAD('{user_id}', 8, '0'), '{verifyUser.email}', '{generate_password_hash(verifyUser.password)}');""")
    
    db.commit()
    cursor.close()
    db.close()

    return {"status": "200", "user_id": user_id}


@app.get("/get_matches/{user_id}/{cur_datetime}", response_model=list[Match])
async def get_matches(user_id: str, cur_datetime: str):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"""
                   SELECT send_id, receive_id, distance, date_time
                   FROM users_matches
                   WHERE receive_id = '{user_id}'
                   """)
    
    matches = cursor.fetchall()
    valid_matches = []
    for match in matches:
        datetime_format = "%Y-%m-%d %H:%M:%S"
        match_time = datetime.datetime.strptime(match[3], datetime_format)
        cur_time = datetime.datetime.strptime(cur_datetime, datetime_format)
        if ((cur_time - match_time).total_seconds() < COOLDOWN_TIME):
            valid_matches.append(match)

    cursor.close()
    db.close()
    
    return [{"send_id": match[0], "receive_id": match[1], "distance": match[2], "date_time": match[3]} for match in valid_matches]


@app.post("/update_luv", response_model=Response)
async def update_luv(user_luv: UserLuv):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT user_id FROM users WHERE email = '{user_luv.luv_email}'")
    luv = cursor.fetchone()
    if not luv:
        cursor.close()
        db.close()
        return {"status": "403"}
    
    # Update users_luvs    
    cursor.execute(f"""INSERT INTO users_luvs (user_id, luv_id, date_time) 
                       VALUES('{user_luv.user_id}', '{luv[0]}', '{user_luv.date_time}');""")
    
    # Update users_matches
    # DELETE cursor.execute(f"DELETE FROM users_matches WHERE send_id = '{user_luv.user_id}'")

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
    receive_user = cursor.fetchone()
    if receive_user:
        receive_id, receive_latitude, receive_longitude = receive_user

        distance = geodesic((send_latitude, send_longitude), (receive_latitude, receive_longitude)).meters

        if distance < DISTANCE:
            cursor.execute(f"""
                            SELECT * 
                            FROM users_matches
                            WHERE send_id = '{send_id}' AND receive_id = '{receive_id}'
                            """)
            most_recent_match = cursor.fetchone()
            
            cursor.execute(f"""
                            INSERT INTO users_matches (send_id, receive_id, distance, date_time) 
                            VALUES('{send_id}', '{receive_id}', {distance}, '{user_luv.date_time}') 
                            ON DUPLICATE KEY UPDATE date_time = '{user_luv.date_time}'
                            """)
            
            datetime_format = "%Y-%m-%d %H:%M:%S"
            recent_datetime = datetime.datetime.strptime(most_recent_match[4], datetime_format)
            new_datetime = datetime.datetime.strptime(user_luv.date_time, datetime_format)
            if (new_datetime - recent_datetime).total_seconds() > COOLDOWN_TIME:
                send_notification(receive_id)

    db.commit()
    cursor.close()
    db.close()

    return {"status": "200"}


@app.post("/update_location", response_model=Response)
async def update_location(location: Location):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"SELECT COUNT(user_id) FROM users_locations WHERE user_id = '{location.user_id}'")
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
                    INSERT INTO users_locations (user_id, latitude, longitude, date_time) 
                    VALUES ('{location.user_id}', {location.latitude}, {location.longitude}, '{location.date_time}')
                    ON DUPLICATE KEY UPDATE latitude = {location.latitude}, longitude = {location.longitude}
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
    # DELETE cursor.execute(f"DELETE FROM users_matches WHERE receive_id = '{location.user_id}'")

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
                                SELECT * 
                                FROM users_matches
                                WHERE send_id = '{send_id}' AND receive_id = '{location.user_id}'
                                """)
                most_recent_match = cursor.fetchone()

                cursor.execute(f"""
                                INSERT INTO users_matches (send_id, receive_id, distance, date_time)
                                VALUES ('{send_id}', '{location.user_id}', {distance}, '{location.date_time}')
                                ON DUPLICATE KEY UPDATE date_time = '{location.date_time}'
                                """)
                
                datetime_format = "%Y-%m-%d %H:%M:%S"
                recent_datetime = datetime.datetime.strptime(most_recent_match[4], datetime_format)
                new_datetime = datetime.datetime.strptime(location.date_time, datetime_format)
                print((new_datetime - recent_datetime).total_seconds())
                if (new_datetime - recent_datetime).total_seconds() > COOLDOWN_TIME:
                    print("SENT TO " + location.user_id)
                    send_notification(location.user_id)
                
    # Delete matches where current user is sender
    # DELETE cursor.execute(f"DELETE FROM users_matches WHERE send_id = '{location.user_id}'")

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
        receive_user = cursor.fetchone()
        if receive_user:
            receive_id, receive_latitude, receive_longitude = receive_user

            distance = geodesic((location.latitude, location.longitude), (receive_latitude, receive_longitude)).meters

            if distance < DISTANCE:
                cursor.execute(f"""
                                SELECT * 
                                FROM users_matches
                                WHERE send_id = '{location.user_id}' AND receive_id = '{receive_id}'
                                """)
                most_recent_match = cursor.fetchone()

                cursor.execute(f"""
                                INSERT INTO users_matches (send_id, receive_id, distance, date_time) 
                                VALUES('{location.user_id}', '{receive_id}', {distance}, '{location.date_time}')
                                ON DUPLICATE KEY UPDATE date_time = '{location.date_time}'
                                """)
                
                datetime_format = "%Y-%m-%d %H:%M:%S"
                recent_datetime = datetime.datetime.strptime(most_recent_match[4], datetime_format)
                new_datetime = datetime.datetime.strptime(location.date_time, datetime_format)
                print((new_datetime - recent_datetime).total_seconds())
                if (new_datetime - recent_datetime).total_seconds() > COOLDOWN_TIME:
                    print("SENT TO " + receive_id)
                    send_notification(receive_id)

    db.commit()
    cursor.close()
    db.close()

    return {"status": "200"}


@app.post("/update_token", response_model=Response)
async def update_fcm_token(token: Token):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(f"""INSERT INTO users_tokens (user_id, token)
                   VALUES('{token.user_id}', '{token.token}')""")
    
    db.commit()
    cursor.close()
    db.close()

    return {"status": "200"}


def send_notification(user_id):
    db = get_db()
    cursor = db.cursor()

    # This registration token comes from the client FCM SDKs.
    # registration_token = 'dFDbUh5Ub0lXiMo2cJcrGZ:APA91bET5SrrUPt6HEWmhIuwB-dA6aU464h5QoDFf4IwedFDCDyAag6tAW0xbsa5pZmnJUSmbkO99gr_fBkE5rEB6c7ucmqV40skslOXoMTAzuOqCp5uhUU'
    cursor.execute(f"SELECT token FROM users_tokens WHERE user_id = '{user_id}'")
    registration_token = cursor.fetchone()[0]

    # See documentation on defining a message payload.
    message = messaging.Message(
        notification=messaging.Notification(
            title='Test',
            body='Test Body'
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    sound="default"  # Plays the default notification sound on iOS
                )
            )
        ),
        token=registration_token,
    )
    # Send a message to the device corresponding to the provided
    # registration token.
    response = messaging.send(message)
    # Response is a message ID string.
    print('Successfully sent message:', response)


# send_notification("00000003")