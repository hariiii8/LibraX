import oracledb
import hashlib
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import wraps
from datetime import timedelta
from dotenv import load_dotenv
import os
load_dotenv()

app = Flask(__name__)
app.secret_key = 'librax_secret_key_2024'
app.permanent_session_lifetime = timedelta(days=30)

DB_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "dsn": os.getenv("DB_DSN")
}
app.secret_key = os.getenv("SECRET_KEY")

def get_db():
    return oracledb.connect(user=DB_CONFIG["user"], password=DB_CONFIG["password"], dsn=DB_CONFIG["dsn"])

def hash_pw(p):
    return hashlib.sha256(p.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def d(*a, **k):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*a, **k)
    return d

def staff_required(f):
    @wraps(f)
    def d(*a, **k):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'staff':
            return redirect(url_for('student_dashboard'))
        return f(*a, **k)
    return d

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('staff_dashboard') if session.get('role') == 'staff' else url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/student-dashboard')
@login_required
def student_dashboard():
    return render_template('student_dashboard.html')

@app.route('/staff-dashboard')
@staff_required
def staff_dashboard():
    return render_template('staff_dashboard.html')

@app.route('/api/public/stats')
def api_public_stats():
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM books")
        books = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM students WHERE is_active = 1")
        members = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM book_issues WHERE return_date IS NOT NULL")
        ret = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM book_issues")
        total = cur.fetchone()[0]
        rate = round((ret / total) * 100) if total > 0 else 98
        cur.close(); conn.close()
        return jsonify({"success": True, "books": f"{books:,}", "members": f"{members:,}", "return_rate": f"{rate}%"})
    except Exception as e:
        print(f"[ERR] {e}")
        return jsonify({"success": False, "books": "12,400", "members": "3,200", "return_rate": "98%"})

@app.route('/api/login', methods=['POST'])
def api_login():
    d  = request.get_json()
    uid = d.get('id', '').strip().upper()
    pw  = d.get('password', '')
    role = d.get('role', 'student')
    if not uid or not pw:
        return jsonify({"success": False, "message": "All fields are required."})
    h = hash_pw(pw)
    try:
        conn = get_db(); cur = conn.cursor()
        if role == 'student':
            cur.execute("SELECT student_id, full_name, email, is_active FROM students WHERE student_id = :1 AND password_hash = :2", [uid, h])
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Invalid Student ID or password."})
            if not row[3]:
                return jsonify({"success": False, "message": "Account deactivated."})
            session.permanent = d.get('remember', False)
            session['user_id'] = row[0]; session['full_name'] = row[1]
            session['email'] = row[2]; session['role'] = 'student'
            return jsonify({"success": True, "message": "Login successful!", "redirect": "/student-dashboard"})
        elif role == 'staff':
            cur.execute("SELECT employee_id, full_name, email, staff_role, is_active FROM staff WHERE employee_id = :1 AND password_hash = :2", [uid, h])
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Invalid Employee ID or password."})
            if not row[4]:
                return jsonify({"success": False, "message": "Account inactive."})
            session.permanent = d.get('remember', False)
            session['user_id'] = row[0]; session['full_name'] = row[1]
            session['email'] = row[2]; session['role'] = 'staff'; session['staff_role'] = row[3]
            return jsonify({"success": True, "message": "Login successful!", "redirect": "/staff-dashboard"})
        return jsonify({"success": False, "message": "Invalid role."})
    except Exception as e:
        print(f"[ERR] {e}")
        return jsonify({"success": False, "message": "Database error. Please try again later."})
    finally:
        cur.close(); conn.close()

@app.route('/api/student/me')
@login_required
def api_student_me():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT student_id, full_name, email, department FROM students WHERE student_id = :1", [session['user_id']])
        r = cur.fetchone()
        cur.close(); conn.close()
        if not r: return jsonify({"success": False})
        return jsonify({"success": True, "data": {"student_id": r[0], "full_name": r[1], "email": r[2], "department": r[3]}})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/student/issued-books')
@login_required
def api_student_issued():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT b.title, b.author, i.issue_date, i.due_date, i.return_date, i.status FROM book_issues i JOIN books b ON i.book_id = b.book_id WHERE i.student_id = :1 AND i.return_date IS NULL ORDER BY i.issue_date DESC", [session['user_id']])
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"title": r[0], "author": r[1], "issue_date": str(r[2]), "due_date": str(r[3]), "return_date": str(r[4]) if r[4] else None, "status": r[5]} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/student/all-books')
@login_required
def api_student_all_books():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT b.title, b.author, i.issue_date, i.due_date, i.return_date, i.status FROM book_issues i JOIN books b ON i.book_id = b.book_id WHERE i.student_id = :1 ORDER BY i.issue_date DESC", [session['user_id']])
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"title": r[0], "author": r[1], "issue_date": str(r[2]), "due_date": str(r[3]), "return_date": str(r[4]) if r[4] else None, "status": r[5]} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/student/stats')
@login_required
def api_student_stats():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM book_issues WHERE student_id = :1 AND return_date IS NOT NULL",
            [session['user_id']]
        )
        ret = cur.fetchone()[0]

        # Fines already in fines table (from returned books)
        cur.execute("""
            SELECT f.fine_id, b.title, f.fine_amount
            FROM fines f
            JOIN book_issues i ON f.issue_id = i.issue_id
            JOIN books b ON i.book_id = b.book_id
            WHERE f.student_id = :1 AND f.paid = 0
        """, [session['user_id']])
        rows = cur.fetchall()
        fines = [{"fine_id": r[0], "title": r[1], "amount": float(r[2])} for r in rows]

        # ── NEW: Running fine from currently overdue books ──
        cur.execute("""
            SELECT b.title,
                   GREATEST(TRUNC(SYSDATE) - TRUNC(i.due_date), 0) * 2 AS running_fine
            FROM book_issues i
            JOIN books b ON i.book_id = b.book_id
            WHERE i.student_id = :1
              AND i.return_date IS NULL
              AND i.due_date < SYSDATE
        """, [session['user_id']])
        overdue_rows = cur.fetchall()
        for r in overdue_rows:
            if float(r[1]) > 0:
                fines.append({"fine_id": None, "title": r[0] + " (accruing)", "amount": float(r[1])})

        total_fine = sum(f['amount'] for f in fines)
        cur.close(); conn.close()
        return jsonify({"success": True, "data": {"returned": ret, "total_fine": total_fine, "fines": fines}})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/student/fines')
@login_required
def api_student_fines():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT b.title, b.author, f.fine_amount, f.paid, GREATEST(TRUNC(SYSDATE) - TRUNC(i.due_date), 0) FROM fines f JOIN book_issues i ON f.issue_id = i.issue_id JOIN books b ON i.book_id = b.book_id WHERE f.student_id = :1 ORDER BY f.paid, f.fine_amount DESC", [session['user_id']])
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"title": r[0], "author": r[1], "fine_amount": float(r[2]), "paid": bool(r[3]), "days_overdue": int(r[4])} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/student/reservations')
@login_required
def api_student_reservations():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT r.reservation_id, b.title, b.author, r.reserved_date, r.status FROM reservations r JOIN books b ON r.book_id = b.book_id WHERE r.student_id = :1 AND r.status = 'pending' ORDER BY r.reserved_date DESC", [session['user_id']])
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"reservation_id": r[0], "title": r[1], "author": r[2], "reserved_date": str(r[3]), "status": r[4]} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/student/reservations/<int:res_id>/cancel', methods=['POST'])
@login_required
def api_cancel_reservation(res_id):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE reservations SET status = 'cancelled' WHERE reservation_id = :1 AND student_id = :2", [res_id, session['user_id']])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/books')
@login_required
def api_all_books():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT book_id, isbn, title, author, genre, publisher, publish_year, total_copies, available_copies FROM books ORDER BY title")
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"book_id": r[0], "isbn": r[1], "title": r[2], "author": r[3], "genre": r[4], "publisher": r[5], "publish_year": r[6], "total_copies": r[7], "available_copies": r[8]} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/books/search')
@login_required
def api_search_books():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"success": False, "message": "No query."})
    try:
        conn = get_db(); cur = conn.cursor()
        like = '%' + q.upper() + '%'
        cur.execute("SELECT book_id, isbn, title, author, genre, publisher, total_copies, available_copies FROM books WHERE UPPER(title) LIKE :1 OR UPPER(author) LIKE :2 OR UPPER(isbn) LIKE :3 OR UPPER(genre) LIKE :4 ORDER BY title FETCH FIRST 20 ROWS ONLY", [like, like, like, like])
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"book_id": r[0], "isbn": r[1], "title": r[2], "author": r[3], "genre": r[4], "publisher": r[5], "total_copies": r[6], "available_copies": r[7]} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/me')
@staff_required
def api_staff_me():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT employee_id, full_name, email, staff_role FROM staff WHERE employee_id = :1", [session['user_id']])
        r = cur.fetchone(); cur.close(); conn.close()
        return jsonify({"success": True, "data": {"employee_id": r[0], "full_name": r[1], "email": r[2], "staff_role": r[3]}})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/dashboard-stats')
@staff_required
def api_staff_stats():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM books"); b = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM book_issues WHERE return_date IS NULL AND due_date < SYSDATE"); o = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM students WHERE is_active = 1"); m = cur.fetchone()[0]
        cur.execute("SELECT NVL(SUM(fine_amount),0) FROM fines WHERE paid = 0"); f = float(cur.fetchone()[0])
        cur.close(); conn.close()
        return jsonify({"success": True, "data": {"total_books": b, "overdue_count": o, "active_members": m, "unpaid_fines": f}})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/recent-issues')
@staff_required
def api_staff_recent():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT b.title, b.author, s.full_name, i.student_id, i.issue_date, i.due_date, i.return_date FROM book_issues i JOIN books b ON i.book_id = b.book_id JOIN students s ON i.student_id = s.student_id ORDER BY i.issue_date DESC FETCH FIRST 10 ROWS ONLY")
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"title": r[0], "author": r[1], "student_name": r[2], "student_id": r[3], "issue_date": str(r[4]), "due_date": str(r[5]), "return_date": str(r[6]) if r[6] else None} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/overdue')
@staff_required
def api_staff_overdue():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT s.full_name, i.student_id, b.title, TRUNC(SYSDATE - i.due_date) FROM book_issues i JOIN books b ON i.book_id = b.book_id JOIN students s ON i.student_id = s.student_id WHERE i.return_date IS NULL AND i.due_date < SYSDATE ORDER BY 4 DESC FETCH FIRST 10 ROWS ONLY")
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"student_name": r[0], "student_id": r[1], "title": r[2], "days_overdue": int(r[3])} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/books', methods=['POST'])
@staff_required
def api_add_book():
    d = request.get_json()
    try:
        conn = get_db(); cur = conn.cursor()
        c = int(d.get('total_copies', 1))
        cur.execute("INSERT INTO books (isbn, title, author, genre, publisher, publish_year, total_copies, available_copies, added_by) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9)", [d['isbn'], d['title'], d['author'], d.get('genre'), d.get('publisher'), d.get('publish_year'), c, c, session['user_id']])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except oracledb.IntegrityError:
        return jsonify({"success": False, "message": "ISBN already exists."})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/books/<int:book_id>', methods=['DELETE'])
@staff_required
def api_delete_book(book_id):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("DELETE FROM books WHERE book_id = :1", [book_id])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/members')
@staff_required
def api_get_members():
    q = request.args.get('q', '').strip()
    try:
        conn = get_db(); cur = conn.cursor()
        if q:
            like = '%' + q.upper() + '%'
            cur.execute("SELECT s.student_id, s.full_name, s.email, s.department, s.is_active, COUNT(i.issue_id), NVL(SUM(CASE WHEN f.paid=0 THEN f.fine_amount ELSE 0 END),0) FROM students s LEFT JOIN book_issues i ON s.student_id=i.student_id LEFT JOIN fines f ON s.student_id=f.student_id WHERE UPPER(s.full_name) LIKE :1 OR UPPER(s.student_id) LIKE :2 GROUP BY s.student_id,s.full_name,s.email,s.department,s.is_active ORDER BY s.full_name", [like, like])
        else:
            cur.execute("SELECT s.student_id, s.full_name, s.email, s.department, s.is_active, COUNT(i.issue_id), NVL(SUM(CASE WHEN f.paid=0 THEN f.fine_amount ELSE 0 END),0) FROM students s LEFT JOIN book_issues i ON s.student_id=i.student_id LEFT JOIN fines f ON s.student_id=f.student_id GROUP BY s.student_id,s.full_name,s.email,s.department,s.is_active ORDER BY s.full_name")
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"student_id": r[0], "full_name": r[1], "email": r[2], "department": r[3], "is_active": bool(r[4]), "books_issued": int(r[5]), "fine_due": float(r[6])} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/members', methods=['POST'])
@staff_required
def api_add_member():
    d = request.get_json()
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("INSERT INTO students (student_id, full_name, email, phone, department, password_hash) VALUES (:1,:2,:3,:4,:5,:6)", [d['student_id'], d['full_name'], d['email'], d.get('phone'), d.get('department'), hash_pw(d['password'])])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except oracledb.IntegrityError:
        return jsonify({"success": False, "message": "Student ID or email already exists."})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/members/<student_id>/toggle', methods=['POST'])
@staff_required
def api_toggle_member(student_id):
    d = request.get_json()
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE students SET is_active = :1 WHERE student_id = :2", [int(d['is_active']), student_id])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/issue', methods=['POST'])
@staff_required
def api_issue_book():
    d = request.get_json()
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT available_copies FROM books WHERE book_id = :1", [d['book_id']])
        r = cur.fetchone()
        if not r or r[0] < 1:
            return jsonify({"success": False, "message": "Book not available."})
        cur.execute("INSERT INTO book_issues (book_id, student_id, issued_by, due_date) VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'))", [d['book_id'], d['student_id'], session['user_id'], d['due_date']])
        cur.execute("UPDATE books SET available_copies = available_copies - 1 WHERE book_id = :1", [d['book_id']])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/student-issued/<student_id>')
@staff_required
def api_student_issued_return(student_id):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT i.issue_id, b.title, b.author, i.due_date FROM book_issues i JOIN books b ON i.book_id=b.book_id WHERE i.student_id=:1 AND i.return_date IS NULL ORDER BY i.issue_date DESC", [student_id])
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"issue_id": r[0], "title": r[1], "author": r[2], "due_date": str(r[3])} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/return/<int:issue_id>', methods=['POST'])
@staff_required
def api_return_book(issue_id):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT book_id, student_id, due_date FROM book_issues WHERE issue_id=:1 AND return_date IS NULL", [issue_id])
        r = cur.fetchone()
        if not r: return jsonify({"success": False, "message": "Not found."})
        book_id, student_id, due_date = r
        cur.execute("UPDATE book_issues SET return_date=SYSDATE, status='returned' WHERE issue_id=:1", [issue_id])
        cur.execute("UPDATE books SET available_copies=available_copies+1 WHERE book_id=:1", [book_id])
        cur.execute("SELECT GREATEST(TRUNC(SYSDATE)-TRUNC(:1),0) FROM dual", [due_date])
        days = int(cur.fetchone()[0]); fine = days * 2
        if fine > 0:
            cur.execute("INSERT INTO fines (issue_id, student_id, fine_amount) VALUES (:1,:2,:3)", [issue_id, student_id, fine])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "fine": fine})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/fines')
@staff_required
def api_staff_fines():
    q = request.args.get('q', '').strip()
    try:
        conn = get_db(); cur = conn.cursor()
        # Existing fines from returned books
        if q:
            like = '%' + q.upper() + '%'
            cur.execute("""
                SELECT f.fine_id, s.full_name, s.student_id, b.title, f.fine_amount, f.paid
                FROM fines f
                JOIN students s ON f.student_id = s.student_id
                JOIN book_issues i ON f.issue_id = i.issue_id
                JOIN books b ON i.book_id = b.book_id
                WHERE UPPER(s.full_name) LIKE :1 OR UPPER(s.student_id) LIKE :2
                ORDER BY f.paid, f.fine_amount DESC
            """, [like, like])
        else:
            cur.execute("""
                SELECT f.fine_id, s.full_name, s.student_id, b.title, f.fine_amount, f.paid
                FROM fines f
                JOIN students s ON f.student_id = s.student_id
                JOIN book_issues i ON f.issue_id = i.issue_id
                JOIN books b ON i.book_id = b.book_id
                ORDER BY f.paid, f.fine_amount DESC
            """)
        rows = cur.fetchall()
        data = [{"fine_id": r[0], "student_name": r[1], "student_id": r[2],
                 "title": r[3], "fine_amount": float(r[4]), "paid": bool(r[5]),
                 "accruing": False} for r in rows]

        # ── NEW: Add accruing fines from currently overdue books ──
        if q:
            like = '%' + q.upper() + '%'
            cur.execute("""
                SELECT s.full_name, s.student_id, b.title,
                       GREATEST(TRUNC(SYSDATE) - TRUNC(i.due_date), 0) * 2 AS running_fine
                FROM book_issues i
                JOIN students s ON i.student_id = s.student_id
                JOIN books b ON i.book_id = b.book_id
                WHERE i.return_date IS NULL AND i.due_date < SYSDATE
                  AND (UPPER(s.full_name) LIKE :1 OR UPPER(s.student_id) LIKE :2)
            """, [like, like])
        else:
            cur.execute("""
                SELECT s.full_name, s.student_id, b.title,
                       GREATEST(TRUNC(SYSDATE) - TRUNC(i.due_date), 0) * 2 AS running_fine
                FROM book_issues i
                JOIN students s ON i.student_id = s.student_id
                JOIN books b ON i.book_id = b.book_id
                WHERE i.return_date IS NULL AND i.due_date < SYSDATE
            """)
        overdue = cur.fetchall()
        for r in overdue:
            if float(r[3]) > 0:
                data.append({
                    "fine_id": None,
                    "student_name": r[0],
                    "student_id": r[1],
                    "title": r[2] + " (accruing)",
                    "fine_amount": float(r[3]),
                    "paid": False,
                    "accruing": True
                })

        cur.close(); conn.close()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/fines/<int:fine_id>/pay', methods=['POST'])
@staff_required
def api_pay_fine(fine_id):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE fines SET paid=1, paid_date=SYSDATE WHERE fine_id=:1", [fine_id])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/staff/reports')
@staff_required
def api_staff_reports():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT b.title, COUNT(*) FROM book_issues i JOIN books b ON i.book_id=b.book_id GROUP BY b.title ORDER BY 2 DESC FETCH FIRST 5 ROWS ONLY")
        tb = [{"title": r[0], "issue_count": r[1]} for r in cur.fetchall()]
        cur.execute("SELECT s.full_name, COUNT(*) FROM book_issues i JOIN students s ON i.student_id=s.student_id GROUP BY s.full_name ORDER BY 2 DESC FETCH FIRST 5 ROWS ONLY")
        bw = [{"full_name": r[0], "issue_count": r[1]} for r in cur.fetchall()]
        cur.execute("SELECT NVL(SUM(fine_amount),0), NVL(SUM(CASE WHEN paid=1 THEN fine_amount END),0), NVL(SUM(CASE WHEN paid=0 THEN fine_amount END),0) FROM fines")
        fr = cur.fetchone(); cur.close(); conn.close()
        return jsonify({"success": True, "data": {"top_books": tb, "top_borrowers": bw, "fines_summary": {"total": float(fr[0]), "paid": float(fr[1]), "unpaid": float(fr[2])}}})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/student/reserve', methods=['POST'])
@login_required
def api_reserve_book():
    d = request.get_json()
    try:
        conn = get_db(); cur = conn.cursor()
        # Check if already reserved
        cur.execute("SELECT COUNT(*) FROM reservations WHERE student_id=:1 AND book_id=:2 AND status='pending'", [session['user_id'], d['book_id']])
        if cur.fetchone()[0] > 0:
            return jsonify({"success": False, "message": "You already have a pending reservation for this book."})
        # Check if already issued
        cur.execute("SELECT COUNT(*) FROM book_issues WHERE student_id=:1 AND book_id=:2 AND return_date IS NULL", [session['user_id'], d['book_id']])
        if cur.fetchone()[0] > 0:
            return jsonify({"success": False, "message": "You already have this book issued."})
        cur.execute("INSERT INTO reservations (book_id, student_id) VALUES (:1, :2)", [d['book_id'], session['user_id']])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "message": "Book reserved successfully!"})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

# ============================================================
#  BORROW REQUEST ROUTES
#  Add these to app.py just before:  if __name__ == '__main__':
# ============================================================

# ── Student: Request to borrow a book ──
@app.route('/api/student/request-borrow', methods=['POST'])
@login_required
def api_request_borrow():
    d = request.get_json()
    try:
        conn = get_db(); cur = conn.cursor()
        # Check already has a pending request for this book
        cur.execute("SELECT COUNT(*) FROM borrow_requests WHERE student_id=:1 AND book_id=:2 AND status='pending'", [session['user_id'], d['book_id']])
        if cur.fetchone()[0] > 0:
            return jsonify({"success": False, "message": "You already have a pending request for this book."})
        # Check if already issued
        cur.execute("SELECT COUNT(*) FROM book_issues WHERE student_id=:1 AND book_id=:2 AND return_date IS NULL", [session['user_id'], d['book_id']])
        if cur.fetchone()[0] > 0:
            return jsonify({"success": False, "message": "You already have this book issued."})
        cur.execute("INSERT INTO borrow_requests (book_id, student_id) VALUES (:1,:2)", [d['book_id'], session['user_id']])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "message": "Borrow request sent! Wait for staff approval."})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

# ── Student: View their borrow requests ──
@app.route('/api/student/borrow-requests')
@login_required
def api_student_borrow_requests():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT r.request_id, b.title, b.author, r.request_date, r.status, r.remarks
            FROM borrow_requests r
            JOIN books b ON r.book_id = b.book_id
            WHERE r.student_id = :1
            ORDER BY r.request_date DESC
        """, [session['user_id']])
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"request_id": r[0], "title": r[1], "author": r[2], "request_date": str(r[3]), "status": r[4], "remarks": r[5]} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

# ── Student: Cancel a pending request ──
@app.route('/api/student/borrow-requests/<int:req_id>/cancel', methods=['POST'])
@login_required
def api_cancel_borrow_request(req_id):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE borrow_requests SET status='rejected' WHERE request_id=:1 AND student_id=:2 AND status='pending'", [req_id, session['user_id']])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "message": "Request cancelled."})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

# ── Staff: View all pending borrow requests ──
@app.route('/api/staff/borrow-requests')
@staff_required
def api_staff_borrow_requests():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT r.request_id, s.full_name, s.student_id, b.title, b.author,
                   b.available_copies, r.request_date, r.status
            FROM borrow_requests r
            JOIN students s ON r.student_id = s.student_id
            JOIN books b ON r.book_id = b.book_id
            ORDER BY CASE r.status WHEN 'pending' THEN 1 ELSE 2 END, r.request_date DESC
        """)
        rows = cur.fetchall(); cur.close(); conn.close()
        return jsonify({"success": True, "data": [{"request_id": r[0], "student_name": r[1], "student_id": r[2], "title": r[3], "author": r[4], "available_copies": r[5], "request_date": str(r[6]), "status": r[7]} for r in rows]})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

# ── Staff: Approve a borrow request (auto-issues the book) ──
@app.route('/api/staff/borrow-requests/<int:req_id>/approve', methods=['POST'])
@staff_required
def api_approve_borrow(req_id):
    d = request.get_json()
    try:
        conn = get_db(); cur = conn.cursor()
        # Get request details
        cur.execute("SELECT book_id, student_id FROM borrow_requests WHERE request_id=:1 AND status='pending'", [req_id])
        r = cur.fetchone()
        if not r:
            return jsonify({"success": False, "message": "Request not found or already processed."})
        book_id, student_id = r
        # Check availability
        cur.execute("SELECT available_copies FROM books WHERE book_id=:1", [book_id])
        avail = cur.fetchone()
        if not avail or avail[0] < 1:
            return jsonify({"success": False, "message": "Book is not available right now."})
        # Set due date (14 days from now by default, or custom)
        due_date = d.get('due_date', '')
        if due_date:
            cur.execute("INSERT INTO book_issues (book_id, student_id, issued_by, due_date) VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'))", [book_id, student_id, session['user_id'], due_date])
        else:
            cur.execute("INSERT INTO book_issues (book_id, student_id, issued_by, due_date) VALUES (:1,:2,:3,SYSDATE+14)", [book_id, student_id, session['user_id']])
        # Decrease available copies
        cur.execute("UPDATE books SET available_copies=available_copies-1 WHERE book_id=:1", [book_id])
        # Mark request as approved
        cur.execute("UPDATE borrow_requests SET status='approved', reviewed_by=:1, reviewed_date=SYSDATE, remarks=:2 WHERE request_id=:3", [session['user_id'], d.get('remarks', 'Approved'), req_id])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "message": "Request approved and book issued!"})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

# ── Staff: Reject a borrow request ──
@app.route('/api/staff/borrow-requests/<int:req_id>/reject', methods=['POST'])
@staff_required
def api_reject_borrow(req_id):
    d = request.get_json()
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE borrow_requests SET status='rejected', reviewed_by=:1, reviewed_date=SYSDATE, remarks=:2 WHERE request_id=:3 AND status='pending'", [session['user_id'], d.get('remarks', 'Rejected'), req_id])
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "message": "Request rejected."})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})

@app.route('/api/student/change-password', methods=['POST'])
@login_required
def api_change_password():
    d = request.get_json()
    current_pw = d.get('current_password', '')
    new_pw     = d.get('new_password', '')
    if not current_pw or not new_pw:
        return jsonify({"success": False, "message": "All fields are required."})
    if len(new_pw) < 6:
        return jsonify({"success": False, "message": "New password must be at least 6 characters."})
    try:
        conn = get_db(); cur = conn.cursor()
        # Verify current password
        cur.execute(
            "SELECT student_id FROM students WHERE student_id = :1 AND password_hash = :2",
            [session['user_id'], hash_pw(current_pw)]
        )
        if not cur.fetchone():
            return jsonify({"success": False, "message": "Current password is incorrect."})
        # Update to new password
        cur.execute(
            "UPDATE students SET password_hash = :1 WHERE student_id = :2",
            [hash_pw(new_pw), session['user_id']]
        )
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "message": "Password changed successfully!"})
    except Exception as e:
        print(f"[ERR] {e}"); return jsonify({"success": False, "message": str(e)})
        
if __name__ == '__main__':
    app.run(debug=True, port=5000)
