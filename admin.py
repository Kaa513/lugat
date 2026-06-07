
"""Admin panel for Lugat dictionary."""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database import get_connection
import re
import os

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "lugat2024")

login_attempts = {}
#ADMIN_PASSWORD = "lugat2024"  # Измени на свой пароль!

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    ip = request.remote_addr
    attempts = login_attempts.get(ip, 0)

    if attempts >= 5:
        flash('Juda ko\'p urinish! 15 daqiqadan keyin qayta urining.')
        return render_template('admin_login.html')

    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            login_attempts[ip] = 0
            return redirect(url_for('admin.index'))
        login_attempts[ip] = attempts + 1
        flash(f'Noto\'g\'ri parol! {5 - attempts - 1} ta urinish qoldi.')
    return render_template('admin_login.html')


@admin_bp.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin.login'))


@admin_bp.route('/')
@login_required
def index():
    page = int(request.args.get('page', 1))
    q = request.args.get('q', '').strip()
    per_page = 50
    offset = (page - 1) * per_page

    with get_connection() as conn:
        if q:
            words = conn.execute(
                "SELECT * FROM words WHERE chinese LIKE ? OR uzbek LIKE ? OR english LIKE ? LIMIT ? OFFSET ?",
                (f'%{q}%', f'%{q}%', f'%{q}%', per_page, offset)
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) as c FROM words WHERE chinese LIKE ? OR uzbek LIKE ? OR english LIKE ?",
                (f'%{q}%', f'%{q}%', f'%{q}%')
            ).fetchone()['c']
        else:
            words = conn.execute(
                "SELECT * FROM words LIMIT ? OFFSET ?", (per_page, offset)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) as c FROM words").fetchone()['c']

    return render_template('admin_index.html', words=words, page=page,
                           total=total, per_page=per_page, q=q)


@admin_bp.route('/edit/<int:word_id>', methods=['GET', 'POST'])
@login_required
def edit(word_id):
    with get_connection() as conn:
        if request.method == 'POST':
            conn.execute(
                """UPDATE words SET uzbek=?, english=?, chinese=?, pinyin=?,
                   example_chinese=?, example_uzbek=? WHERE id=?""",
                (
                    request.form['uzbek'],
                    request.form['english'],
                    request.form['chinese'],
                    request.form['pinyin'],
                    request.form['example_chinese'],
                    request.form['example_uzbek'],
                    word_id
                )
            )
            return redirect(url_for('admin.index'))
        word = conn.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
    return render_template('admin_edit.html', word=word)


@admin_bp.route('/delete/<int:word_id>')
@login_required
def delete(word_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM words WHERE id=?", (word_id,))
    return redirect(url_for('admin.index'))


@admin_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO words (uzbek, english, chinese, pinyin,
                   example_chinese, example_uzbek) VALUES (?,?,?,?,?,?)""",
                (
                    request.form['uzbek'],
                    request.form['english'],
                    request.form['chinese'],
                    request.form['pinyin'],
                    request.form['example_chinese'],
                    request.form['example_uzbek'],
                )
            )
        return redirect(url_for('admin.index'))
    return render_template('admin_edit.html', word=None)


@admin_bp.route('/clean_cl')
@login_required
def clean_cl():
    """Remove CL:... garbage from uzbek and english fields."""
    with get_connection() as conn:
        words = conn.execute("SELECT id, uzbek, english FROM words").fetchall()
        count = 0
        for w in words:
            new_uzbek = re.sub(r'\s*\|\s*CL:[^\|]*', '', w['uzbek'] or '').strip()
            new_english = re.sub(r'\s*\|\s*CL:[^\|]*', '', w['english'] or '').strip()
            if new_uzbek != w['uzbek'] or new_english != w['english']:
                conn.execute(
                    "UPDATE words SET uzbek=?, english=? WHERE id=?",
                    (new_uzbek, new_english, w['id'])
                )
                count += 1
        conn.commit()
    flash(f'{count} ta so\'z tozalandi!')
    return redirect(url_for('admin.index'))