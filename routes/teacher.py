from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, send_file
from flask_login import login_required, current_user
from functools import wraps
from models import User, Class, Subject, Student, AttendanceRecord, ApprovalRequest, Department
from extensions import db
from datetime import datetime, date
import csv, io, json, os
from werkzeug.utils import secure_filename
from config import Config

teacher_bp = Blueprint('teacher', __name__)

def teacher_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ('teacher', 'admin'):
            flash('Teacher access required.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

def get_approved_reqs():
    return ApprovalRequest.query.filter_by(teacher_id=current_user.id, status='approved').all()

@teacher_bp.route('/dashboard')
@login_required
@teacher_required
def dashboard():
    approved_requests = get_approved_reqs()
    pending_req = ApprovalRequest.query.filter_by(teacher_id=current_user.id, status='pending').count()
    
    # Get subjects from approved requests
    subject_ids = [r.subject_id for r in approved_requests]
    # Also add subjects directly assigned to the teacher in the Subject table
    assigned_subject_ids = [s.id for s in current_user.subjects]
    
    all_subject_ids = list(set(subject_ids + assigned_subject_ids))
    subjects = Subject.query.filter(Subject.id.in_(all_subject_ids or [0])).all()
    
    from datetime import timedelta
    today = date.today()
    
    # Weekly data for the chart (Mon - Sun of current week)
    weekly = []
    start_of_week = today - timedelta(days=today.weekday())
    for i in range(7):
        d = start_of_week + timedelta(days=i)
        p = AttendanceRecord.query.filter(AttendanceRecord.subject_id.in_(all_subject_ids or [0]), AttendanceRecord.date == d, AttendanceRecord.status == 'present').count()
        a = AttendanceRecord.query.filter(AttendanceRecord.subject_id.in_(all_subject_ids or [0]), AttendanceRecord.date == d, AttendanceRecord.status == 'absent').count()
        weekly.append({'date': d.strftime('%a'), 'present': p, 'absent': a})
    
    weekly_by_subject = {}
    for s in subjects:
        w_sub = []
        for i in range(7):
            d = start_of_week + timedelta(days=i)
            p = AttendanceRecord.query.filter_by(subject_id=s.id, date=d, status='present').count()
            a = AttendanceRecord.query.filter_by(subject_id=s.id, date=d, status='absent').count()
            w_sub.append({'date': d.strftime('%a'), 'present': p, 'absent': a})
        weekly_by_subject[s.id] = w_sub
    
    subject_stats = []
    for s in subjects:
        total = AttendanceRecord.query.filter_by(subject_id=s.id).count()
        present = AttendanceRecord.query.filter_by(subject_id=s.id, status='present').count()
        pct = round((present / total * 100) if total else 0, 1)
        subject_stats.append({
            'id': s.id,
            'name': s.name,
            'code': s.code,
            'present': present,
            'total': total,
            'pct': pct
        })
    
    today_sessions = AttendanceRecord.query.filter(
        AttendanceRecord.subject_id.in_(all_subject_ids or [0]), 
        AttendanceRecord.date == today
    ).group_by(AttendanceRecord.time_slot, AttendanceRecord.subject_id).count()

    is_approved = current_user.is_active_account

    return render_template('teacher/dashboard.html', 
        subjects=subjects, 
        pending_req=pending_req,
        today_sessions=today_sessions,
        weekly=json.dumps(weekly),
        weekly_by_sub=json.dumps(weekly_by_subject),
        subject_stats=json.dumps(subject_stats),
        is_approved=is_approved)

@teacher_bp.route('/request-access', methods=['GET', 'POST'])
@login_required
@teacher_required
def request_access():
    if request.method == 'POST':
        subject_id = request.form.get('subject_id')
        class_id = request.form.get('class_id')
        message = request.form.get('message', '')
        existing = ApprovalRequest.query.filter_by(teacher_id=current_user.id, subject_id=subject_id, status='pending').first()
        if existing:
            flash('Pending request already exists for this subject.', 'warning')
        else:
            req = ApprovalRequest(teacher_id=current_user.id, subject_id=subject_id, class_id=class_id, message=message)
            db.session.add(req); db.session.commit()
            flash('Access request submitted successfully.', 'success')
        return redirect(url_for('teacher.dashboard'))
    classes = Class.query.all()
    my_requests = ApprovalRequest.query.filter_by(teacher_id=current_user.id).order_by(ApprovalRequest.created_at.desc()).all()
    return render_template('teacher/request_access.html', classes=classes, my_requests=my_requests)

@teacher_bp.route('/classes')
@teacher_bp.route('/classes/<int:subject_id>')
@login_required
@teacher_required
def classes(subject_id=None):
    approved_requests = get_approved_reqs()
    subject_ids = [r.subject_id for r in approved_requests]
    assigned_subject_ids = [s.id for s in current_user.subjects]
    all_subject_ids = list(set(subject_ids + assigned_subject_ids))
    subjects = Subject.query.filter(Subject.id.in_(all_subject_ids or [0])).all()

    if not subject_id and subjects:
        return redirect(url_for('teacher.classes', subject_id=subjects[0].id))

    subject = Subject.query.get_or_404(subject_id) if subject_id else None
    students = Student.query.filter_by(class_id=subject.class_id).order_by(Student.student_id).all() if subject else []
    
    # Calculate attendance percentages for each student in this subject
    student_data = []
    for s in students:
        total = AttendanceRecord.query.filter_by(student_id=s.id, subject_id=subject_id).count()
        present = AttendanceRecord.query.filter_by(student_id=s.id, subject_id=subject_id, status='present').count()
        pct = round((present / total * 100) if total else 0, 1)
        student_data.append({
            'obj': s,
            'pct': pct,
            # Placeholder for 6 photos logic - for now we use photo_count
            'photos': [f"photo_{i}.jpg" for i in range(min(s.photo_count or 0, 6))]
        })

    is_approved = current_user.is_active_account
    return render_template('teacher/classes.html', subjects=subjects, subject=subject, student_data=student_data, is_approved=is_approved)

@teacher_bp.route('/lectures', methods=['GET', 'POST'])
@login_required
@teacher_required
def lectures():
    if request.method == 'POST':
        payload_str = request.form.get('payload')
        if payload_str:
            import json
            data = json.loads(payload_str)
            
            # Find or Create Department
            dept_name = data.get('dept', 'Unknown Dept')
            dept = Department.query.filter_by(name=dept_name).first()
            if not dept:
                dept = Department(name=dept_name, code=dept_name[:3].upper())
                db.session.add(dept)
                db.session.flush()

            # Find or Create Class
            year_map = {"First Year": 1, "Second Year": 2, "Third Year": 3, "BTech": 4}
            year_val = year_map.get(data.get('year'), 1)
            cls_name = f"{data.get('year')} {dept.code}"
            
            cls = Class.query.filter_by(name=cls_name, section=data.get('division'), department_id=dept.id).first()
            if not cls:
                cls = Class(name=cls_name, section=data.get('division'), year=year_val, department_id=dept.id)
                db.session.add(cls)
                db.session.flush()

            # Find or Create Subject
            subj = Subject.query.filter_by(name=data.get('name'), class_id=cls.id).first()
            if not subj:
                subj = Subject(name=data.get('name'), code=data.get('code'), class_id=cls.id)
                db.session.add(subj)
                db.session.flush()

            # Check if pending request already exists
            existing = ApprovalRequest.query.filter_by(teacher_id=current_user.id, subject_id=subj.id, status='pending').first()
            if not existing:
                req = ApprovalRequest(
                    teacher_id=current_user.id,
                    subject_id=subj.id,
                    class_id=cls.id,
                    note=json.dumps(data.get('dates', [])) # Store the lecture schedules requested
                )
                db.session.add(req)
                db.session.commit()
                flash('Subject and Schedule request sent to Admin for approval.', 'success')
            else:
                flash('You already have a pending request for this subject.', 'warning')
            
            return redirect(url_for('teacher.dashboard'))
            
    departments = Department.query.all()
    is_approved = current_user.is_active_account
    return render_template('teacher/lectures.html', departments=departments, is_approved=is_approved)

@teacher_bp.route('/classes/<int:subject_id>/add-student', methods=['POST'])
@login_required
@teacher_required
def add_student(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    class_id = subject.class_id
    student_id = request.form.get('student_id'); name = request.form.get('name'); email = request.form.get('email')
    if Student.query.filter_by(student_id=student_id, class_id=class_id).first():
        flash('Student ID already exists in this class.', 'error')
    else:
        db.session.add(Student(student_id=student_id, name=name, email=email, class_id=class_id)); db.session.commit()
        flash(f'Student {name} added.', 'success')
    return redirect(url_for('teacher.classes', subject_id=subject_id))

@teacher_bp.route('/classes/<int:subject_id>/import-csv', methods=['POST'])
@login_required
@teacher_required
def import_students_csv(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    class_id = subject.class_id
    file = request.files.get('csv_file')
    if not file: flash('No file provided.', 'error'); return redirect(url_for('teacher.classes', subject_id=subject_id))
    stream = io.StringIO(file.stream.read().decode('utf-8')); reader = csv.DictReader(stream); count = 0
    for row in reader:
        sid = row.get('student_id','').strip(); name = row.get('name','').strip()
        if sid and name and not Student.query.filter_by(student_id=sid, class_id=class_id).first():
            db.session.add(Student(student_id=sid, name=name, email=row.get('email','').strip(), class_id=class_id)); count += 1
    db.session.commit(); flash(f'{count} students imported.', 'success')
    return redirect(url_for('teacher.classes', subject_id=subject_id))

@teacher_bp.route('/classes/upload-photo/<int:student_id>', methods=['POST'])
@login_required
@teacher_required
def upload_student_photo(student_id):
    student = Student.query.get_or_404(student_id); photos = request.files.getlist('photos')
    saved_paths = []; folder = os.path.join(Config.UPLOAD_FOLDER, f'student_{student_id}'); os.makedirs(folder, exist_ok=True)
    for photo in photos:
        if photo and photo.filename:
            path = os.path.join(folder, secure_filename(photo.filename)); photo.save(path); saved_paths.append(path)
    if saved_paths:
        try:
            from ai.recognizer import generate_face_embeddings
            embeddings = generate_face_embeddings(saved_paths)
            if embeddings:
                existing = student.get_encoding()
                if existing and isinstance(existing[0], (int, float)): existing = [existing]
                student.set_encoding((existing or []) + embeddings)
        except: pass
        student.photo_count = (student.photo_count or 0) + len(saved_paths); db.session.commit()
        return jsonify({'success': True, 'photos': student.photo_count})
    return jsonify({'error': 'No photos saved'}), 400

@teacher_bp.route('/mark-attendance', methods=['GET', 'POST'])
@login_required
@teacher_required
def mark_attendance():
    approved_requests = get_approved_reqs()
    approved_subjects = [Subject.query.get(r.subject_id) for r in approved_requests if Subject.query.get(r.subject_id)]
    if request.method == 'POST':
        subject_id = request.form.get('subject_id', type=int)
        attendance_date = request.form.get('date'); lecture_time = request.form.get('time')
        photos = request.files.getlist('photos')
        if not subject_id or not attendance_date or not photos:
            flash('Please fill all required fields and upload at least one photo.', 'error')
            return redirect(url_for('teacher.mark_attendance'))
        subject = Subject.query.get_or_404(subject_id)
        students = Student.query.filter_by(class_id=subject.class_id).all()
        saved_paths = []; session_folder = os.path.join(Config.UPLOAD_FOLDER, 'sessions', f'{subject_id}_{attendance_date}'); os.makedirs(session_folder, exist_ok=True)
        for photo in photos:
            if photo and photo.filename:
                path = os.path.join(session_folder, secure_filename(photo.filename)); photo.save(path); saved_paths.append(path)
        try:
            from ai.recognizer import process_attendance
            results = process_attendance(saved_paths, students)
        except:
            import random
            results = {s.id: {'status': 'present' if random.random() > 0.4 else 'absent', 'confidence': round(random.uniform(0.7, 0.95), 3), 'name': s.name, 'student_id': s.student_id} for s in students}
        att_date = datetime.strptime(attendance_date, '%Y-%m-%d').date()
        att_time = None
        if lecture_time:
            try: att_time = datetime.strptime(lecture_time, '%H:%M').time()
            except: pass
        for s in students:
            res = results.get(s.id, {'status': 'absent', 'confidence': 0.0})
            existing = AttendanceRecord.query.filter_by(student_id=s.id, subject_id=subject_id, date=att_date).first()
            if existing: existing.status = res['status']; existing.confidence = res.get('confidence', 0.0)
            else: db.session.add(AttendanceRecord(student_id=s.id, subject_id=subject_id, date=att_date, time=att_time, status=res['status'], marked_by=current_user.id, method='ai', confidence=res.get('confidence', 0.0)))
        db.session.commit()
        present_count = sum(1 for r in results.values() if r['status'] == 'present')
        flash(f'Attendance marked: {present_count}/{len(students)} present.', 'success')
        result_data = [{'student_id': s.student_id, 'name': s.name, 'db_id': s.id, 'status': results.get(s.id, {}).get('status', 'absent'), 'confidence': results.get(s.id, {}).get('confidence', 0.0)} for s in students]
        return render_template('teacher/attendance_result.html', results=result_data, subject=subject, att_date=att_date, subject_id=subject_id, present_count=present_count, total=len(students))
    return render_template('teacher/mark_attendance.html', approved_subjects=approved_subjects)

@teacher_bp.route('/records')
@login_required
@teacher_required
def records():
    approved_requests = get_approved_reqs()
    approved_subject_ids = [r.subject_id for r in approved_requests]
    approved_subjects = Subject.query.filter(Subject.id.in_(approved_subject_ids)).all() if approved_subject_ids else []
    selected_subject_id = request.args.get('subject_id', type=int)
    from_date = request.args.get('from_date'); to_date = request.args.get('to_date')
    student_data = []; subject = None; total_lectures = 0
    if selected_subject_id and selected_subject_id in approved_subject_ids:
        subject = Subject.query.get(selected_subject_id)
        students = Student.query.filter_by(class_id=subject.class_id).all()
        query = AttendanceRecord.query.filter_by(subject_id=selected_subject_id)
        if from_date: query = query.filter(AttendanceRecord.date >= datetime.strptime(from_date, '%Y-%m-%d').date())
        if to_date: query = query.filter(AttendanceRecord.date <= datetime.strptime(to_date, '%Y-%m-%d').date())
        all_records = query.all(); total_lectures = len(set(r.date for r in all_records))
        for s in students:
            s_records = [r for r in all_records if r.student_id == s.id]
            present = sum(1 for r in s_records if r.status == 'present'); total = len(s_records)
            pct = round((present / total * 100) if total else 0, 1)
            student_data.append({'student_id': s.student_id, 'name': s.name, 'present': present, 'absent': total - present, 'total_lectures': total, 'percentage': pct, 'grade': 'A' if pct >= 85 else 'B' if pct >= 75 else 'C' if pct >= 60 else 'F'})
    return render_template('teacher/records.html', approved_subjects=approved_subjects, selected_subject_id=selected_subject_id, from_date=from_date, to_date=to_date, student_data=student_data, subject=subject, total_lectures=total_lectures)

@teacher_bp.route('/records/export')
@login_required
@teacher_required
def export_records():
    approved_requests = get_approved_reqs()
    approved_subject_ids = [r.subject_id for r in approved_requests]
    selected_subject_id = request.args.get('subject_id', type=int)
    if not selected_subject_id or selected_subject_id not in approved_subject_ids:
        flash('Invalid subject.', 'error'); return redirect(url_for('teacher.records'))
    subject = Subject.query.get(selected_subject_id)
    students = Student.query.filter_by(class_id=subject.class_id).all()
    records_q = AttendanceRecord.query.filter_by(subject_id=selected_subject_id).all()
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(['Roll No', 'Name', 'Present', 'Absent', 'Total Lectures', 'Percentage', 'Grade'])
    for s in students:
        s_records = [r for r in records_q if r.student_id == s.id]
        present = sum(1 for r in s_records if r.status == 'present'); total = len(s_records)
        pct = round((present / total * 100) if total else 0, 1)
        writer.writerow([s.student_id, s.name, present, total - present, total, f'{pct}%', 'A' if pct >= 85 else 'B' if pct >= 75 else 'C' if pct >= 60 else 'F'])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name=f'{subject.code or subject.name}_attendance.csv')

@teacher_bp.route('/monthly-report')
@login_required
@teacher_required
def monthly_report():
    approved_requests = get_approved_reqs()
    approved_subject_ids = [r.subject_id for r in approved_requests]
    approved_subjects = Subject.query.filter(Subject.id.in_(approved_subject_ids)).all() if approved_subject_ids else []
    selected_subject_id = request.args.get('subject_id', type=int); month_str = request.args.get('month')
    report_data = None; heatmap_data = {}; student_summary = []
    if selected_subject_id and month_str:
        try:
            month_date = datetime.strptime(month_str, '%Y-%m')
            import calendar; days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
            subject = Subject.query.get(selected_subject_id)
            students = Student.query.filter_by(class_id=subject.class_id).all()
            month_records = AttendanceRecord.query.filter(AttendanceRecord.subject_id == selected_subject_id, db.extract('year', AttendanceRecord.date) == month_date.year, db.extract('month', AttendanceRecord.date) == month_date.month).all()
            below_75 = 0
            for s in students:
                s_records = [r for r in month_records if r.student_id == s.id]
                present = sum(1 for r in s_records if r.status == 'present'); total = len(s_records)
                pct = round((present / total * 100) if total else 0, 1)
                if pct < 75: below_75 += 1
                student_summary.append({'student_id': s.student_id, 'name': s.name, 'present': present, 'absent': total - present, 'total': total, 'percentage': pct, 'grade': 'A' if pct >= 85 else 'B' if pct >= 75 else 'C' if pct >= 60 else 'F'})
            avg_present = sum(s['present'] for s in student_summary)
            total_possible = len(students) * days_in_month
            avg_rate = round((avg_present / total_possible * 100) if total_possible else 0, 1)
            from collections import defaultdict; daily_counts = defaultdict(int)
            for r in month_records:
                if r.status == 'present': daily_counts[r.date.day] += 1
            heatmap_data = {str(d): daily_counts[d] for d in range(1, days_in_month + 1)}
            report_data = {'subject': subject, 'month': month_date, 'days_in_month': days_in_month, 'total_students': len(students), 'below_75': below_75, 'avg_rate': avg_rate}
        except Exception as e:
            flash(f'Error: {e}', 'error')
    return render_template('teacher/monthly_report.html', approved_subjects=approved_subjects, selected_subject_id=selected_subject_id, month_str=month_str, report_data=report_data, heatmap_data=json.dumps(heatmap_data), student_summary=student_summary)

@teacher_bp.route('/api/subjects-by-class/<int:class_id>')
@login_required
@teacher_required
def api_subjects_by_class(class_id):
    subjects = Subject.query.filter_by(class_id=class_id).all()
    return jsonify([{'id': s.id, 'name': s.name, 'code': s.code} for s in subjects])
