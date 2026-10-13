import os
import json
import uuid
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename
import bcrypt
import jwt

import config
from database import get_db_connection
from ai_engine import AIDamageAnalyzer
from cost_calculator import CostEstimator
from report_generator import generate_pdf_report

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Initialize AI Damage Analyzer
ai_analyzer = AIDamageAnalyzer()
cost_estimator = CostEstimator()


# Helper: Allowed extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS


# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this feature.", "warning")
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function


# Admin decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash("Administrator privilege required.", "danger")
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function


# JWT Token Generator
def generate_jwt_token(user_id, email, role):
    payload = {
        'user_id': user_id,
        'email': email,
        'role': role,
        'exp': datetime.utcnow().timestamp() + (config.JWT_EXPIRATION_HOURS * 3600)
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm='HS256')


# Notification Helper
def create_notification(user_id, title, message, notif_type='info', link=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                '''
                INSERT INTO notifications (user_id, title, message, type, link, is_read)
                VALUES (%s, %s, %s, %s, %s, 0)
                ''',
                (user_id, title, message, notif_type, link)
            )
            conn.commit()
    except Exception as e:
        print(f"Error creating notification: {e}")
    finally:
        if conn: conn.close()


@app.context_processor
def inject_notifications():
    if 'user_id' in session:
        uid = session['user_id']
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(
                    '''
                    SELECT * FROM notifications 
                    WHERE user_id = %s OR user_id IS NULL 
                    ORDER BY created_at DESC LIMIT 10
                    ''',
                    (uid,)
                )
                notifs = cursor.fetchall() or []

                cursor.execute(
                    '''
                    SELECT COUNT(*) as unread_count FROM notifications 
                    WHERE (user_id = %s OR user_id IS NULL) AND is_read = 0
                    ''',
                    (uid,)
                )
                row = cursor.fetchone()
                unread_count = row['unread_count'] if row else 0

                return {
                    'user_notifications': notifs,
                    'unread_notif_count': unread_count
                }
        except Exception as e:
            print(f"Notification context error: {e}")
            return {'user_notifications': [], 'unread_notif_count': 0}
        finally:
            if conn: conn.close()
    return {'user_notifications': [], 'unread_notif_count': 0}


# -------------------------------------------------------------
# Landing Page
# -------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


# -------------------------------------------------------------
# Module 1: User Login, Registration & JWT Auth
# -------------------------------------------------------------
@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'register':
            name = request.form.get('name')
            email = request.form.get('email')
            password = request.form.get('password')
            contact_number = request.form.get('contact_number')
            address = request.form.get('address')
            role = request.form.get('role', 'user')

            if not name or not email or not password:
                flash("Name, email, and password are required.", "danger")
                return redirect(url_for('auth'))

            hashed_pass = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            conn = get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO users (name, email, password, role, contact_number, address) VALUES (%s, %s, %s, %s, %s, %s)",
                        (name, email, hashed_pass, role, contact_number, address)
                    )
                    conn.commit()
                flash("Registration successful! Please log in.", "success")
            except Exception as e:
                flash(f"User registration failed: {e}", "danger")
            finally:
                if conn: conn.close()

            return redirect(url_for('auth'))

        elif action == 'login':
            email = request.form.get('email')
            password = request.form.get('password')

            conn = get_db_connection()
            try:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                    user = cursor.fetchone()

                    if user:
                        db_pass = user['password']
                        match = False
                        try:
                            match = bcrypt.checkpw(password.encode('utf-8'), db_pass.encode('utf-8'))
                        except Exception:
                            match = (db_pass == password)

                        if match:
                            session['user_id'] = user['user_id']
                            session['name'] = user['name']
                            session['email'] = user['email']
                            session['role'] = user['role']

                            token = generate_jwt_token(user['user_id'], user['email'], user['role'])
                            session['jwt_token'] = token

                            flash(f"Welcome back, {user['name']}!", "success")
                            if user['role'] == 'admin':
                                return redirect(url_for('admin_dashboard'))
                            return redirect(url_for('vehicle_register'))
                        else:
                            flash("Invalid password.", "danger")
                    else:
                        flash("User email not found.", "danger")
            except Exception as e:
                flash(f"Login error: {e}", "danger")
            finally:
                if conn: conn.close()

    return render_template('auth.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("Successfully logged out.", "info")
    return redirect(url_for('auth'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        contact_number = request.form.get('contact_number')
        address = request.form.get('address')
        role = request.form.get('role', 'user')

        if not name or not email or not password:
            flash("Name, email, and password are required.", "danger")
            return redirect(url_for('register'))

        hashed_pass = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (name, email, password, role, contact_number, address) VALUES (%s, %s, %s, %s, %s, %s)",
                    (name, email, hashed_pass, role, contact_number, address)
                )
                conn.commit()
            flash("Registration successful! Please log in.", "success")
        except Exception as e:
            flash(f"User registration failed: {e}", "danger")
        finally:
            if conn: conn.close()

        return redirect(url_for('auth'))

    return render_template('register.html')


# -------------------------------------------------------------
# Module 2: Vehicle Registration
# -------------------------------------------------------------
# API: Dynamic Car Models based on Car Brand
# -------------------------------------------------------------
@app.route('/api/car-models', methods=['GET'])
def get_car_models_api():
    brand = request.args.get('brand', '').strip().upper()
    json_path = os.path.join(config.BASE_DIR, 'car_parts_prices.json')
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            if brand:
                return jsonify({'brand': brand, 'models': list(data.get(brand, {}).keys())})
            return jsonify({b: list(models.keys()) for b, models in data.items()})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({}), 404


@app.route('/vehicle/register', methods=['GET', 'POST'])
@login_required
def vehicle_register():
    if request.method == 'POST':
        vin_number = request.form.get('vin_number')
        car_brand = request.form.get('car_brand')
        model = request.form.get('model')
        custom_model = request.form.get('custom_model', '').strip()
        if model == '__custom__' and custom_model:
            model = custom_model
        year = request.form.get('year', 2023)
        color = request.form.get('color', 'Black')
        insurance_provider = request.form.get('insurance_provider')
        policy_number = request.form.get('policy_number')
        coverage_type = request.form.get('coverage_type', 'Comprehensive')
        expiry_date = request.form.get('expiry_date')

        if not vin_number or not car_brand or not model or not insurance_provider or not policy_number:
            flash("All vehicle and insurance details are required.", "warning")
            return redirect(url_for('vehicle_register'))

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''
                    INSERT INTO vehicles (user_id, vin_number, car_brand, model, year, color, 
                                          insurance_provider, policy_number, coverage_type, expiry_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''',
                    (session['user_id'], vin_number, car_brand, model, year, color,
                     insurance_provider, policy_number, coverage_type, expiry_date)
                )
                conn.commit()
                vehicle_id = cursor.lastrowid

            session['current_vehicle_id'] = vehicle_id
            create_notification(
                session['user_id'],
                "Vehicle Registered",
                f"{car_brand} {model} ({vin_number}) was successfully added to your garage.",
                "success",
                url_for('upload_images', vehicle_id=vehicle_id)
            )
            flash("Vehicle registered successfully! Proceed to upload inspection images.", "success")
            return redirect(url_for('upload_images', vehicle_id=vehicle_id))
        except Exception as e:
            flash(f"Vehicle registration error: {e}", "danger")
        finally:
            if conn: conn.close()

    # GET: fetch user's existing vehicles and inspection reports
    vehicles = []
    reports = []
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM vehicles WHERE user_id = %s ORDER BY created_at DESC", (session['user_id'],))
            vehicles = cursor.fetchall()

            cursor.execute("""
                SELECT r.*, v.car_brand, v.model, v.vin_number, v.insurance_provider, v.policy_number,
                       (SELECT COUNT(*) FROM damage_detections d WHERE d.report_id = r.report_id) AS damage_count
                FROM reports r
                JOIN vehicles v ON r.vehicle_id = v.vehicle_id
                WHERE r.user_id = %s
                ORDER BY r.created_at DESC
            """, (session['user_id'],))
            reports = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching vehicles/reports: {e}")
    finally:
        if conn: conn.close()

    return render_template('vehicle_register.html', vehicles=vehicles, reports=reports)


@app.route('/my-reports')
@login_required
def my_reports():
    conn = get_db_connection()
    reports = []
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT r.*, v.car_brand, v.model, v.vin_number, v.insurance_provider, v.policy_number,
                       (SELECT COUNT(*) FROM damage_detections d WHERE d.report_id = r.report_id) AS damage_count
                FROM reports r
                JOIN vehicles v ON r.vehicle_id = v.vehicle_id
                WHERE r.user_id = %s
                ORDER BY r.created_at DESC
            """, (session['user_id'],))
            reports = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching user reports: {e}")
    finally:
        if conn: conn.close()
    return render_template('my_reports.html', reports=reports)


# -------------------------------------------------------------
# Module 3: Upload Images (Front, Rear, Side View & Validation)
# -------------------------------------------------------------
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_images():
    vehicle_id = request.args.get('vehicle_id') or session.get('current_vehicle_id')
    if not vehicle_id:
        flash("Please select or register a vehicle first.", "warning")
        return redirect(url_for('vehicle_register'))

    conn = get_db_connection()
    vehicle = None
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM vehicles WHERE vehicle_id = %s", (vehicle_id,))
            vehicle = cursor.fetchone()
    finally:
        if conn: conn.close()

    if request.method == 'POST':
        front_file = request.files.get('front_image')
        rear_file = request.files.get('rear_image')
        side_file = request.files.get('side_image')

        files_map = {
            'Front': front_file,
            'Rear': rear_file,
            'Side': side_file
        }

        report_id = f"REP-{uuid.uuid4().hex[:8].upper()}"
        all_detections = []
        uploaded_views_data = []

        for view_name, file_obj in files_map.items():
            if file_obj and file_obj.filename != '' and allowed_file(file_obj.filename):
                ext = file_obj.filename.rsplit('.', 1)[1].lower()
                orig_filename = f"{report_id}_{view_name.lower()}_orig.{ext}"
                annot_filename = f"{report_id}_{view_name.lower()}_annot.{ext}"

                orig_path = os.path.join(config.UPLOAD_FOLDER, orig_filename)
                annot_path = os.path.join(config.UPLOAD_FOLDER, annot_filename)

                file_obj.save(orig_path)

                # AI Detection Pipeline
                ai_res = ai_analyzer.detect_damage(orig_path, annot_path)
                if ai_res.get('success'):
                    for d in ai_res.get('detections', []):
                        d['view_type'] = view_name
                        all_detections.append(d)

                uploaded_views_data.append({
                    'view_type': view_name,
                    'orig_filename': orig_filename,
                    'annot_filename': annot_filename
                })

        if not uploaded_views_data:
            flash("At least one valid image (Front, Rear, or Side view) must be uploaded.", "danger")
            return render_template('upload_images.html', vehicle=vehicle)

        # Module 4 & 5: Cost Calculation & Severity Matrix
        brand = vehicle.get('car_brand', 'HONDA') if vehicle else 'HONDA'
        model_name = vehicle.get('model', 'City') if vehicle else 'City'
        cost_results = cost_estimator.calculate_repair_cost(brand, model_name, all_detections)

        summary = cost_results['summary']
        itemized = cost_results['itemized_breakdown']

        overall_severity = 'Minor'
        severities = [d.get('severity') for d in all_detections]
        if 'Severe' in severities:
            overall_severity = 'Severe'
        elif 'Moderate' in severities:
            overall_severity = 'Moderate'

        # Module 6 & DB Store
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Save Report
                cursor.execute(
                    '''
                    INSERT INTO reports (report_id, user_id, vehicle_id, total_parts_cost, total_labour_cost,
                                         total_paint_cost, tax_amount, total_cost, repair_time_hours, severity_level, overall_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''',
                    (report_id, session['user_id'], vehicle_id, summary['total_parts_cost'], summary['total_labour_cost'],
                     summary['total_paint_cost'], summary['tax_amount'], summary['total_estimated_cost'],
                     summary['total_repair_hours'], overall_severity, 'Completed')
                )

                # Save Uploaded Images
                for uv in uploaded_views_data:
                    cursor.execute(
                        "INSERT INTO uploaded_images (report_id, view_type, original_filename, annotated_filename) VALUES (%s, %s, %s, %s)",
                        (report_id, uv['view_type'], uv['orig_filename'], uv['annot_filename'])
                    )

                # Save Damage Detections
                for idx, det in enumerate(all_detections):
                    item_info = itemized[idx] if idx < len(itemized) else {}
                    cursor.execute(
                        '''
                        INSERT INTO damage_detections (report_id, part_name, damage_type, severity, confidence, bbox_json, part_cost)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ''',
                        (report_id, det.get('part_name'), det.get('damage_type'), det.get('severity'),
                         det.get('confidence'), str(det.get('bbox')), item_info.get('effective_part_cost', 0.0))
                    )

                conn.commit()

            # Generate PDF Report
            pdf_filename = f"Inspection_Report_{report_id}.pdf"
            pdf_path = os.path.join(config.REPORT_FOLDER, pdf_filename)
            
            report_payload = {
                'report_id': report_id,
                'user': {'name': session.get('name'), 'email': session.get('email'), 'contact_number': 'Registered User'},
                'vehicle': vehicle,
                'detections': itemized,
                'summary': summary
            }
            generate_pdf_report(report_payload, pdf_path)

            # Update DB with pdf filename
            with conn.cursor() as cursor:
                cursor.execute("UPDATE reports SET pdf_filename = %s WHERE report_id = %s", (pdf_filename, report_id))
                conn.commit()

            create_notification(
                session['user_id'],
                "Inspection Report Ready",
                f"Report #{report_id} completed. Severity: {overall_severity}, Estimate: Rs. {summary['total_estimated_cost']:,.2f}.",
                "report",
                url_for('report_view', report_id=report_id)
            )

            flash("AI Damage Detection & Cost Estimation completed successfully!", "success")
            return redirect(url_for('severity_analysis', report_id=report_id))

        except Exception as e:
            flash(f"Error processing AI inspection: {e}", "danger")
        finally:
            if conn: conn.close()

    return render_template('upload_images.html', vehicle=vehicle)


# -------------------------------------------------------------
# Module 4 & 5: Severity Analysis & Cost Estimation View
# -------------------------------------------------------------
@app.route('/severity_analysis/<report_id>')
@login_required
def severity_analysis(report_id):
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM reports WHERE report_id = %s", (report_id,))
            report = cursor.fetchone()
            if not report:
                flash("Report not found.", "danger")
                return redirect(url_for('vehicle_register'))

            cursor.execute("SELECT * FROM vehicles WHERE vehicle_id = %s", (report['vehicle_id'],))
            vehicle = cursor.fetchone()

            cursor.execute("SELECT * FROM uploaded_images WHERE report_id = %s", (report_id,))
            images = cursor.fetchall()

            cursor.execute("SELECT * FROM damage_detections WHERE report_id = %s", (report_id,))
            detections = cursor.fetchall()

            return render_template('severity_analysis.html',
                                   report=report,
                                   vehicle=vehicle,
                                   images=images,
                                   detections=detections)
    finally:
        if conn: conn.close()


# -------------------------------------------------------------
# Module 6: Report Generation View & PDF Download
# -------------------------------------------------------------
@app.route('/report/<report_id>')
@login_required
def report_view(report_id):
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM reports WHERE report_id = %s", (report_id,))
            report = cursor.fetchone()
            if not report:
                flash("Report not found.", "danger")
                return redirect(url_for('vehicle_register'))

            cursor.execute("SELECT * FROM users WHERE user_id = %s", (report['user_id'],))
            report_user = cursor.fetchone()

            cursor.execute("SELECT * FROM vehicles WHERE vehicle_id = %s", (report['vehicle_id'],))
            vehicle = cursor.fetchone()

            cursor.execute("SELECT * FROM uploaded_images WHERE report_id = %s", (report_id,))
            images = cursor.fetchall()

            cursor.execute("SELECT * FROM damage_detections WHERE report_id = %s", (report_id,))
            detections = cursor.fetchall()

            return render_template('report_view.html',
                                   report=report,
                                   report_user=report_user,
                                   vehicle=vehicle,
                                   images=images,
                                   detections=detections)
    finally:
        if conn: conn.close()


@app.route('/report/<report_id>/pdf')
@login_required
def download_pdf_report(report_id):
    filename = f"Inspection_Report_{report_id}.pdf"
    file_path = os.path.join(config.REPORT_FOLDER, filename)
    if os.path.exists(file_path):
        return send_from_directory(config.REPORT_FOLDER, filename, as_attachment=True)
    flash("PDF file not available.", "danger")
    return redirect(url_for('report_view', report_id=report_id))


# -------------------------------------------------------------
# Module: Payment Gateway & Checkout Routes
# -------------------------------------------------------------
@app.route('/payment/<report_id>')
@login_required
def payment_page(report_id):
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM reports WHERE report_id = %s", (report_id,))
            report = cursor.fetchone()
            if not report:
                flash("Report not found.", "danger")
                return redirect(url_for('my_reports'))

            if report['user_id'] != session['user_id'] and session.get('role') != 'admin':
                flash("Unauthorized access to this report's payment.", "danger")
                return redirect(url_for('my_reports'))

            # Check if already paid
            cursor.execute("SELECT * FROM payments WHERE report_id = %s AND payment_status = 'Success'", (report_id,))
            existing_payment = cursor.fetchone()
            if existing_payment:
                return redirect(url_for('payment_receipt', payment_id=existing_payment['payment_id']))

            cursor.execute("SELECT * FROM vehicles WHERE vehicle_id = %s", (report['vehicle_id'],))
            vehicle = cursor.fetchone()

            cursor.execute("SELECT * FROM damage_detections WHERE report_id = %s", (report_id,))
            detections = cursor.fetchall()

            return render_template('payment.html',
                                   report=report,
                                   vehicle=vehicle,
                                   detections=detections)
    finally:
        if conn: conn.close()


@app.route('/payment/process', methods=['POST'])
@login_required
def process_payment():
    report_id = request.form.get('report_id')
    amount_raw = request.form.get('amount', 0.0)
    payment_method = request.form.get('payment_method', 'Credit/Debit Card')
    
    card_number = request.form.get('card_number', '')
    card_last4 = card_number.replace(' ', '')[-4:] if card_number else None
    upi_id = request.form.get('upi_id', '') or None

    try:
        amount = float(amount_raw)
    except (ValueError, TypeError):
        amount = 0.0

    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM reports WHERE report_id = %s", (report_id,))
            report = cursor.fetchone()
            if not report:
                flash("Report not found.", "danger")
                return redirect(url_for('my_reports'))

            payment_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"
            transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"

            # Save payment with 'Pending Approval' status
            cursor.execute(
                '''
                INSERT INTO payments (payment_id, report_id, user_id, amount, payment_method, transaction_id, payment_status, card_last4, upi_id)
                VALUES (%s, %s, %s, %s, %s, %s, 'Pending Approval', %s, %s)
                ''',
                (payment_id, report_id, session['user_id'], amount, payment_method, transaction_id, card_last4, upi_id)
            )

            cursor.execute(
                "UPDATE reports SET payment_status = 'Pending Approval' WHERE report_id = %s",
                (report_id,)
            )

            conn.commit()

            # Notify Admin users
            cursor.execute("SELECT user_id FROM users WHERE role = 'admin'")
            admins = cursor.fetchall()
            for adm in admins:
                create_notification(
                    adm['user_id'],
                    "Payment Pending Approval",
                    f"User {session.get('name')} submitted payment of Rs. {amount:,.2f} for Report {report_id}. Action required.",
                    "warning",
                    url_for('admin_dashboard')
                )

        create_notification(
            session['user_id'],
            "Payment Submitted",
            f"Payment of Rs. {amount:,.2f} for Report {report_id} was submitted and is awaiting Admin verification. Txn ID: {transaction_id}.",
            "warning",
            url_for('payment_receipt', payment_id=payment_id)
        )

        flash(f"Payment submitted successfully! Your transaction (Txn: {transaction_id}) is pending administrator approval.", "info")
        return redirect(url_for('payment_receipt', payment_id=payment_id))
    except Exception as e:
        flash(f"Payment processing error: {e}", "danger")
        return redirect(url_for('payment_page', report_id=report_id))
    finally:
        if conn: conn.close()


@app.route('/payment/receipt/<payment_id>')
@login_required
def payment_receipt(payment_id):
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM payments WHERE payment_id = %s", (payment_id,))
            payment = cursor.fetchone()
            if not payment:
                flash("Payment receipt not found.", "danger")
                return redirect(url_for('my_reports'))

            if payment['user_id'] != session['user_id'] and session.get('role') != 'admin':
                flash("Unauthorized access to payment receipt.", "danger")
                return redirect(url_for('my_reports'))

            cursor.execute("SELECT * FROM reports WHERE report_id = %s", (payment['report_id'],))
            report = cursor.fetchone()

            cursor.execute("SELECT * FROM users WHERE user_id = %s", (payment['user_id'],))
            user = cursor.fetchone()

            cursor.execute("SELECT * FROM vehicles WHERE vehicle_id = %s", (report['vehicle_id'],))
            vehicle = cursor.fetchone()

            return render_template('payment_receipt.html',
                                   payment=payment,
                                   report=report,
                                   user=user,
                                   vehicle=vehicle)
    finally:
        if conn: conn.close()


# -------------------------------------------------------------
# Admin Payment Approval Routes
# -------------------------------------------------------------
@app.route('/admin/payment/approve/<payment_id>', methods=['POST'])
@admin_required
def admin_approve_payment(payment_id):
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM payments WHERE payment_id = %s", (payment_id,))
            payment = cursor.fetchone()
            if not payment:
                flash("Payment record not found.", "danger")
                return redirect(url_for('admin_dashboard'))

            cursor.execute("UPDATE payments SET payment_status = 'Success' WHERE payment_id = %s", (payment_id,))
            cursor.execute("UPDATE reports SET payment_status = 'Paid' WHERE report_id = %s", (payment['report_id'],))
            conn.commit()

        create_notification(
            payment['user_id'],
            "Payment Approved & Verified!",
            f"Your payment of Rs. {payment['amount']:,.2f} for Report {payment['report_id']} was accepted and verified by Admin. Txn ID: {payment['transaction_id']}.",
            "success",
            url_for('payment_receipt', payment_id=payment_id)
        )

        flash(f"Payment '{payment_id}' approved and marked as Successful!", "success")
    except Exception as e:
        flash(f"Error approving payment: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/payment/reject/<payment_id>', methods=['POST'])
@admin_required
def admin_reject_payment(payment_id):
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM payments WHERE payment_id = %s", (payment_id,))
            payment = cursor.fetchone()
            if not payment:
                flash("Payment record not found.", "danger")
                return redirect(url_for('admin_dashboard'))

            cursor.execute("UPDATE payments SET payment_status = 'Rejected' WHERE payment_id = %s", (payment_id,))
            cursor.execute("UPDATE reports SET payment_status = 'Unpaid' WHERE report_id = %s", (payment['report_id'],))
            conn.commit()

        create_notification(
            payment['user_id'],
            "Payment Rejected",
            f"Your payment of Rs. {payment['amount']:,.2f} for Report {payment['report_id']} was rejected by Admin. Please re-submit payment.",
            "warning",
            url_for('payment_page', report_id=payment['report_id'])
        )

        flash(f"Payment '{payment_id}' rejected.", "warning")
    except Exception as e:
        flash(f"Error rejecting payment: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


# -------------------------------------------------------------
# Module 7: Admin Dashboard & Analytics
# -------------------------------------------------------------
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # Metrics
            cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'user'")
            total_users = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) as total FROM vehicles")
            total_vehicles = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) as total, COALESCE(SUM(total_cost), 0) as total_claim_amount FROM reports")
            rep_stats = cursor.fetchone()
            total_inspections = rep_stats['total']
            total_claims_cost = rep_stats['total_claim_amount']

            # Payment Metrics & Records
            cursor.execute("SELECT COUNT(*) as total_payments, COALESCE(SUM(amount), 0) as total_revenue FROM payments WHERE payment_status = 'Success'")
            pay_stats = cursor.fetchone()
            total_revenue = pay_stats['total_revenue'] if pay_stats else 0.0
            total_paid_count = pay_stats['total_payments'] if pay_stats else 0

            cursor.execute("SELECT COUNT(*) as pending_count FROM payments WHERE payment_status = 'Pending Approval'")
            p_stats = cursor.fetchone()
            pending_payments_count = p_stats['pending_count'] if p_stats else 0

            cursor.execute('''
                SELECT p.*, u.name as user_name, u.email as user_email 
                FROM payments p 
                JOIN users u ON p.user_id = u.user_id 
                ORDER BY CASE WHEN p.payment_status = 'Pending Approval' THEN 0 ELSE 1 END, p.created_at DESC LIMIT 50
            ''')
            all_payments = cursor.fetchall()

            # Users table
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 20")
            all_users = cursor.fetchall()

            # Vehicles table
            cursor.execute('''
                SELECT v.*, u.name as owner_name 
                FROM vehicles v 
                JOIN users u ON v.user_id = u.user_id 
                ORDER BY v.created_at DESC LIMIT 20
            ''')
            all_vehicles = cursor.fetchall()

            # Reports table
            cursor.execute('''
                SELECT r.*, u.name as owner_name, v.car_brand, v.model 
                FROM reports r 
                JOIN users u ON r.user_id = u.user_id 
                JOIN vehicles v ON r.vehicle_id = v.vehicle_id 
                ORDER BY r.created_at DESC LIMIT 20
            ''')
            all_reports = cursor.fetchall()

            # Analytics: Damage Type distribution
            cursor.execute("SELECT damage_type, COUNT(*) as count FROM damage_detections GROUP BY damage_type")
            damage_dist = cursor.fetchall()

            # Analytics: Severity distribution
            cursor.execute("SELECT severity_level, COUNT(*) as count FROM reports GROUP BY severity_level")
            severity_dist = cursor.fetchall()

            # Feedback table
            cursor.execute('''
                SELECT f.*, u.name as user_name, u.email as user_email, u.contact_number as user_contact
                FROM feedback f
                JOIN users u ON f.user_id = u.user_id
                ORDER BY f.created_at DESC LIMIT 50
            ''')
            all_feedback = cursor.fetchall()

            # Feedback statistics
            cursor.execute("SELECT AVG(rating) as avg_rating, COUNT(*) as total_count FROM feedback")
            f_stats = cursor.fetchone()
            avg_rating = round(float(f_stats['avg_rating']), 1) if f_stats and f_stats['avg_rating'] is not None else 0.0
            total_feedbacks = f_stats['total_count'] if f_stats else 0

            return render_template('admin.html',
                                   total_users=total_users,
                                   total_vehicles=total_vehicles,
                                   total_inspections=total_inspections,
                                   total_claims_cost=total_claims_cost,
                                   total_revenue=total_revenue,
                                   total_paid_count=total_paid_count,
                                   pending_payments_count=pending_payments_count,
                                   all_payments=all_payments,
                                   all_users=all_users,
                                   all_vehicles=all_vehicles,
                                   all_reports=all_reports,
                                   damage_dist=damage_dist,
                                   severity_dist=severity_dist,
                                   all_feedback=all_feedback,
                                   avg_rating=avg_rating,
                                   total_feedbacks=total_feedbacks)
    finally:
        if conn: conn.close()


# -------------------------------------------------------------
# Admin Actions: User Edit & Delete
# -------------------------------------------------------------
@app.route('/admin/user/edit/<int:user_id>', methods=['POST'])
@admin_required
def admin_edit_user(user_id):
    name = request.form.get('name')
    email = request.form.get('email')
    role = request.form.get('role', 'user')
    contact_number = request.form.get('contact_number')
    address = request.form.get('address')

    if not name or not email:
        flash("Name and Email are required.", "warning")
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                '''
                UPDATE users 
                SET name = %s, email = %s, role = %s, contact_number = %s, address = %s
                WHERE user_id = %s
                ''',
                (name, email, role, contact_number, address, user_id)
            )
            conn.commit()
        flash(f"User '{name}' updated successfully.", "success")
    except Exception as e:
        flash(f"Error updating user: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_id == session.get('user_id'):
        flash("You cannot delete your own logged-in admin account.", "danger")
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT report_id FROM reports WHERE user_id = %s", (user_id,))
            user_reports = cursor.fetchall()
            for r in user_reports:
                rep_id = r['report_id'] if isinstance(r, dict) else r[0]
                cursor.execute("DELETE FROM damage_detections WHERE report_id = %s", (rep_id,))
                cursor.execute("DELETE FROM uploaded_images WHERE report_id = %s", (rep_id,))
                cursor.execute("DELETE FROM reports WHERE report_id = %s", (rep_id,))
            
            cursor.execute("DELETE FROM vehicles WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            conn.commit()
        flash("User and all associated records deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting user: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


# -------------------------------------------------------------
# Admin Actions: Vehicle Edit & Delete
# -------------------------------------------------------------
@app.route('/admin/vehicle/edit/<int:vehicle_id>', methods=['POST'])
@admin_required
def admin_edit_vehicle(vehicle_id):
    car_brand = request.form.get('car_brand')
    model = request.form.get('model')
    custom_model = request.form.get('custom_model', '').strip()
    if model == '__custom__' and custom_model:
        model = custom_model
    year = request.form.get('year', 2023)
    color = request.form.get('color', 'Black')
    vin_number = request.form.get('vin_number')
    insurance_provider = request.form.get('insurance_provider')
    policy_number = request.form.get('policy_number')
    coverage_type = request.form.get('coverage_type', 'Comprehensive')
    expiry_date = request.form.get('expiry_date')

    if not vin_number or not car_brand or not model:
        flash("Brand, Model, and VIN Number are required.", "warning")
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                '''
                UPDATE vehicles 
                SET car_brand = %s, model = %s, year = %s, color = %s, 
                    vin_number = %s, insurance_provider = %s, policy_number = %s, 
                    coverage_type = %s, expiry_date = %s
                WHERE vehicle_id = %s
                ''',
                (car_brand, model, year, color, vin_number, insurance_provider, policy_number, coverage_type, expiry_date, vehicle_id)
            )
            conn.commit()
        flash("Vehicle details updated successfully.", "success")
    except Exception as e:
        flash(f"Error updating vehicle: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/vehicle/delete/<int:vehicle_id>', methods=['POST'])
@admin_required
def admin_delete_vehicle(vehicle_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT report_id FROM reports WHERE vehicle_id = %s", (vehicle_id,))
            v_reports = cursor.fetchall()
            for r in v_reports:
                rep_id = r['report_id'] if isinstance(r, dict) else r[0]
                cursor.execute("DELETE FROM damage_detections WHERE report_id = %s", (rep_id,))
                cursor.execute("DELETE FROM uploaded_images WHERE report_id = %s", (rep_id,))
                cursor.execute("DELETE FROM reports WHERE report_id = %s", (rep_id,))

            cursor.execute("DELETE FROM vehicles WHERE vehicle_id = %s", (vehicle_id,))
            conn.commit()
        flash("Vehicle and associated reports deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting vehicle: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


# -------------------------------------------------------------
# Admin Actions: Inspection Report Edit & Delete
# -------------------------------------------------------------
@app.route('/admin/report/edit/<report_id>', methods=['POST'])
@admin_required
def admin_edit_report(report_id):
    severity_level = request.form.get('severity_level')
    overall_status = request.form.get('overall_status', 'Completed')
    total_cost = request.form.get('total_cost', 0.0)

    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT user_id FROM reports WHERE report_id = %s", (report_id,))
            rep = cursor.fetchone()
            owner_id = rep['user_id'] if rep else None

            cursor.execute(
                '''
                UPDATE reports 
                SET severity_level = %s, overall_status = %s, total_cost = %s
                WHERE report_id = %s
                ''',
                (severity_level, overall_status, total_cost, report_id)
            )
            conn.commit()

        if owner_id:
            create_notification(
                owner_id,
                "Report Updated by Admin",
                f"Your inspection report {report_id} was updated: Status '{overall_status}', Severity '{severity_level}'.",
                "warning",
                url_for('report_view', report_id=report_id)
            )

        flash(f"Report '{report_id}' updated successfully.", "success")
    except Exception as e:
        flash(f"Error updating report: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/report/delete/<report_id>', methods=['POST'])
@admin_required
def admin_delete_report(report_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM damage_detections WHERE report_id = %s", (report_id,))
            cursor.execute("DELETE FROM uploaded_images WHERE report_id = %s", (report_id,))
            cursor.execute("DELETE FROM reports WHERE report_id = %s", (report_id,))
            conn.commit()
        flash(f"Report '{report_id}' deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting report: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


# -------------------------------------------------------------
# Module: Feedback & Rating Routes
# -------------------------------------------------------------
@app.route('/feedback/submit', methods=['POST'])
@login_required
def submit_feedback():
    report_id = request.form.get('report_id') or None
    rating_raw = request.form.get('rating', 5)
    category = request.form.get('category', 'General')
    comments = request.form.get('comments', '').strip()

    try:
        rating = max(1, min(5, int(rating_raw)))
    except (ValueError, TypeError):
        rating = 5

    if not comments:
        flash("Please enter feedback comments with your rating.", "warning")
        return redirect(request.referrer or url_for('index'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                '''
                INSERT INTO feedback (user_id, report_id, rating, category, comments, status)
                VALUES (%s, %s, %s, %s, %s, 'New')
                ''',
                (session['user_id'], report_id, rating, category, comments)
            )
            conn.commit()

        # Confirmation to user
        create_notification(
            session['user_id'],
            "Feedback Received",
            f"Thank you! Your {rating}-star rating and feedback were submitted successfully.",
            "success",
            None
        )

        # Notify administrators
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT user_id FROM users WHERE role = 'admin'")
            admins = cursor.fetchall()
            for adm in admins:
                create_notification(
                    adm['user_id'],
                    "New User Feedback",
                    f"{session.get('name')} submitted a {rating}★ rating ({category}).",
                    "feedback",
                    url_for('admin_dashboard')
                )

        flash("Thank you for your rating and feedback!", "success")
    except Exception as e:
        flash(f"Error saving feedback: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(request.referrer or url_for('index'))


@app.route('/admin/feedback/status/<int:feedback_id>', methods=['POST'])
@admin_required
def admin_feedback_status(feedback_id):
    new_status = request.form.get('status', 'Reviewed')
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE feedback SET status = %s WHERE feedback_id = %s", (new_status, feedback_id))
            conn.commit()
        flash("Feedback review status updated.", "success")
    except Exception as e:
        flash(f"Error updating status: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/feedback/delete/<int:feedback_id>', methods=['POST'])
@admin_required
def admin_feedback_delete(feedback_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM feedback WHERE feedback_id = %s", (feedback_id,))
            conn.commit()
        flash("Feedback entry deleted.", "success")
    except Exception as e:
        flash(f"Error deleting feedback: {e}", "danger")
    finally:
        if conn: conn.close()

    return redirect(url_for('admin_dashboard'))


# -------------------------------------------------------------
# Module: Notifications AJAX & Broadcast Routes
# -------------------------------------------------------------
@app.route('/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    uid = session['user_id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s OR user_id IS NULL", (uid,))
            conn.commit()
        return jsonify({'success': True, 'message': 'All notifications marked as read.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn: conn.close()


@app.route('/admin/notification/send', methods=['POST'])
@admin_required
def admin_send_notification():
    target = request.form.get('target_user', 'all')
    title = request.form.get('title', 'Admin Notice')
    message = request.form.get('message', '').strip()
    notif_type = request.form.get('type', 'info')
    link = request.form.get('link', '') or None

    if not message:
        flash("Notification message cannot be blank.", "warning")
        return redirect(url_for('admin_dashboard'))

    target_id = None if target == 'all' else int(target)
    create_notification(target_id, title, message, notif_type, link)
    flash("System notification dispatched successfully.", "success")
    return redirect(url_for('admin_dashboard'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
