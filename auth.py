# -*- coding: utf-8 -*-
"""사용자 저장소 + 인증 (파일 기반, 관리자 CRUD 지원).
저장 위치: USERS_FILE(기본 data/users.json). Railway 영구 저장은 Volume 마운트 권장.
최초 부팅 시 USERS_JSON 환경변수로 시드. ADMIN_USERS(콤마 목록)=관리자 지정."""
import os, json, threading
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.environ.get('USERS_FILE', os.path.join(BASE, 'data', 'users.json'))
ADMIN_USERS = set(u.strip() for u in os.environ.get('ADMIN_USERS', '').split(',') if u.strip())
_lock = threading.RLock()


def _norm(d):
    store = {}
    for u, v in d.items():
        if isinstance(v, dict):
            store[u] = {'pw': v.get('pw', ''), 'admin': bool(v.get('admin'))}
        else:  # legacy {username: hash}
            store[u] = {'pw': v, 'admin': u in ADMIN_USERS}
    return store


def _ensure_admin(store):
    for u in list(store):
        if u in ADMIN_USERS:
            store[u]['admin'] = True
    if store and not any(v['admin'] for v in store.values()):
        store[next(iter(store))]['admin'] = True
    return store


def _seed_from_env():
    raw = os.environ.get('USERS_JSON')
    store = {}
    if raw:
        try:
            store = _norm(json.loads(raw))
        except json.JSONDecodeError:
            store = {}
    if not store:
        store = {'admin': {'pw': generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'change-me')), 'admin': True}}
    return _ensure_admin(store)


def _write(store):
    try:
        d = os.path.dirname(USERS_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def persistent():
    """USERS_FILE 경로가 쓰기 가능한지(영구 저장 여부 안내용)."""
    return os.path.exists(USERS_FILE) or bool(os.environ.get('USERS_FILE'))


def load_store():
    with _lock:
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, encoding='utf-8') as f:
                    store = _ensure_admin(_norm(json.load(f)))
                    if store:
                        return store
            except Exception:
                pass
        store = _seed_from_env()
        _write(store)
        return store


def save_store(store):
    with _lock:
        return _write(store)


def verify(username, password):
    e = load_store().get((username or '').strip())
    return bool(e and check_password_hash(e['pw'], password or ''))


def is_admin(username):
    return bool(load_store().get(username, {}).get('admin'))


def list_users():
    return [{'username': u, 'admin': v['admin']} for u, v in sorted(load_store().items())]


def add_user(username, password, admin=False):
    username = (username or '').strip()
    if not username or not password:
        return False, '아이디와 비밀번호를 모두 입력하세요.'
    s = load_store()
    s[username] = {'pw': generate_password_hash(password), 'admin': bool(admin)}
    ok = save_store(s)
    return ok, ('저장되었습니다.' if ok else '저장 실패 — 영구 저장에는 Railway Volume이 필요합니다.')


def set_password(username, password):
    s = load_store()
    if username in s and password:
        s[username]['pw'] = generate_password_hash(password)
        ok = save_store(s)
        return ok, ('비밀번호가 변경되었습니다.' if ok else '저장 실패.')
    return False, '변경 실패.'


def set_admin(username, admin):
    s = load_store()
    if username not in s:
        return False, '없는 사용자.'
    if not admin and s[username]['admin'] and sum(1 for v in s.values() if v['admin']) <= 1:
        return False, '마지막 관리자는 해제할 수 없습니다.'
    s[username]['admin'] = bool(admin)
    ok = save_store(s)
    return ok, ('변경되었습니다.' if ok else '저장 실패.')


def delete_user(username):
    s = load_store()
    if username not in s:
        return False, '없는 사용자.'
    if s[username]['admin'] and sum(1 for v in s.values() if v['admin']) <= 1:
        return False, '마지막 관리자는 삭제할 수 없습니다.'
    del s[username]
    ok = save_store(s)
    return ok, ('삭제되었습니다.' if ok else '저장 실패.')


def export_users_json():
    """Railway USERS_JSON 변수에 붙여넣어 영구 백업할 문자열."""
    return json.dumps({u: {'pw': v['pw'], 'admin': v['admin']} for u, v in load_store().items()}, ensure_ascii=False)
