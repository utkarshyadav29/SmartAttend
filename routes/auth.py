from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard') if current_user.role == 'admin' else url_for('teacher.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'teacher')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.role == role:
            login_user(user, remember=request.form.get('remember') == 'on')
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('admin.dashboard') if role == 'admin' else url_for('teacher.dashboard'))
        flash('Invalid credentials. Please check your username, password, and role.', 'error')

    return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard') if current_user.role == 'admin' else url_for('teacher.dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if User.query.filter_by(username=username).first():
            flash('Username is already taken. Please choose another.', 'error')
            return redirect(url_for('auth.register'))
            
        if User.query.filter_by(email=email).first():
            flash('Email is already registered. Please login.', 'error')
            return redirect(url_for('auth.register'))

        # Create new Teacher user (inactive until approved)
        new_teacher = User(
            name=name,
            username=username,
            email=email,
            role='teacher',
            employee_id=f"TCH{User.query.filter_by(role='teacher').count() + 1:03d}",
            department='Pending',
            is_active_account=False
        )
        new_teacher.set_password(password)
        
        from extensions import db
        db.session.add(new_teacher)
        db.session.commit()
        
        flash('Registration successful! Please wait for admin approval before logging in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
