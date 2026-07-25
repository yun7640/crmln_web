# -*- coding: utf-8 -*-
"""CRMLN 측정결과 검토 대시보드 — 로그인 + 업로드 검토 + 관리자 + 사용자 설명서 (Flask)."""
import os, json, io, functools
from flask import (Flask, request, session, redirect, url_for, render_template,
                   send_file, send_from_directory, flash)
import auth
import review_engine

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
BASE = os.path.dirname(os.path.abspath(__file__))


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **k):
        if not session.get('user'):
            return redirect(url_for('login', next=request.path))
        return view(*a, **k)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*a, **k):
        if not session.get('user'):
            return redirect(url_for('login', next=request.path))
        if not auth.is_admin(session['user']):
            return render_template('message.html', user=session.get('user'), is_admin=False,
                                   title='접근 권한 없음', body='관리자만 접근할 수 있는 메뉴입니다.'), 403
        return view(*a, **k)
    return wrapped


@app.context_processor
def inject_nav():
    u = session.get('user')
    return {'user': u, 'is_admin': bool(u and auth.is_admin(u))}


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = (request.form.get('username') or '').strip()
        p = request.form.get('password') or ''
        if auth.verify(u, p):
            session['user'] = u
            return redirect(request.args.get('next') or url_for('index'))
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('dashboard.html')


@app.route('/view')
@login_required
def view_dashboard():
    return send_from_directory(os.path.join(BASE, 'private'), 'dashboard.html')


@app.route('/manual')
@login_required
def manual():
    return render_template('manual.html')


@app.route('/review', methods=['POST'])
@login_required
def review():
    f = request.files.get('file')
    if not f or not f.filename.lower().endswith(('.xlsx', '.xlsm')):
        return {'error': '.xlsx 측정 파일을 첨부하세요.'}, 400
    try:
        out_bytes, summary = review_engine.process(f.read())
    except ValueError as e:
        return {'error': str(e)}, 400
    except Exception as e:
        return {'error': '처리 중 오류: %s' % e}, 500
    bio = io.BytesIO(out_bytes)
    name = os.path.splitext(f.filename)[0] + '_검토.xlsx'
    resp = send_file(bio, as_attachment=True, download_name=name,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp.headers['X-Review-Summary'] = json.dumps(summary)
    return resp


# ---------- 관리자 ----------
@app.route('/admin')
@admin_required
def admin_home():
    return render_template('admin.html', users=auth.list_users(),
                           persistent=auth.persistent(), export=auth.export_users_json())


@app.route('/admin/add', methods=['POST'])
@admin_required
def admin_add():
    ok, msg = auth.add_user(request.form.get('username'), request.form.get('password'),
                            admin=bool(request.form.get('admin')))
    flash(msg)
    return redirect(url_for('admin_home'))


@app.route('/admin/reset', methods=['POST'])
@admin_required
def admin_reset():
    ok, msg = auth.set_password(request.form.get('username'), request.form.get('password'))
    flash(msg)
    return redirect(url_for('admin_home'))


@app.route('/admin/role', methods=['POST'])
@admin_required
def admin_role():
    ok, msg = auth.set_admin(request.form.get('username'), bool(request.form.get('admin')))
    flash(msg)
    return redirect(url_for('admin_home'))


@app.route('/admin/delete', methods=['POST'])
@admin_required
def admin_delete():
    u = request.form.get('username')
    if u == session.get('user'):
        flash('현재 로그인한 본인 계정은 삭제할 수 없습니다.')
    else:
        ok, msg = auth.delete_user(u)
        flash(msg)
    return redirect(url_for('admin_home'))


@app.route('/healthz')
def healthz():
    return {'ok': True}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), debug=False)
