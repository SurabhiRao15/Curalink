from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit
import uuid
import mysql.connector
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from datetime import date, datetime, timedelta
import requests
from flask_mail import Mail, Message
import threading
import subprocess
import time
import os

# ---------------- APP SETUP ----------------
app = Flask(__name__)
app.secret_key = "supersecretkey"

# ---------------- MYSQL (mysql.connector) ----------------
# Adjust credentials if needed
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="surabhi",
    database="curalink",
    auth_plugin="mysql_native_password"
)

def get_cursor(dict=False):
    """
    Helper to create cursors:
      - get_cursor(dict=True) -> returns dictionary rows (like DictCursor)
      - get_cursor(dict=False) -> returns tuple rows (default)
    """
    return db.cursor(dictionary=dict)

# SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Mail config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'swararao119@gmail.com'
app.config['MAIL_PASSWORD'] = 'zora rtwg atvd bopb'
mail = Mail(app)


def start_ngrok():
    """Start ngrok and display public URL"""
    def run_ngrok():
        time.sleep(3)  # Wait for Flask to start
        
        try:
            # Start ngrok process
            process = subprocess.Popen(
                ["ngrok", "http", "5000"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for ngrok to start
            time.sleep(5)
            
            # Get ngrok public URL
            try:
                response = requests.get("http://localhost:4040/api/tunnels", timeout=10)
                if response.status_code == 200:
                    tunnels = response.json()['tunnels']
                    for tunnel in tunnels:
                        if tunnel['proto'] == 'https':
                            public_url = tunnel['public_url']
                            print(f"\n" + "="*50)
                            print(f" NGROK PUBLIC URL: {public_url}")
                            print(f" Share this URL for multi-device testing!")
                            print("="*50 + "\n")
                            break
            except:
                print(" Manually check ngrok at: http://localhost:4040")
                
        except Exception as e:
            print(f" Ngrok error: {e}")
            print(" Make sure ngrok is installed: https://ngrok.com/download")

    thread = threading.Thread(target=run_ngrok, daemon=True)
    thread.start()

# ---------------- HELPER FUNCTIONS ----------------

def create_video_call():
    """Create Jitsi Meet video call - FREE & WORKS IMMEDIATELY"""
    try:
        # Create a unique room name
        room_id = uuid.uuid4().hex[:16]
        meet_link = f"https://meet.jit.si/CuraLinkConsultation-{room_id}"
        
        print(f"Jitsi Meet room created: {meet_link}")
        return meet_link
        
    except Exception as e:
        print(f"Error creating Jitsi room: {e}")
        return None

def send_accept_email(patient_email, meet_link, appointment_date, appointment_time):
    try:
        msg = Message(
            subject="Appointment Accepted - CuraLink",
            sender=app.config['MAIL_USERNAME'],
            recipients=[patient_email]
        )
        msg.body = f"""
Dear Patient,

Your appointment has been accepted by the doctor.

📅 Date: {appointment_date}
⏰ Time: {appointment_time}
🔗 Meeting Link: {meet_link}

Please join the meeting on time.

Best regards,
CuraLink Team
"""
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending acceptance email: {e}")
        return False

def send_reject_email(patient_email, appointment_date, appointment_time):
    try:
        msg = Message(
            subject="Appointment Update - CuraLink",
            sender=app.config['MAIL_USERNAME'],
            recipients=[patient_email]
        )
        msg.body = f"""
Dear Patient,

We regret to inform you that your appointment scheduled for:
📅 {appointment_date} at ⏰ {appointment_time}

has been canceled by the doctor. Please book another appointment.

We apologize for any inconvenience.

Best regards,
CuraLink Team
"""
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending rejection email: {e}")
        return False

def send_prescription_email(patient_email, doctor_name, prescription_text):
    try:
        msg = Message(
            subject="Your Prescription - CuraLink",
            sender=app.config['MAIL_USERNAME'],
            recipients=[patient_email]
        )
        
        msg.html = f"""
        <html>
            <body>
                <h2>Your Prescription - CuraLink</h2>
                <p>Dear Patient,</p>
                <p>You have received a new prescription from <strong>Dr. {doctor_name}</strong>.</p>
                <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #007bff;">
                    <h3> Prescription Details:</h3>
                    <p style="white-space: pre-line;">{prescription_text}</p>
                </div>
                <p>Please follow the dosage instructions carefully and contact your doctor if you have any questions.</p>
                <br>
                <p>Best regards,<br>CuraLink Team</p>
            </body>
        </html>
        """
        
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending prescription email: {e}")
        return False

@app.route("/update_location", methods=["POST"])
def update_location():
    data = request.get_json()
    lat = data.get("lat")
    lon = data.get("lon")
    if lat and lon:
        session["lat"] = lat
        session["lon"] = lon
        return jsonify({"status": "success", "lat": lat, "lon": lon})
    return jsonify({"status": "error", "message": "No coordinates received"}), 400


# Fetch pharmacies near saved location
@app.route("/nearby_pharmacies")
def nearby_pharmacies():
    lat = session.get("lat")
    lon = session.get("lon")

    if not lat or not lon:
        return jsonify([])  # no location stored yet

    # Overpass query (5km radius)
    query = f"""
    [out:json];
    node["amenity"="pharmacy"](around:5000,{lat},{lon});
    out;
    """
    url = "https://overpass-api.de/api/interpreter"
    response = requests.post(url, data={"data": query})

    if response.status_code != 200:
        return jsonify([])

    data = response.json()
    stores = []
    for element in data.get("elements", []):
        name = element.get("tags", {}).get("name", "Unnamed Pharmacy")
        store_lat = element.get("lat")
        store_lon = element.get("lon")
        google_link = f"https://www.google.com/maps?q={store_lat},{store_lon}"
        stores.append({
            "name": name,
            "lat": store_lat,
            "lon": store_lon,
            "link": google_link
        })

    return jsonify(stores)


@app.route("/request_appointment", methods=["POST"])
def request_appointment():
    if "loggedin" not in session or session["role"] != "patient":
        flash("Please login as patient to request appointment.", "danger")
        return redirect(url_for("login"))
    
    try:
        doctor_id = request.form.get("doctor_id")
        patient_id = session.get("id")
        appointment_date = request.form.get("date")
        appointment_time = request.form.get("time")
        symptoms = request.form.get("symptoms", "")
        
        # Validation
        if not all([doctor_id, patient_id, appointment_date, appointment_time]):
            flash("All fields are required.", "danger")
            return redirect(url_for("patient_home", section='doctors'))
        
        # Validate date is not in the past
        appointment_datetime = datetime.strptime(f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M")
        if appointment_datetime < datetime.now():
            flash("Appointment date/time cannot be in the past.", "danger")
            return redirect(url_for("patient_home", section='doctors'))
        
        cursor = get_cursor(dict=False)
        
        # ✅ NEW: Check if patient already has an accepted appointment with any doctor
        cursor.execute("""
            SELECT COUNT(*) as active_count 
            FROM appointments 
            WHERE patient_id = %s AND status = 'Accepted'
        """, (patient_id,))
        
        active_appointments = cursor.fetchone()[0]
        
        if active_appointments > 0:
            cursor.close()
            flash("You already have an accepted appointment with a doctor. Please complete that before booking a new one.", "warning")
            return redirect(url_for("patient_home", section='doctors'))
        
        # Check if doctor exists
        cursor.execute("SELECT name FROM doctors WHERE id = %s", (doctor_id,))
        doctor = cursor.fetchone()
        if not doctor:
            cursor.close()
            flash("Doctor not found.", "danger")
            return redirect(url_for("patient_home", section='doctors'))
        
        # Insert appointment
        cursor.execute("""
            INSERT INTO appointments (doctor_id, patient_id, appointment_date, appointment_time, symptoms, status) 
            VALUES (%s, %s, %s, %s, %s, 'Pending')
        """, (doctor_id, patient_id, appointment_date, appointment_time, symptoms))
        
        db.commit()
        cursor.close()
        
        flash("Appointment request sent successfully!", "success")
        return redirect(url_for("patient_home", section='appointments'))
        
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for("patient_home", section='doctors'))

# ---------------- AUTH ----------------

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form["role"].lower()
        email = request.form.get("email")
        password = request.form["password"]
        cursor = get_cursor(dict=True)

        if role == "patient":
            cursor.execute("SELECT * FROM patients WHERE email=%s AND password=%s", (email, password))
        elif role == "doctor":
            cursor.execute("SELECT * FROM doctors WHERE email=%s AND password=%s", (email, password))
        elif role == "store":
            cursor.execute("SELECT * FROM store WHERE email=%s AND password=%s", (email, password))
        else:
            cursor.close()
            flash("Invalid role selected.", "danger")
            return redirect(url_for("login"))

        user = cursor.fetchone()
        cursor.close()

        if user:
            session["loggedin"] = True
            session["role"] = role
            session["id"] = user["id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            if role == "store":
                return redirect(url_for("home"))
            else:
                return redirect(url_for(f"{role}_home"))
        else:
            flash("Invalid credentials. Please try again.", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- SIGNUP ROUTES ----------------

@app.route("/signup_patient", methods=["GET", "POST"])
def signup_patient():
    if request.method == "POST":
        name = request.form["name"]
        age = request.form["age"]
        dob = request.form["dob"]
        email = request.form["email"]
        phone_number = request.form["phone_number"]
        password = request.form["password"]

        cursor = get_cursor(dict=False)
        cursor.execute("""
            INSERT INTO patients (name, age, dob, email, phone_number, password)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (name, age, dob, email, phone_number, password))
        db.commit()
        cursor.close()

        flash("Signup successful! You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup_patient.html")

@app.route("/signup_doctor", methods=["GET", "POST"])
def signup_doctor():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone_number"]
        password = request.form["password"]

        cursor = get_cursor(dict=False)
        cursor.execute("SELECT * FROM doctors WHERE email=%s", (email,))
        existing_user = cursor.fetchone()

        if existing_user:
            cursor.close()
            flash("Doctor already registered! Please log in.", "warning")
            return redirect(url_for("login"))

        cursor.execute("""
            INSERT INTO doctors (name, email, phone_number, password)
            VALUES (%s, %s, %s, %s)
        """, (name, email, phone, password))
        db.commit()
        cursor.close()

        flash("Doctor signup successful! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("signup_doctor.html")

@app.route("/signup_store", methods=["GET", "POST"])
def signup_store():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        cursor = get_cursor(dict=False)
        cursor.execute("SELECT * FROM store WHERE email=%s", (email,))
        existing_user = cursor.fetchone()

        if existing_user:
            cursor.close()
            flash("Store already registered! Please log in.", "warning")
            return redirect(url_for("login"))

        cursor.execute("""
            INSERT INTO store (name, email, password)
            VALUES (%s, %s, %s)
        """, (name, email, password))
        db.commit()
        cursor.close()

        flash("Store signup successful! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("signup_store.html")


# ---------------- PATIENT ROUTES ----------------

@app.route("/patient_home", methods=["GET", "POST"])
def patient_home():
    cursor = get_cursor(dict=False)
    patient_name = session.get("username", "Patient")
    
    # ✅ Get message from query parameter if it exists
    message = request.args.get('message', '')
    
    # Medicine list for Buy Medicine section
    cursor.execute("SELECT name, stock, expiry, store FROM medicines")
    medicine_list = []
    for m in cursor.fetchall():
        expiry_date = m[2]
        if isinstance(expiry_date, str):
            expiry_date = datetime.strptime(expiry_date, "%Y-%m-%d").date()
        medicine_list.append({
            "name": m[0],
            "stock": m[1],
            "expiry": expiry_date,
            "store": m[3]
        })
    # ---------------- SEARCH MEDICINE ----------------
    results = []
    if request.method == "POST" and request.form.get("section") == "home":
        medicine_name = request.form.get("medicine_name")
        cursor.execute("SELECT name, stock, expiry FROM medicines WHERE name LIKE %s", (f"%{medicine_name}%",))
        medicines_from_db = cursor.fetchall()

        for m in medicines_from_db:
            expiry_date = m[2]
            if isinstance(expiry_date, str):
                expiry_date = datetime.strptime(expiry_date, "%Y-%m-%d").date()
            results.append({
                "name": m[0],
                "stock": m[1],
                "expiry": expiry_date,
                "is_expired": expiry_date < date.today()
            })

    # ---------------- ORDERS ----------------
    cursor.execute("""
        SELECT medicine_name, quantity, store, purchased_at 
        FROM purchases 
        WHERE patient_id = %s 
        ORDER BY purchased_at DESC
    """, (session["id"],))
    
    orders = []
    for order in cursor.fetchall():
        orders.append({
            "medicine_name": order[0],
            "quantity": order[1],
            "store": order[2],
            "purchased_at": order[3].strftime("%Y-%m-%d %H:%M") if order[3] else "Unknown"
        })

    # ---------------- CHECK EXPIRY ----------------
    search_query = request.args.get("search", "")
    if search_query:
        cursor.execute("SELECT name, expiry FROM medicines WHERE name LIKE %s", (f"%{search_query}%",))
    else:
        cursor.execute("SELECT name, expiry FROM medicines")
    expiry_list = []
    for m in cursor.fetchall():
        expiry_date = m[1]
        if isinstance(expiry_date, str):
            expiry_date = datetime.strptime(expiry_date, "%Y-%m-%d").date()
        expiry_list.append({
            "name": m[0],
            "expiry": expiry_date,
            "is_expired": expiry_date < date.today()
        })

    # ---------------- DOCTORS ----------------
    cursor.execute("SELECT id, name, email, phone_number FROM doctors")
    rows = cursor.fetchall()

    doctors = []
    for row in rows:
        doctors.append({
            "id": row[0],
            "name": row[1],
            "email": row[2],
            "phone_number": row[3]
        })

    # ✅ FIXED: APPOINTMENTS - Join with doctors table to get doctor names
    cursor.execute("""
        SELECT a.id, d.name as doctor_name, a.appointment_date, a.appointment_time, 
               a.status, a.meet_link, a.symptoms
        FROM appointments a 
        JOIN doctors d ON a.doctor_id = d.id 
        WHERE a.patient_id = %s 
        ORDER BY a.appointment_date DESC, a.appointment_time DESC
    """, (session.get("id"),))
    
    appointments = []
    for app in cursor.fetchall():
        # Handle timedelta for time conversion
        appointment_time = app[3]
        if isinstance(appointment_time, timedelta):
            # Convert timedelta to time string (HH:MM)
            total_seconds = int(appointment_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours:02d}:{minutes:02d}"
        elif appointment_time:
            # It's already a time object
            time_str = appointment_time.strftime("%H:%M")
        else:
            time_str = "N/A"
        
        appointments.append({
            "id": app[0],
            "doctor_name": app[1],
            "date": app[2].strftime("%Y-%m-%d") if app[2] else "N/A",
            "time": time_str,
            "status": app[4],
            "meet_link": app[5],
            "symptoms": app[6]
        })

    # ---------------- DOCTOR ADVICE ----------------
    cursor.execute("""
        SELECT d.name, a.advice, a.created_at 
        FROM advice a 
        JOIN doctors d ON a.doctor_id = d.id 
        WHERE a.patient_email = %s 
        ORDER BY a.created_at DESC
    """, (session.get("email"),))
    advice_records = cursor.fetchall()

    # Convert to list of dictionaries with correct field names
    advice_list = []
    for record in advice_records:
        advice_list.append({
            "doctor_name": record[0],
            "advice": record[1],
            "date": record[2].strftime("%Y-%m-%d %H:%M") if record[2] else "Unknown"
        })

    # DEBUG: Check what we got
    print(f"DEBUG - Patient email: {session.get('email')}")
    print(f"DEBUG - Number of advice records found: {len(advice_list)}")

    if advice_list:
        for advice in advice_list:
            print(f"Doctor: {advice['doctor_name']}, Advice: {advice['advice']}, Date: {advice['date']}")
    else:
        print("No advice records found for this patient")
    
    today = date.today()  # Add this line
    
    # ---------------- NEARBY PHARMACIES ----------------
    lat = session.get("lat")
    lon = session.get("lon")
    nearby_stores = []
    if lat and lon:
        query = f"""
        [out:json];
        node["amenity"="pharmacy"](around:5000,{lat},{lon});
        out;
        """
        try:
            response = requests.post("https://overpass-api.de/api/interpreter", data={"data": query}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for element in data.get("elements", []):
                    name = element.get("tags", {}).get("name", "Unnamed Pharmacy")
                    store_lat = element.get("lat")
                    store_lon = element.get("lon")
                    google_link = f"https://www.google.com/maps?q={store_lat},{store_lon}"
                    nearby_stores.append({
                        "name": name,
                        "lat": store_lat,
                        "lon": store_lon,
                        "link": google_link
                    })
        except:
            pass  # fail silently if API fails
    
    # Get active section from query parameters or form
    active_section = request.args.get('section') or request.form.get('section') or 'home'
    
    cursor.close()
    return render_template(
        "patient_home.html",
        patient_name=patient_name,
        results=results,
        orders=orders,
        medicine_list=medicine_list,
        expiry_list=expiry_list,
        doctors=doctors,
        appointments=appointments,
        advice_list=advice_list,
        search_query=search_query,
        nearby_stores=nearby_stores,
        active_section=request.form.get("section") or request.args.get("section"),
        today=today,  # Add this line
        purchase_message=message,  # ✅ Pass the message to template
    )

@app.route("/debug_advice")
def debug_advice():
    if "loggedin" in session and session["role"] == "patient":
        cursor = get_cursor(dict=False)
        
        # Check all advice in database
        cursor.execute("SELECT * FROM advice")
        all_advice = cursor.fetchall()
        print("ALL ADVICE IN DATABASE:")
        for adv in all_advice:
            print(adv)
        
        # Check advice for current patient
        cursor.execute("""
            SELECT a.*, d.name as doctor_name, p.name as patient_name 
            FROM advice a 
            JOIN doctors d ON a.doctor_id = d.id 
            JOIN patients p ON a.patient_email = p.email 
            WHERE a.patient_email = %s
        """, (session.get("email"),))
        patient_advice = cursor.fetchall()
        
        print(f"ADVICE FOR PATIENT {session.get('email')}:")
        for adv in patient_advice:
            print(adv)
        
        cursor.close()
        return f"Check console for debug output. Patient email: {session.get('email')}"
    
    return "Not logged in as patient"

# ---------------- DOCTOR ROUTES ----------------

@app.route("/doctor_home")
def doctor_home():
    if "loggedin" in session and session["role"] == "doctor":
        cursor = get_cursor(dict=True)
        
        # ✅ FIXED: Get appointments with patient information
        cursor.execute("""
            SELECT 
                a.id,
                a.appointment_date,
                a.appointment_time,
                a.status,
                a.meet_link,
                a.symptoms,
                p.name as patient_name,
                p.email as patient_email
            FROM appointments a 
            JOIN patients p ON a.patient_id = p.id 
            WHERE a.doctor_id = %s
            ORDER BY a.appointment_date DESC, a.appointment_time DESC
        """, (session["id"],))
        
        appointments = []
        for app in cursor.fetchall():
            # Handle timedelta for time conversion
            appointment_time = app['appointment_time']
            if isinstance(appointment_time, timedelta):
                total_seconds = int(appointment_time.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                time_str = f"{hours:02d}:{minutes:02d}"
            elif appointment_time:
                time_str = appointment_time.strftime("%H:%M")
            else:
                time_str = "N/A"
            
            appointments.append({
                "id": app['id'],
                "patient_name": app['patient_name'],
                "patient_email": app['patient_email'],
                "appointment_date": app['appointment_date'].strftime("%Y-%m-%d") if app['appointment_date'] else "N/A",
                "appointment_time": time_str,
                "status": app['status'],
                "meet_link": app['meet_link'],
                "symptoms": app['symptoms']
            })

        # ✅ FIXED: Get only patients with accepted appointments with this doctor
        cursor.execute("""
            SELECT DISTINCT p.id, p.name, p.email, p.age, p.phone_number, p.dob
            FROM patients p 
            JOIN appointments a ON p.id = a.patient_id 
            WHERE a.doctor_id = %s AND a.status = 'Accepted'
            ORDER BY p.name
        """, (session["id"],))
        patients1 = cursor.fetchall()

        # Convert to list of dictionaries with proper null handling
        formatted_patients = []
        for patient in patients1:
            patient_dict = {
                "id": patient['id'],
                "name": patient['name'] or "Unknown",
                "email": patient['email'] or "No email",
                "age": patient['age'] or "Not provided",
                "phone_number": patient['phone_number'] or "Not provided",
                "dob": patient['dob'] or "Not provided"
            }
            
            # Handle date of birth properly
            if patient['dob']:
                if hasattr(patient['dob'], 'strftime'):
                    patient_dict['dob'] = patient['dob'].strftime("%Y-%m-%d")
                else:
                    patient_dict['dob'] = str(patient['dob'])
            
            formatted_patients.append(patient_dict)

        patients = formatted_patients

        # ✅ FIXED: Get patients for advice section (only assigned patients)
        cursor.execute("""
            SELECT DISTINCT p.id, p.name, p.email
            FROM patients p 
            JOIN appointments a ON p.id = a.patient_id 
            WHERE a.doctor_id = %s AND a.status = 'Accepted'
            ORDER BY p.name
        """, (session["id"],))
        patients2 = cursor.fetchall()

        # Get meetings for meetings section
        cursor.execute("""
            SELECT m.*, p.name as patient_name 
            FROM meetings m 
            JOIN patients p ON m.patient_id = p.id 
            WHERE m.doctor_id = %s 
            ORDER BY m.created_at DESC LIMIT 5
        """, (session["id"],))
        meetings = cursor.fetchall()
        
        cursor.close()
        
        return render_template(
            "doctor_home.html",
            doctor_name=session["name"],
            patients=patients,
            patients_basic=patients2,
            appointments=appointments,
            meetings=meetings
        )
    return redirect(url_for("login"))

@app.route("/doctor/advice", methods=["POST"])
def doctor_advice():
    if "loggedin" in session and session["role"] == "doctor":
        patient_email = request.form["patient_email"]
        advice = request.form["advice"]
        cursor = get_cursor(dict=False)
        
        try:
            # Insert advice into database
            cursor.execute(
                "INSERT INTO advice (doctor_id, patient_email, advice) VALUES (%s, %s, %s)",
                (session["id"], patient_email, advice)
            )
            db.commit()
            
            # Send prescription email
            email_sent = send_prescription_email(
                patient_email=patient_email,
                doctor_name=session["name"],
                prescription_text=advice
            )
            
            if email_sent:
                flash("Prescription sent successfully and email notification delivered!", "success")
            else:
                flash("Prescription saved but email notification failed.", "warning")
                
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
        finally:
            cursor.close()
            
        return redirect(url_for("doctor_home"))
    return redirect(url_for("login"))

@app.route("/doctor/accept_appointment/<int:appointment_id>", methods=["POST"])
def accept_appointment(appointment_id):
    if not ("loggedin" in session and session["role"] == "doctor"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("login"))

    try:
        cursor = get_cursor(dict=True)
        
        # Get appointment details
        cursor.execute("""
            SELECT a.patient_id, a.appointment_date, a.appointment_time, 
                   p.email, p.name as patient_name, d.email as doctor_email
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN doctors d ON a.doctor_id = d.id
            WHERE a.id = %s AND a.doctor_id = %s AND a.status = 'Pending'
        """, (appointment_id, session["id"]))
        
        appointment = cursor.fetchone()
        if not appointment:
            cursor.close()
            flash("Appointment not found or already processed.", "danger")
            return redirect(url_for("doctor_home"))

        # ✅ NEW: Auto-reject other pending appointments for this patient
        cursor2 = get_cursor(dict=False)
        cursor2.execute("""
            UPDATE appointments 
            SET status = 'Auto-Rejected' 
            WHERE patient_id = %s 
            AND status = 'Pending' 
            AND id != %s
        """, (appointment['patient_id'], appointment_id))
        db.commit()
        cursor2.close()

        # Handle date/time conversion
        appointment_date = appointment['appointment_date']
        appointment_time = appointment['appointment_time']
        
        # Convert to datetime objects
        if isinstance(appointment_time, timedelta):
            total_seconds = int(appointment_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            start_dt = datetime.combine(appointment_date, datetime.min.time()) + appointment_time
        else:
            start_dt = datetime.combine(appointment_date, appointment_time)
        
        end_dt = start_dt + timedelta(minutes=30)
        
        # Create video call
        meet_link = create_video_call()
        
        if not meet_link:
            cursor.close()
            flash("Failed to create video call. Please try again.", "danger")
            return redirect(url_for("doctor_home"))

        # Save to database
        cursor3 = get_cursor(dict=False)
        cursor3.execute(
            "UPDATE appointments SET status=%s, meet_link=%s WHERE id=%s", 
            ("Accepted", meet_link, appointment_id)
        )
        db.commit()
        cursor3.close()
        
        # Format time for email
        appointment_time = appointment['appointment_time']
        if isinstance(appointment_time, timedelta):
            total_seconds = int(appointment_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            appointment_time_str = f"{hours:02d}:{minutes:02d}"
        else:
            appointment_time_str = appointment_time.strftime("%H:%M")

        # Send email
        email_sent = send_accept_email(
            patient_email=appointment['email'],
            meet_link=meet_link,
            appointment_date=appointment['appointment_date'].strftime("%Y-%m-%d"),
            appointment_time=appointment_time_str
        )

        cursor.close()

        if email_sent:
            flash(f"Appointment accepted! Video call link sent to {appointment['patient_name']}. Other pending appointments for this patient were automatically rejected.", "success")
        else:
            flash(f"Appointment accepted but email failed. Video link: {meet_link}. Other pending appointments for this patient were automatically rejected.", "warning")
        
        return redirect(url_for("doctor_home"))
        
    except Exception as e:
        print(f"Error in accept_appointment: {str(e)}")
        flash(f"Error accepting appointment: {str(e)}", "danger")
        return redirect(url_for("doctor_home"))
    
@app.route("/doctor/reject_appointment/<int:appointment_id>", methods=["POST"])
def reject_appointment(appointment_id):
    if not ("loggedin" in session and session["role"] == "doctor"):
        flash("Unauthorized access.", "danger")
        return redirect(url_for("login"))

    try:
        cursor = get_cursor(dict=True)
        cursor.execute("""
            SELECT a.patient_id, a.appointment_date, a.appointment_time, p.email, p.name as patient_name
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            WHERE a.id = %s AND a.doctor_id = %s AND a.status = 'Pending'
        """, (appointment_id, session["id"]))
        
        appointment = cursor.fetchone()
        
        email_sent = False
        if appointment:
            # Format time for email
            appointment_time = appointment['appointment_time']
            if isinstance(appointment_time, timedelta):
                total_seconds = int(appointment_time.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                appointment_time_str = f"{hours:02d}:{minutes:02d}"
            else:
                appointment_time_str = appointment_time.strftime("%H:%M")
                
            # Send rejection email
            email_sent = send_reject_email(
                appointment['email'],
                appointment['appointment_date'].strftime("%Y-%m-%d"),
                appointment_time_str
            )

        # Update appointment status
        cursor2 = get_cursor(dict=False)
        cursor2.execute("UPDATE appointments SET status='Rejected' WHERE id=%s", (appointment_id,))
        db.commit()
        cursor2.close()
        cursor.close()

        if appointment and email_sent:
            flash(f"Appointment rejected and notification sent to {appointment['patient_name']}.", "success")
        elif appointment:
            flash(f"Appointment rejected but email notification failed.", "warning")
        else:
            flash("Appointment processed.", "info")
            
        return redirect(url_for("doctor_home"))
        
    except Exception as e:
        flash(f"Error rejecting appointment: {str(e)}", "danger")
        return redirect(url_for("doctor_home"))

# ---------------- MEETINGS / SOCKET ----------------

@app.route("/create_meeting", methods=["POST"])
def create_meeting():
    if "loggedin" in session and session["role"] == "doctor":
        try:
            patient_email = request.form["patient_email"]
            
            # Validate patient exists
            cursor = get_cursor(dict=True)
            cursor.execute("SELECT name, email FROM patients WHERE email = %s", (patient_email,))
            patient = cursor.fetchone()
            cursor.close()
            
            if not patient:
                flash("Patient not found.", "danger")
                return redirect(url_for("doctor_home"))

            # Create real Google Meet using your existing function
            start_time = datetime.now() + timedelta(minutes=5)  # Meeting starts in 5 minutes
            end_time = start_time + timedelta(minutes=30)  # 30-minute meeting
            
            meet_link = create_video_call() 
            if not meet_link:
                flash("Failed to create Meet. Please try again.", "danger")
                return redirect(url_for("doctor_home"))

            # Store in database
            cursor2 = get_cursor(dict=False)
            cursor2.execute("""
                INSERT INTO meetings (doctor_id, patient_email, meet_link, created_at)
                VALUES (%s, %s, %s, NOW())
            """, (session["id"], patient_email, meet_link))
            db.commit()
            cursor2.close()

            # Send email to patient
            send_meeting_invite_email(patient_email, meet_link, start_time)
            
            flash(f"Meet created for {patient['name']}! Link sent via email.", "success")
            return redirect(url_for("doctor_home"))
            
        except Exception as e:
            flash(f"Error creating meeting: {str(e)}", "danger")
            return redirect(url_for("doctor_home"))
    
    return redirect(url_for("login"))

def send_meeting_invite_email(patient_email, meet_link, meeting_time):
    try:
        msg = Message(
            subject="Teleconsultation Meeting Invitation - CuraLink",
            sender=app.config['MAIL_USERNAME'],
            recipients=[patient_email]
        )
        msg.body = f"""
Dear Patient,

You have been invited to a teleconsultation meeting.

🔗 Meeting Link: {meet_link}
⏰ Scheduled Time: {meeting_time.strftime("%Y-%m-%d %H:%M")}

Please join the meeting using the link above.

Best regards,
CuraLink Team
"""
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending meeting invite: {e}")
        return False
    
@app.route("/doctor/start_meet")
def start_meet():
    if "loggedin" in session and session["role"] == "doctor":
        cursor = get_cursor(dict=True)
        cursor.execute("""
            SELECT m.meet_id, m.meet_link, p.name as patient_name, m.created_at
            FROM meetings m 
            JOIN patients p ON m.patient_id = p.id 
            WHERE m.doctor_id = %s AND m.created_at > DATE_SUB(NOW(), INTERVAL 1 DAY)
            ORDER BY m.created_at DESC
        """, (session["id"],))
        meetings = cursor.fetchall()
        cursor.close()
        
        return render_template("start_meet.html", 
                             doctor_name=session["name"], 
                             meetings=meetings)
    return redirect(url_for("login"))

@app.route("/join_meet/<meet_id>")
def join_meet(meet_id):
    if "loggedin" in session:
        # Verify meeting exists and user has access
        cursor = get_cursor(dict=True)
        cursor.execute("""
            SELECT m.*, d.name as doctor_name, p.name as patient_name
            FROM meetings m
            LEFT JOIN doctors d ON m.doctor_id = d.id
            LEFT JOIN patients p ON m.patient_id = p.id
            WHERE m.meet_id = %s AND (m.doctor_id = %s OR m.patient_id = %s)
        """, (meet_id, session["id"], session["id"]))
        
        meeting = cursor.fetchone()
        cursor.close()
        
        if not meeting:
            flash("Meeting not found or access denied.", "danger")
            return redirect(url_for("patient_home" if session["role"] == "patient" else "doctor_home"))
        
        return render_template("join_meet.html", 
                             meet_id=meet_id, 
                             user_name=session["name"],
                             meeting=meeting)
    return redirect(url_for("login"))

# WebRTC SocketIO Handlers
@socketio.on('join_room')
def handle_join_room(data):
    room = data['room']
    join_room(room)
    emit('user_joined', {'user': data['user'], 'message': 'has joined the room'}, room=room)

@socketio.on('leave_room')
def handle_leave_room(data):
    room = data['room']
    leave_room(room)
    emit('user_left', {'user': data['user'], 'message': 'has left the room'}, room=room)

@socketio.on('signal')
def handle_signal(data):
    # Handle WebRTC signaling
    emit('signal', data, room=data['room'], include_self=False)

# ---------------- RECOMMENDATIONS ----------------

def load_data():
    df = pd.read_csv("Cleaned_Medicine_List_with_Alternatives.csv")
    df.drop_duplicates(subset=['Medicine Name', 'Composition'], inplace=True)
    df.dropna(subset=['Composition'], inplace=True)
    df['Drug Class'] = df['Drug Class'].fillna("Unknown")
    return df


df = load_data()
df['combined_text'] = (
    df['Medicine Name'].astype(str) + " " +
    df['Composition'].astype(str) + " " +
    df['Use Case'].astype(str) + " " +
    df['Type'].astype(str) + " " +
    df['Drug Class'].astype(str)
)

# Create TF-IDF matrix
vectorizer = TfidfVectorizer(stop_words='english')
tfidf_matrix = vectorizer.fit_transform(df['combined_text'])


# -----------------------------
# Suggest alternate medicine
# -----------------------------
def suggest_best_alternate(med_name, df, tfidf_matrix, similarity_threshold=0.3):
    med_name = med_name.strip().lower()
    
    # Find the medicine row
    match = df[df['Medicine Name'].str.lower() == med_name]
    if match.empty:
        return None, f"Medicine '{med_name}' not found!"
    
    idx = match.index[0]

    # Compute cosine similarity
    cosine_sim = cosine_similarity(tfidf_matrix[idx], tfidf_matrix).flatten()
    cosine_sim[idx] = 0  # exclude itself

    best_idx = cosine_sim.argmax()
    best_score = cosine_sim[best_idx]

    if best_score < similarity_threshold:
        return None, f"No highly similar alternative found for '{med_name}' (max similarity {best_score*100:.2f}%)."
    print('**',best_score*100)
    # Prepare result
    if best_score*100>46:
        result = df.iloc[[best_idx]][['Medicine Name', 'Composition', 'Use Case', 'Type', 'Drug Class']].copy()
        result.insert(0, "Similarity (%)", f"{best_score*100:.2f}%")
        return result.to_dict(orient="records")[0], None
    else:
        return None,None

@app.route("/recommend_alternate", methods=["GET", "POST"])
def recommend_alternate():
    medicine = None
    error = None
    medicine_name = None
    
    if request.method == "POST":
        medicine_name = request.form["medicine_name"]
        medicine, error = suggest_best_alternate(medicine_name, df, tfidf_matrix)
    return render_template("recommend.html", medicine=medicine, error=error, medicine_name=medicine_name)

# ---------------- STORE ROUTES ----------------

@app.route("/home")
def home():
    if "loggedin" not in session:
        return redirect(url_for("login"))
    return render_template("home.html", 
                           role=session["role"],
                           name=session.get("name"))



@app.route("/patient/search_medicine", methods=["POST"])
def search_medicine():
    if "loggedin" in session and session["role"] == "patient":
        med_name = request.form["medicine_name"]
        cursor = get_cursor(dict=False)
        cursor.execute("SELECT name, stock, expiry FROM medicines WHERE name LIKE %s", 
                       ("%" + med_name + "%",))
        results = cursor.fetchall()
        cursor.close()

        # Fetch other patient data
        cursor = get_cursor(dict=False)
        cursor.execute("SELECT id, name, email, phone_number FROM doctors")
        doctors = cursor.fetchall()
        cursor.execute("""SELECT u.name AS doctor_name, a.advice, a.created_at
                          FROM advice a JOIN doctors u ON a.doctor_id = u.id
                          WHERE a.patient_email = %s
                          ORDER BY a.created_at DESC""", (session["email"],))
        advice_list = cursor.fetchall()
        cursor.close()

        return render_template(
            "patient_home.html",
            patient_name=session["name"],
            doctors=doctors,
            advice_list=advice_list,
            orders=[],        # fetch if needed
            appointments=[],  # fetch if needed
            results=results,
            active_section="search"
        )
    flash("Unauthorized access.")
    return redirect(url_for("login"))

def get_nearby_pharmacies(lat, lon, radius=5000):
    query = f"""
    [out:json];
    node["amenity"="pharmacy"](around:{radius},{lat},{lon});
    out;
    """
    url = "https://overpass-api.de/api/interpreter"
    response = requests.post(url, data={"data": query})
    stores = []
    if response.status_code == 200:
        data = response.json()
        for element in data.get("elements", []):
            name = element.get("tags", {}).get("name", "Unnamed Pharmacy")
            stores.append(name)
    return stores

@app.route("/patient/buy_medicine", methods=["GET", "POST"])
def buy_medicine():
    if "loggedin" not in session or session["role"] != "patient":
        return redirect(url_for("login"))

    message = ""
    if request.method == "POST":
        medicine_name = request.form.get("medicine_name")
        quantity = int(request.form.get("quantity", 1))
        store = request.form.get("store", "Unknown")

        if not medicine_name:
            message = "Medicine name is required."
        else:
            cursor = get_cursor(dict=False)
            cursor.execute(
                "SELECT id, stock, expiry FROM medicines WHERE name=%s AND store=%s",
                (medicine_name, store)
            )
            medicine = cursor.fetchone()

            if medicine:
                med_id, current_stock, expiry = medicine
                if isinstance(expiry, str):
                    expiry = datetime.strptime(expiry, "%Y-%m-%d").date()

                if expiry < date.today():
                    message = f" {medicine_name} is expired (Expiry: {expiry})."
                elif current_stock >= quantity:
                    new_stock = current_stock - quantity
                    cursor.execute("UPDATE medicines SET stock=%s WHERE id=%s", (new_stock, med_id))

                    cursor.execute("""
                        INSERT INTO purchases (patient_id, medicine_name, quantity, store, purchased_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (session["id"], medicine_name, quantity, store))

                    db.commit()
                    message = f"Purchased {quantity} of {medicine_name} from {store}!"
                else:
                    message = f"Only {current_stock} left for {medicine_name}."
            else:
                # Only insert if medicine_name exists
                cursor.execute("""
                    INSERT INTO purchases (patient_id, medicine_name, quantity, store, purchased_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (session["id"], medicine_name, quantity, store))
                db.commit()
                message = f"Order placed for {medicine_name} at {store}."

            cursor.close()

        # ✅ REDIRECT BACK TO PATIENT HOME WITH BUY SECTION ACTIVE
        return redirect(url_for('patient_home', section='buy', message=message))

    # For GET requests, also redirect to patient home with buy section
    return redirect(url_for('patient_home', section='buy'))

# ⏳ CHECK EXPIRY
@app.route("/patient/check_expiry", methods=["POST"])
def check_expiry():
    if "loggedin" in session and session["role"] == "patient":
        medicine_name = request.form["medicine_name"]
        cursor = get_cursor(dict=False)
        cursor.execute("SELECT expiry FROM medicines WHERE name=%s", (medicine_name,))
        medicine = cursor.fetchone()
        expiry_result = medicine[0] if medicine else "Medicine not found"
        cursor.close()

        return render_template(
            "patient_home.html",
            patient_name=session["name"],
            expiry_result=expiry_result,
            active_section=request.form.get("section", "expiry")
        )
    return redirect(url_for("login"))

# Add new medicine
@app.route("/add_medicine", methods=["GET", "POST"])
def add_medicine():
    if "loggedin" in session and session.get("role") == "store":
        if request.method == "POST":
            name = request.form["name"]
            stock = request.form["stock"]
            expiry_date = request.form["expiry"]

            store_name = session.get("name")   # ✅ Get store name from session

            cur = get_cursor(dict=False)
            cur.execute(
                "INSERT INTO medicines (name, stock, expiry, store) VALUES (%s, %s, %s, %s)",
                (name, stock, expiry_date, store_name)   # ✅ Insert store name
            )
            db.commit()
            cur.close()

            flash("Medicine added successfully!", "success")
            return redirect(url_for("view_medicine"))

        return render_template("add_medicine.html")

    flash("Unauthorized access.", "danger")
    return redirect(url_for("home"))


# View medicines
@app.route('/view_medicine')
def view_medicine():
    if "loggedin" not in session or session.get("role") != "store":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("home"))

    store_name = session.get("name")   # ✅ get the store name

    cur = get_cursor(dict=False)
    cur.execute(
        "SELECT id, name, stock, expiry, store FROM medicines WHERE store = %s",
        (store_name,)
    )
    medicines = cur.fetchall()
    cur.close()

    return render_template("view_medicine.html", medicines=medicines)


# Edit medicine
@app.route("/edit_medicine/<int:med_id>", methods=["GET", "POST"])
def edit_medicine(med_id):
    if "loggedin" in session and session.get("role") == "store":
        cursor = get_cursor(dict=False)

        if request.method == "POST":
            name = request.form["name"]
            stock = request.form["stock"]
            expiry_date = request.form["expiry"]

            cursor.execute(
                "UPDATE medicines SET name=%s, stock=%s, expiry=%s WHERE id=%s",
                (name, stock, expiry_date, med_id)
            )
            db.commit()
            cursor.close()

            flash("Medicine updated successfully!", "success")
            return redirect(url_for("view_medicine"))  # ✅ redirect back to list

        # GET: load medicine data for form
        cursor.execute("SELECT id, name, stock, expiry FROM medicines WHERE id=%s", (med_id,))
        medicine = cursor.fetchone()
        cursor.close()
        return render_template("edit_medicine.html", medicine=medicine)

    flash("Unauthorized access.", "danger")
    return redirect(url_for("home"))

# Delete medicine
@app.route('/delete_medicine/<int:id>')
def delete_medicine(id):
    cur = get_cursor(dict=False)
    cur.execute("DELETE FROM medicines WHERE id=%s", (id,))
    db.commit()
    cur.close()
    return redirect(url_for('view_medicine'))

# Low stock medicines
@app.route("/low_stock")
def low_stock():
    if "loggedin" in session:
        if session.get("role") == "store":   # keep consistent with restock
            cursor = get_cursor(dict=False)
            cursor.execute("SELECT id, name, stock FROM medicines WHERE stock < 10")
            medicines = cursor.fetchall()
            cursor.close()
            return render_template("low_stock.html", medicines=medicines)
        else:
            flash("Only store staff can access Low Stock page.", "danger")
            return redirect(url_for("home"))
    else:
        flash("Please log in first.", "warning")
        return redirect(url_for("home"))

@app.route('/view_orders')
def view_orders():
    cur = get_cursor(dict=False)
    # Join purchases with users to get patient names
    cur.execute("""
        SELECT p.id, u.name AS patient_name, p.medicine_name, 
               p.quantity, p.store, p.purchased_at
        FROM purchases p
        JOIN patients u ON p.patient_id = u.id
    """)
    orders = cur.fetchall()
    cur.close()
    return render_template("view_orders.html", orders=orders)

@app.route('/expiry_alert')
def expiry_alert():
    cur = get_cursor(dict=False)
    today = datetime.today().date()
    upcoming = today + timedelta(days=3)

    # ✅ Medicines expiring soon (today to next 3 days)
    cur.execute("SELECT id, name, stock, expiry FROM medicines WHERE expiry BETWEEN %s AND %s",
                (today, upcoming))
    expiring_soon = cur.fetchall()

    # ✅ Medicines already expired (expiry < today)
    cur.execute("SELECT id, name, stock, expiry FROM medicines WHERE expiry < %s", (today,))
    expired = cur.fetchall()

    cur.close()

    # format expiry date for display
    formatted_expiring_soon = [
        (m[0], m[1], m[2], m[3].strftime("%d-%b-%Y") if m[3] else None)
        for m in expiring_soon
    ]
    formatted_expired = [
        (m[0], m[1], m[2], m[3].strftime("%d-%b-%Y") if m[3] else None)
        for m in expired
    ]

    return render_template("expiry_alert.html",
                           expiring_soon=formatted_expiring_soon,
                           expired=formatted_expired)

    
# Restock medicine
@app.route("/restock/<int:med_id>", methods=["POST"])
def restock(med_id):
    if "loggedin" in session and session.get("role") == "store":
        new_stock = request.form.get("new_stock")

        # Validation
        if not new_stock or not new_stock.isdigit():
            flash("Invalid stock value.", "danger")
            return redirect(url_for("low_stock"))

        new_stock = int(new_stock)

        cursor = get_cursor(dict=False)
        cursor.execute("UPDATE medicines SET stock = stock + %s WHERE id = %s", (new_stock, med_id))
        db.commit()
        cursor.close()

        flash("Medicine restocked successfully!", "success")
        return redirect(url_for("low_stock"))

    flash("Unauthorized access.", "danger")
    return redirect(url_for("home"))

# ---------------- MAIN ----------------
if __name__ == "__main__":
    print(" Starting CuraLink with Ngrok...")
    start_ngrok()  # Start ngrok automatically
    socketio.run(app, 
                 debug=True, 
                 host='0.0.0.0',  # Allow external connections
                 port=5000,
                 allow_unsafe_werkzeug=True)
