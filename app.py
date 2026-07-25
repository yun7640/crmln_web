# -*- coding: utf-8 -*-
"""CRMLN 측정결과 검토 대시보드 — 사용자별 로그인 + 업로드 검토 (Flask)."""
import os, json, io, functools
from flask import (Flask, request, session, redirect, url_for, render_template,
                   send_file, send_from_directory, abort, flash)
from werkzeug.security import check_password_hash, generate_password_hash
import review_engine

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB 업로드 제한

BASE = os.path.dirname(os.path.abspath(__file__))


def load_users():
    """USERS_JSON 환경변수(우선) 또는 users.json 파일에서 {username: pw_hash} 로드."""
    raw = os.environ.get('USERS_JSON')
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    path = os.path.join(BASE, 'users.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    # 폴백: 기본 관리자(최초 배포 확인용) — 반드시 교체할 것
    return {'admin': generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'change-me'))}


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **k):
        if not session.get('user'):
            return redirect(url_for('login', next=request.path))
        return view(*a, **k)
    return wrapped


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = (request.form.get('username') or '').strip()
        p = request.form.get('password') or ''
        users = load_users()
        h = users.get(u)
        if h and check_password_hash(h, p):
            session['user'] = u
            nxt = request.args.get('next') or url_for('index')
            return redirect(nxt)
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('dashboard.html', user=session.get('user'))


@app.route('/view')
@login_required
def view_dashboard():
    # 로그인 사용자에게만 대시보드 HTML 제공(공개 static 아님)
    return send_from_directory(os.path.join(BASE, 'private'), 'dashboard.html')


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


@app.route('/healthz')
def healthz():
    return {'ok': True}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), debug=False)
