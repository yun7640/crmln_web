# -*- coding: utf-8 -*-
"""Postgres 저장 계층 (선택적).
환경변수 DATABASE_URL(Railway Postgres 참조변수)이 있으면 회차·사용자를 Postgres에 저장한다.
없거나 연결 실패 시 호출측(rounds.py·auth.py)이 파일 방식으로 폴백한다.

Railway: web 서비스 Variables에 DATABASE_URL = ${{Postgres.DATABASE_URL}} (참조) 추가.
테이블은 최초 접속 시 자동 생성(CREATE TABLE IF NOT EXISTS)된다."""
import os, json

_URL = (os.environ.get('DATABASE_URL') or os.environ.get('DATABASE_PUBLIC_URL')
        or os.environ.get('POSTGRES_URL') or '')

try:
    import psycopg2
    import psycopg2.extras  # noqa
except Exception:
    psycopg2 = None

_init_done = False


def configured():
    """DATABASE_URL 지정 + 드라이버 존재 여부(연결 성공까지는 보장 안 함)."""
    return bool(_URL and psycopg2)


def _connect():
    # Railway는 postgres:// 또는 postgresql:// 형태 모두 제공 — psycopg2는 둘 다 허용.
    return psycopg2.connect(_URL, connect_timeout=10)


def _init(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS app_users (
                     username text PRIMARY KEY,
                     pw text NOT NULL,
                     admin boolean NOT NULL DEFAULT false)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS app_rounds (
                     label text NOT NULL,
                     mode text NOT NULL,
                     data jsonb NOT NULL,
                     meta jsonb,
                     updated_at timestamptz NOT NULL DEFAULT now(),
                     PRIMARY KEY (label, mode))""")


def _run(fn, default=None):
    """연결→(init)→fn(cur)→commit. 실패 시 default 반환(폴백 신호)."""
    global _init_done
    if not configured():
        return default
    try:
        conn = _connect()
    except Exception:
        return default
    try:
        with conn:
            with conn.cursor() as cur:
                if not _init_done:
                    _init(cur)
                    _init_done = True
                return fn(cur)
    except Exception:
        return default
    finally:
        try:
            conn.close()
        except Exception:
            pass


def available():
    """실제 연결·테이블 준비까지 확인(폴백 판단용)."""
    return _run(lambda cur: True, default=False) is True


# ---------- rounds ----------
def rounds_load():
    def q(cur):
        cur.execute("SELECT label, mode, data, meta FROM app_rounds")
        out = {}
        for label, mode, data, meta in cur.fetchall():
            r = out.setdefault(label, {'label': label})
            r[mode] = data
            if meta:
                if meta.get('date'):
                    r['date'] = meta['date']
                r.setdefault('by', {})[mode] = meta.get('by', '')
        return out
    return _run(q, default=None)


def rounds_upsert(label, mode, data, date='', user=''):
    meta = {'date': date, 'by': user}
    def q(cur):
        cur.execute("""INSERT INTO app_rounds (label, mode, data, meta)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (label, mode)
                       DO UPDATE SET data = EXCLUDED.data, meta = EXCLUDED.meta, updated_at = now()""",
                    (label, mode, json.dumps(data, ensure_ascii=False),
                     json.dumps(meta, ensure_ascii=False)))
        return True
    return _run(q, default=None)


def rounds_delete(label, mode=None):
    def q(cur):
        if mode:
            cur.execute("DELETE FROM app_rounds WHERE label = %s AND mode = %s", (label, mode))
        else:
            cur.execute("DELETE FROM app_rounds WHERE label = %s", (label,))
        return True
    return _run(q, default=None)


# ---------- users ----------
def users_load():
    def q(cur):
        cur.execute("SELECT username, pw, admin FROM app_users")
        return {u: {'pw': p, 'admin': bool(a)} for u, p, a in cur.fetchall()}
    return _run(q, default=None)


def users_save(store):
    """전체 사용자 맵을 트랜잭션으로 재작성(업서트 + 없어진 사용자 삭제)."""
    def q(cur):
        cur.execute("SELECT username FROM app_users")
        existing = {r[0] for r in cur.fetchall()}
        for u, v in store.items():
            cur.execute("""INSERT INTO app_users (username, pw, admin) VALUES (%s, %s, %s)
                           ON CONFLICT (username) DO UPDATE SET pw = EXCLUDED.pw, admin = EXCLUDED.admin""",
                        (u, v.get('pw', ''), bool(v.get('admin'))))
        for u in existing - set(store):
            cur.execute("DELETE FROM app_users WHERE username = %s", (u,))
        return True
    return _run(q, default=None)


def users_count():
    return _run(lambda cur: (cur.execute("SELECT count(*) FROM app_users"), cur.fetchone()[0])[1], default=0)
