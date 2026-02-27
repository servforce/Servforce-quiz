from __future__ import annotations

import json
import time
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlsplit

import psycopg2
import psycopg2.extras

from config import DATABASE_URL, logger

# 把一个数据库连接字符串 DATABASE_URL 解析成 psycopg2.connect() 需要的参数字典
def _parse_pg_dsn(database_url: str) -> dict[str, Any]:
    url = database_url.strip()  # 去掉前后两端的空白
    if url.startswith("postgresql+psycopg2://"):
        url = "postgresql://" + url[len("postgresql+psycopg2://") :]        # 更换地址前缀
    if not url.startswith("postgresql://"):
        raise RuntimeError(f"Unsupported DATABASE_URL scheme: {database_url!r}")        # 使用别的数据库就抛出异常

    u = urlsplit(url)   # 将url拆分出来协议，用户名，密码，主机，端口，路径
    if not u.hostname or not u.port or not u.path:
        raise RuntimeError(f"Invalid DATABASE_URL: {database_url!r}")       # 遇到异常则抛出异常
    return {
        "host": u.hostname,  # 127.0.0.1
        "port": u.port,     # 端口号
        "user": u.username,     # 用户名
        "password": u.password,     # 密码
        "dbname": u.path.lstrip("/"),       # 数据库名称
    }

# 链接数据库管理器，自动管理 PostgreSQL 连接的打开、提交、回滚、关闭
@contextmanager
def conn_scope() -> Iterator[psycopg2.extensions.connection]:
    dsn = _parse_pg_dsn(DATABASE_URL)   # 解析url地址链接
    # print(dsn.get('password'))
    conn = psycopg2.connect(**dsn)      # 连接对应数据库
    try:
        yield conn      # 把连接对象给with使用
        conn.commit()   # 正常执行完，没有异常自动提交事务
    except Exception:
        conn.rollback()     # 如果存在错误，就回滚到上次的操作
        raise       # 抛出异常
    finally:
        conn.close()        # 操作完成后，关闭数据库连接


def _candidate_query_where_clause(query: str | None) -> tuple[str, list[Any]]:
    """
    Build a WHERE clause + params for candidate search.

    Behavior:
    - If the user enters a pure-number query, treat it as:
        phone prefix match (phone LIKE '{q}%') OR exact ID match (id = q).
      This matches the UI expectation that entering "13" shows phones starting with 13
      (and also candidate ID 13 if exists).
    - Supports optional ID prefixes like "#3" or "id:3".
    """
    qraw = str(query or "").strip()
    if not qraw:
        return "", []

    qid = qraw
    if qid.startswith("#"):
        qid = qid[1:].strip()
    if qid.lower().startswith("id:"):
        qid = qid[3:].strip()

    if qid.isdigit():
        params: list[Any] = [f"{qid}%"]
        try:
            qnum = int(qid)
        except Exception:
            qnum = None
        if qnum is None:
            return " WHERE (phone LIKE %s)", params
        params.append(qnum)
        return " WHERE (phone LIKE %s OR id = %s)", params

    q = f"%{qraw}%"
    return " WHERE (name ILIKE %s OR phone LIKE %s)", [q, q]


def init_db() -> None:
    """
    Create/upgrade required DB objects.

    Notes:
    - candidate no longer stores exam status/entered/submitted timestamps.
    - Per-token exam attempts are stored in exam_paper so one candidate can take the same paper multiple times
      with different tokens.
    """
    enum_ddl = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'candidate_status') THEN
    CREATE TYPE candidate_status AS ENUM ('created', 'distributed', 'verified', 'finished');
  ELSE
    -- Ensure required values exist (compatible with older PostgreSQL)
    IF EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'candidate_status' AND e.enumlabel = 'send'
    ) AND NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'candidate_status' AND e.enumlabel = 'distributed'
    ) THEN
      BEGIN
        ALTER TYPE candidate_status RENAME VALUE 'send' TO 'distributed';
      EXCEPTION
        WHEN OTHERS THEN
          NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'candidate_status' AND e.enumlabel = 'created'
    ) THEN
      BEGIN
        ALTER TYPE candidate_status ADD VALUE 'created';
      EXCEPTION
        WHEN OTHERS THEN
          NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'candidate_status' AND e.enumlabel = 'distributed'
    ) THEN
      BEGIN
        ALTER TYPE candidate_status ADD VALUE 'distributed';
      EXCEPTION
        WHEN OTHERS THEN
          NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'candidate_status' AND e.enumlabel = 'verified'
    ) THEN
      BEGIN
        ALTER TYPE candidate_status ADD VALUE 'verified';
      EXCEPTION
        WHEN OTHERS THEN
          NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'candidate_status' AND e.enumlabel = 'in_exam'
    ) THEN
      BEGIN
        ALTER TYPE candidate_status ADD VALUE 'in_exam';
      EXCEPTION
        WHEN OTHERS THEN
          NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'candidate_status' AND e.enumlabel = 'grading'
    ) THEN
      BEGIN
        ALTER TYPE candidate_status ADD VALUE 'grading';
      EXCEPTION
        WHEN OTHERS THEN
          NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'candidate_status' AND e.enumlabel = 'finished'
    ) THEN
      BEGIN
        ALTER TYPE candidate_status ADD VALUE 'finished';
      EXCEPTION
        WHEN OTHERS THEN
          NULL;
      END;
    END IF;
  END IF;
END$$;
"""

    exam_paper_enum_ddl = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'exam_paper_status') THEN
    CREATE TYPE exam_paper_status AS ENUM ('invited', 'verified', 'in_exam', 'grading', 'finished');
  ELSE
    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'exam_paper_status' AND e.enumlabel = 'invited'
    ) THEN
      BEGIN
        ALTER TYPE exam_paper_status ADD VALUE 'invited';
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'exam_paper_status' AND e.enumlabel = 'verified'
    ) THEN
      BEGIN
        ALTER TYPE exam_paper_status ADD VALUE 'verified';
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'exam_paper_status' AND e.enumlabel = 'in_exam'
    ) THEN
      BEGIN
        ALTER TYPE exam_paper_status ADD VALUE 'in_exam';
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'exam_paper_status' AND e.enumlabel = 'grading'
    ) THEN
      BEGIN
        ALTER TYPE exam_paper_status ADD VALUE 'grading';
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      WHERE t.typname = 'exam_paper_status' AND e.enumlabel = 'finished'
    ) THEN
      BEGIN
        ALTER TYPE exam_paper_status ADD VALUE 'finished';
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END IF;
  END IF;
END$$;
"""

    schema_ddl = """
 CREATE TABLE IF NOT EXISTS candidate (
   id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    phone            TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ NULL,
   resume_bytes     BYTEA NULL,
   resume_filename  TEXT NULL,
   resume_mime      TEXT NULL,
   resume_size      INT NULL,
   resume_parsed    JSONB NULL,
  resume_parsed_at TIMESTAMPTZ NULL
 );

 DO $$
 BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'candidate_phone_key') THEN
     BEGIN
       ALTER TABLE candidate ADD CONSTRAINT candidate_phone_key UNIQUE (phone);
    EXCEPTION
      WHEN unique_violation THEN
        -- Existing duplicates; keep running without enforcing uniqueness to avoid startup failure.
        RAISE NOTICE 'Skip adding UNIQUE(phone) because duplicates exist.';
    END;
  END IF;
END$$;

ALTER TABLE candidate ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
UPDATE candidate SET created_at = NOW() WHERE created_at IS NULL;
ALTER TABLE candidate ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE candidate ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE candidate ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

ALTER TABLE candidate DROP COLUMN IF EXISTS updated_at;

-- Drop deprecated columns (status/exam fields moved to exam_paper).
ALTER TABLE candidate DROP COLUMN IF EXISTS status;
ALTER TABLE candidate DROP COLUMN IF EXISTS exam_key;
ALTER TABLE candidate DROP COLUMN IF EXISTS score;
ALTER TABLE candidate DROP COLUMN IF EXISTS exam_started_at;
ALTER TABLE candidate DROP COLUMN IF EXISTS exam_submitted_at;
ALTER TABLE candidate DROP COLUMN IF EXISTS duration_seconds;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_bytes BYTEA NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_filename TEXT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_mime TEXT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_size INT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_parsed JSONB NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_parsed_at TIMESTAMPTZ NULL;

  -- Drop deprecated columns (we no longer use them).
  ALTER TABLE candidate DROP COLUMN IF EXISTS interview;
  ALTER TABLE candidate DROP COLUMN IF EXISTS remark;

 CREATE INDEX IF NOT EXISTS idx_candidate_phone ON candidate(phone);
 CREATE INDEX IF NOT EXISTS idx_candidate_created_at ON candidate(created_at);
 CREATE INDEX IF NOT EXISTS idx_candidate_deleted_at ON candidate(deleted_at);

  CREATE TABLE IF NOT EXISTS exam_paper (
    id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES candidate(id),
    phone TEXT NOT NULL,
    exam_key TEXT NOT NULL,
    token TEXT NOT NULL,
    invite_start_date DATE NULL,
    invite_end_date DATE NULL,
    status exam_paper_status NOT NULL DEFAULT 'invited',
    entered_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    score INT NULL CHECK (score IS NULL OR score BETWEEN 0 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
   updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
 );

 ALTER TABLE exam_paper DROP COLUMN IF EXISTS duration_seconds;

 DO $$
 BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'exam_paper_token_key') THEN
     BEGIN
       ALTER TABLE exam_paper ADD CONSTRAINT exam_paper_token_key UNIQUE (token);
     EXCEPTION WHEN OTHERS THEN NULL;
     END;
   END IF;
 END$$;

  CREATE INDEX IF NOT EXISTS idx_exam_paper_candidate_id ON exam_paper(candidate_id);
  CREATE INDEX IF NOT EXISTS idx_exam_paper_phone ON exam_paper(phone);
  CREATE INDEX IF NOT EXISTS idx_exam_paper_exam_key ON exam_paper(exam_key);
  CREATE INDEX IF NOT EXISTS idx_exam_paper_status ON exam_paper(status);
  CREATE INDEX IF NOT EXISTS idx_exam_paper_created_at ON exam_paper(created_at);
  ALTER TABLE exam_paper ADD COLUMN IF NOT EXISTS invite_start_date DATE NULL;
  ALTER TABLE exam_paper ADD COLUMN IF NOT EXISTS invite_end_date DATE NULL;
  CREATE INDEX IF NOT EXISTS idx_exam_paper_invite_start_date ON exam_paper(invite_start_date);

  CREATE TABLE IF NOT EXISTS system_log (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    candidate_id BIGINT NULL,
    exam_key TEXT NULL,
    token TEXT NULL,
    llm_prompt_tokens INT NULL,
    llm_completion_tokens INT NULL,
    llm_total_tokens INT NULL,
    duration_seconds INT NULL,
    ip TEXT NULL,
    user_agent TEXT NULL,
    meta JSONB NULL
  );
  CREATE INDEX IF NOT EXISTS idx_system_log_at ON system_log(at);
  CREATE INDEX IF NOT EXISTS idx_system_log_event_type ON system_log(event_type);
  CREATE INDEX IF NOT EXISTS idx_system_log_candidate_id ON system_log(candidate_id);
  CREATE INDEX IF NOT EXISTS idx_system_log_exam_key ON system_log(exam_key);
  CREATE INDEX IF NOT EXISTS idx_system_log_token ON system_log(token);
  """
    try:
        # PostgreSQL requires committing enum value changes before using them in
        # defaults/updates within the same session. Execute enum DDL separately.
        with conn_scope() as conn:
            with conn.cursor() as cur:
                cur.execute(enum_ddl)
        with conn_scope() as conn:
            with conn.cursor() as cur:
                cur.execute(exam_paper_enum_ddl)
        with conn_scope() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_ddl)
        try:
            n = backfill_system_log_llm_totals_from_meta()
            if n > 0:
                logger.info("Backfilled system_log llm_total_tokens from meta: %s rows", n)
        except Exception:
            logger.exception("Failed to backfill system_log llm_total_tokens from meta")
        logger.info("DB ready")
    except Exception as e:
        raise RuntimeError(
            f"Database connection failed. Please check DATABASE_URL and PostgreSQL status. Details: {type(e).__name__}({e})"
        ) from e


# 从 PostgreSQL 的 candidate 表里查询候选人（考生）列表，倒序排列
def list_candidates(
    limit: int | None = None,
    offset: int = 0,
    *,
    query: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> list[dict[str, Any]]:
    # 查询的sql语句
    sql = """
 SELECT
   id,
   name,
   phone,
   created_at,
    (resume_bytes IS NOT NULL) AS has_resume
  FROM candidate
 WHERE deleted_at IS NULL
   """
    params: list[Any] = []      # 最多返回多少条
    where_sql, where_params = _candidate_query_where_clause(query)
    if where_sql:
        # _candidate_query_where_clause returns a " WHERE ..." fragment; we already have a base WHERE.
        sql += " AND " + where_sql.strip().removeprefix("WHERE").removeprefix("where").strip()
        params.extend(where_params)

    if created_from is not None:
        if " WHERE " in sql:
            sql += " AND created_at >= %s"
        else:
            sql += " WHERE created_at >= %s"
        params.append(created_from)
    if created_to is not None:
        if " WHERE " in sql:
            sql += " AND created_at <= %s"
        else:
            sql += " WHERE created_at <= %s"
        params.append(created_to)

    sql += "\nORDER BY id DESC\n"   # 按照id倒序输出
    # 将限制的limit的数量传到数据库中
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))   # 确保传给数据库的一定是整数 
    # 连接数据库并将数据库中的内容都展示出来
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))     # 将参数列表换成元组传进去
            return [dict(r) for r in cur.fetchall()]


# 创建候选人身份信息
def count_candidates(*, query: str | None = None) -> int:
    sql = "SELECT COUNT(*) FROM candidate WHERE deleted_at IS NULL"
    params: list[Any] = []
    where_sql, where_params = _candidate_query_where_clause(query)
    if where_sql:
        sql += " AND " + where_sql.strip().removeprefix("WHERE").removeprefix("where").strip()
        params.extend(where_params)
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return int(cur.fetchone()[0])


def get_candidate_by_phone(phone: str) -> dict[str, Any] | None:
    sql = """
 SELECT id, name, phone, created_at
  FROM candidate
 WHERE phone = %s
   AND deleted_at IS NULL
 ORDER BY id DESC
 LIMIT 1
 """
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (str(phone or ""),))
            row = cur.fetchone()
            return dict(row) if row else None


def create_candidate(name: str, phone: str) -> int:
    sql = """
 INSERT INTO candidate(name, phone)
 VALUES (%s, %s)
 RETURNING id
 """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (name, phone))
            return int(cur.fetchone()[0])


# 候选人（考生）的 id查找到候选者的身份信息
def get_candidate(candidate_id: int) -> dict[str, Any] | None:
    sql = """
 SELECT id, name, phone, created_at, deleted_at,
        resume_filename, resume_mime, resume_size, resume_parsed, resume_parsed_at
  FROM candidate
  WHERE id = %s
   """
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (int(candidate_id),))
            row = cur.fetchone()
            return dict(row) if row else None


def get_candidate_resume(candidate_id: int) -> dict[str, Any] | None:
    sql = """
 SELECT resume_bytes, resume_filename, resume_mime, resume_size
 FROM candidate
 WHERE id=%s
 """
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (int(candidate_id),))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            b = d.get("resume_bytes")
            if isinstance(b, memoryview):
                d["resume_bytes"] = b.tobytes()
            return d


def update_candidate_resume(
    candidate_id: int,
    *,
    resume_bytes: bytes,
    resume_filename: str | None = None,
    resume_mime: str | None = None,
    resume_size: int | None = None,
    resume_parsed: dict[str, Any] | None = None,
) -> None:
    sql = """
 UPDATE candidate
 SET
   resume_bytes=%s,
   resume_filename=%s,
   resume_mime=%s,
   resume_size=%s,
   resume_parsed=%s,
   resume_parsed_at=NOW()
 WHERE id=%s
 """
    parsed_param = None
    if resume_parsed is not None:
        parsed_param = psycopg2.extras.Json(
            resume_parsed, dumps=lambda x: json.dumps(x, ensure_ascii=False)
        )
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    psycopg2.Binary(resume_bytes),
                    (resume_filename or None),
                    (resume_mime or None),
                    (int(resume_size) if resume_size is not None else None),
                    parsed_param,
                    int(candidate_id),
                ),
            )


def update_candidate_resume_parsed(
    candidate_id: int,
    *,
    resume_parsed: dict[str, Any] | None,
    touch_resume_parsed_at: bool = True,
) -> None:
    if touch_resume_parsed_at:
        sql = """
  UPDATE candidate
  SET
    resume_parsed=%s,
    resume_parsed_at=NOW()
  WHERE id=%s
  """
    else:
        sql = """
  UPDATE candidate
  SET
    resume_parsed=%s
  WHERE id=%s
  """
    parsed_param = None
    if resume_parsed is not None:
        parsed_param = psycopg2.extras.Json(resume_parsed, dumps=lambda x: json.dumps(x, ensure_ascii=False))
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (parsed_param, int(candidate_id)))


def mark_exam_deleted(exam_key: str, *, marker: str = "已删除") -> int:
    """
    When an exam is deleted, preserve history but mark the exam reference in exam_paper.
    Returns number of affected rows.
    """
    sql = "UPDATE exam_paper SET exam_key=%s WHERE exam_key=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(marker), str(exam_key or "")))
            return int(cur.rowcount or 0)


def rename_exam_key(old_exam_key: str, new_exam_key: str) -> int:
    """
    Rename exam_key references in exam_paper table.
    Returns number of affected rows.
    """
    sql = "UPDATE exam_paper SET exam_key=%s WHERE exam_key=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(new_exam_key or ""), str(old_exam_key or "")))
            return int(cur.rowcount or 0)

# 根据id修改候选者姓名和手机号
def update_candidate(candidate_id: int, *, name: str, phone: str, created_at=None) -> None:
    if created_at is None:
        sql = "UPDATE candidate SET name=%s, phone=%s WHERE id=%s"
        params = (name, phone, int(candidate_id))
    else:
        sql = "UPDATE candidate SET name=%s, phone=%s, created_at=%s WHERE id=%s"
        params = (name, phone, created_at, int(candidate_id))
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


# 根据id号删除候选者id
def delete_candidate(candidate_id: int) -> None:
    # Preserve exam history: if exam_paper exists, perform a "soft delete" by anonymizing
    # the candidate record while keeping its id for FK references.
    sql_check = "SELECT 1 FROM exam_paper WHERE candidate_id=%s LIMIT 1"
    sql_hard = "DELETE FROM candidate WHERE id=%s"
    sql_soft = """
 UPDATE candidate
   SET
     deleted_at=NOW(),
     name=%s,
     phone=%s,
     resume_bytes=NULL,
     resume_filename=NULL,
     resume_mime=NULL,
     resume_size=NULL,
     resume_parsed=NULL,
     resume_parsed_at=NULL
 WHERE id=%s
 """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_check, (int(candidate_id),))
            if cur.fetchone() is not None:
                # Use a unique phone placeholder to free the original phone for future registrations.
                placeholder_phone = f"DELETED_{int(candidate_id)}_{int(time.time())}"
                cur.execute(sql_soft, ("已删除", placeholder_phone, int(candidate_id)))
                return
            cur.execute(sql_hard, (int(candidate_id),))


# 通过姓名和电话验证候选者
def verify_candidate(candidate_id: int, *, name: str, phone: str) -> bool:
    sql = "SELECT 1 FROM candidate WHERE id=%s AND name=%s AND phone=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (int(candidate_id), name, phone))
            return cur.fetchone() is not None


def create_exam_paper(
    *,
    candidate_id: int,
    phone: str,
    exam_key: str,
    token: str,
    invite_start_date: str | None = None,
    invite_end_date: str | None = None,
    status: str = "invited",
) -> int:
    sql = """
 INSERT INTO exam_paper(candidate_id, phone, exam_key, token, invite_start_date, invite_end_date, status)
 VALUES (%s, %s, %s, %s, %s::date, %s::date, %s::exam_paper_status)
 RETURNING id
 """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    int(candidate_id),
                    str(phone or ""),
                    str(exam_key or ""),
                    str(token or ""),
                    (str(invite_start_date).strip() if invite_start_date else None),
                    (str(invite_end_date).strip() if invite_end_date else None),
                    str(status or "invited"),
                ),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def get_exam_paper_by_token(token: str) -> dict[str, Any] | None:
    sql = """
 SELECT
    id,
    candidate_id,
    phone,
    exam_key,
    token,
    invite_start_date,
    invite_end_date,
    status,
    entered_at,
    finished_at,
    score,
    created_at,
    updated_at
 FROM exam_paper
 WHERE token=%s
 LIMIT 1
 """
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (str(token or ""),))
            row = cur.fetchone()
            return dict(row) if row else None


def set_exam_paper_status(token: str, status: str) -> None:
    sql = "UPDATE exam_paper SET status=%s::exam_paper_status, updated_at=NOW() WHERE token=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(status or ""), str(token or "")))


def set_exam_paper_entered_at(token: str, entered_at) -> None:
    sql = """
 UPDATE exam_paper
 SET entered_at=COALESCE(entered_at, %s),
     updated_at=NOW()
 WHERE token=%s
 """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (entered_at, str(token or "")))


def set_exam_paper_finished_at(token: str, finished_at) -> None:
    sql = """
 UPDATE exam_paper
 SET finished_at=COALESCE(finished_at, %s),
     updated_at=NOW()
 WHERE token=%s
 """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (finished_at, str(token or "")))


def set_exam_paper_invite_window_if_missing(
    token: str,
    *,
    invite_start_date: str | None = None,
    invite_end_date: str | None = None,
) -> None:
    """
    Backfill invite window dates onto exam_paper without overwriting existing values.
    """
    sql = """
 UPDATE exam_paper
 SET
   invite_start_date = COALESCE(invite_start_date, %s::date),
   invite_end_date = COALESCE(invite_end_date, %s::date),
   updated_at = NOW()
 WHERE token=%s
 """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    (str(invite_start_date).strip() if invite_start_date else None),
                    (str(invite_end_date).strip() if invite_end_date else None),
                    str(token or ""),
                ),
            )


def update_exam_paper_result(
    token: str,
    *,
    status: str,
    score: int | None,
    entered_at=None,
    finished_at=None,
) -> None:
    sql = """
 UPDATE exam_paper
 SET
   status=%s::exam_paper_status,
   score=%s,
   entered_at=COALESCE(entered_at, %s),
   finished_at=%s,
   updated_at=NOW()
 WHERE token=%s
 """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    str(status or ""),
                    (int(score) if score is not None else None),
                    entered_at,
                    finished_at,
                    str(token or ""),
                ),
            )


def list_exam_papers(
    *,
    query: str | None = None,
    invite_start_from: str | None = None,
    invite_start_to: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = """
  SELECT
     ep.id AS attempt_id,
     ep.candidate_id,
     c.name,
     ep.phone,
     ep.exam_key,
     ep.token,
     ep.invite_start_date,
     ep.invite_end_date,
     ep.status,
     ep.entered_at,
     ep.finished_at,
     ep.score,
     ep.created_at
  FROM exam_paper ep
  JOIN candidate c ON c.id = ep.candidate_id
  """
    params: list[Any] = []
    where: list[str] = []
    q = str(query or "").strip()
    if q:
        ql = f"%{q}%"
        where.append("(c.name ILIKE %s OR ep.phone LIKE %s OR ep.exam_key ILIKE %s OR ep.token ILIKE %s)")
        params.extend([ql, ql, ql, ql])
    if invite_start_from:
        where.append("ep.invite_start_date >= %s::date")
        params.append(str(invite_start_from).strip())
    if invite_start_to:
        where.append("ep.invite_start_date <= %s::date")
        params.append(str(invite_start_to).strip())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += "\n ORDER BY ep.id DESC\n"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))
    if offset:
        sql += " OFFSET %s"
        params.append(int(offset))
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]


def create_system_log(
    *,
    actor: str,
    event_type: str,
    candidate_id: int | None = None,
    exam_key: str | None = None,
    token: str | None = None,
    llm_prompt_tokens: int | None = None,
    llm_completion_tokens: int | None = None,
    llm_total_tokens: int | None = None,
    duration_seconds: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    sql = """
 INSERT INTO system_log(
   actor, event_type, candidate_id, exam_key, token,
   llm_prompt_tokens, llm_completion_tokens, llm_total_tokens, duration_seconds,
   ip, user_agent, meta
 )
 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
 RETURNING id
 """
    meta_param = None
    if meta is not None:
        meta_param = psycopg2.extras.Json(meta, dumps=lambda x: json.dumps(x, ensure_ascii=False))
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    str(actor or ""),
                    str(event_type or ""),
                    (int(candidate_id) if candidate_id is not None else None),
                    (str(exam_key).strip() if exam_key else None),
                    (str(token).strip() if token else None),
                    (int(llm_prompt_tokens) if llm_prompt_tokens is not None else None),
                    (int(llm_completion_tokens) if llm_completion_tokens is not None else None),
                    (int(llm_total_tokens) if llm_total_tokens is not None else None),
                    (int(duration_seconds) if duration_seconds is not None else None),
                    (str(ip).strip() if ip else None),
                    (str(user_agent).strip() if user_agent else None),
                    meta_param,
                ),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def backfill_system_log_llm_totals_from_meta() -> int:
    """
    Best-effort backfill:

    For historical rows written before we started persisting llm_total_tokens explicitly,
    copy meta.llm_total_tokens_sum into the dedicated llm_total_tokens column.

    This enables consistent UI display without changing existing meta payloads.
    """
    sql = """
 UPDATE system_log
 SET llm_total_tokens = (meta->>'llm_total_tokens_sum')::int
 WHERE (llm_total_tokens IS NULL OR llm_total_tokens <= 0)
   AND meta IS NOT NULL
   AND (meta ? 'llm_total_tokens_sum')
   AND (meta->>'llm_total_tokens_sum') ~ '^[0-9]+$'
   AND (meta->>'llm_total_tokens_sum')::int > 0
    """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return int(cur.rowcount or 0)


def _system_log_where_clause(
    *,
    query: str | None = None,
    event_type: str | None = None,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
    table_alias: str = "",
    business_only: bool = False,
) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    a = str(table_alias or "").strip()
    if a and not a.endswith("."):
        a = a + "."

    if business_only:
        # Keep only business-relevant logs:
        # - candidate.* ops
        # - exam CRUD ops
        # - assignment/invite + answering timeline
        # - llm.usage only when it can be linked to candidate/exam/token context
        llm_linked = (
            f"({a}token IS NOT NULL AND {a}token <> '') OR "
            f"{a}candidate_id IS NOT NULL OR "
            f"({a}exam_key IS NOT NULL AND {a}exam_key <> '')"
        )
        where.append(
            "("
            f"{a}event_type LIKE 'candidate.%%' OR "
            f"{a}event_type IN ('exam.upload','exam.update','exam.delete','exam.read',"
            f"'assignment.create','exam.enter','exam.finish') OR "
            f"({a}event_type='llm.usage' AND ({llm_linked}))"
            ")"
        )

    t = str(event_type or "").strip()
    if t:
        where.append(f"{a}event_type=%s")
        params.append(t)

    if at_from is not None:
        where.append(f"{a}at >= %s")
        params.append(at_from)
    if at_to is not None:
        where.append(f"{a}at <= %s")
        params.append(at_to)

    q = str(query or "").strip()
    if q:
        ql = f"%{q}%"
        where.append(
            "("
            f"{a}actor ILIKE %s OR {a}event_type ILIKE %s OR {a}exam_key ILIKE %s OR {a}token ILIKE %s OR "
            f"CAST({a}candidate_id AS TEXT) ILIKE %s OR CAST({a}meta AS TEXT) ILIKE %s"
            ")"
        )
        params.extend([ql, ql, ql, ql, ql, ql])

    if not where:
        return "", []
    return " WHERE " + " AND ".join(where), params


def count_system_logs(
    *,
    query: str | None = None,
    event_type: str | None = None,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
    business_only: bool = False,
) -> int:
    sql = "SELECT COUNT(*) FROM system_log"
    where_sql, params = _system_log_where_clause(
        query=query,
        event_type=event_type,
        at_from=at_from,
        at_to=at_to,
        business_only=business_only,
    )
    if where_sql:
        sql += where_sql
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return int(cur.fetchone()[0])


def list_system_logs(
    *,
    query: str | None = None,
    event_type: str | None = None,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
    limit: int | None = None,
    offset: int = 0,
    business_only: bool = False,
) -> list[dict[str, Any]]:
    sql = """
 SELECT
   sl.id,
   sl.at,
   sl.actor,
   sl.event_type,
   sl.candidate_id,
   c.name AS candidate_name,
   c.phone AS candidate_phone,
   sl.exam_key,
   sl.token,
   sl.llm_prompt_tokens,
   sl.llm_completion_tokens,
   sl.llm_total_tokens,
   sl.duration_seconds,
   sl.ip,
   sl.user_agent,
   sl.meta
 FROM system_log sl
 LEFT JOIN candidate c ON c.id = sl.candidate_id
 """
    where_sql, params = _system_log_where_clause(
        query=query,
        event_type=event_type,
        at_from=at_from,
        at_to=at_to,
        table_alias="sl",
        business_only=business_only,
    )
    if where_sql:
        sql += where_sql
    sql += "\n ORDER BY id DESC\n"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))
    if offset:
        sql += " OFFSET %s"
        params.append(int(offset))
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]


def count_operation_logs() -> int:
    """
    Count business operation logs (exclude llm.usage rows).

    Operations shown in UI:
      - candidate.* (CRUD and related admin actions)
      - exam.* (CRUD + public invite toggle)
      - assignment timeline: assignment.create / exam.enter / exam.finish
    """
    sql = """
 SELECT COUNT(*)
 FROM system_log sl
 WHERE (
    sl.event_type LIKE 'candidate.%%' OR
    sl.event_type LIKE 'exam.%%' OR
    sl.event_type IN ('assignment.create','exam.enter','exam.finish')
  ) AND sl.event_type <> 'llm.usage'
  """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return int(cur.fetchone()[0])


def list_operation_logs(*, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """
    List business operation logs (exclude llm.usage rows), newest first.
    """
    sql = """
 SELECT
    sl.id,
    sl.at,
    sl.actor,
    sl.event_type,
    sl.candidate_id,
    c.name AS candidate_name,
    c.phone AS candidate_phone,
    sl.exam_key,
    sl.token,
    sl.llm_prompt_tokens,
    sl.llm_completion_tokens,
    sl.llm_total_tokens,
    sl.duration_seconds,
    sl.meta
  FROM system_log sl
  LEFT JOIN candidate c ON c.id = sl.candidate_id
  WHERE (
    sl.event_type LIKE 'candidate.%%' OR
    sl.event_type LIKE 'exam.%%' OR
    sl.event_type IN ('assignment.create','exam.enter','exam.finish')
  ) AND sl.event_type <> 'llm.usage'
  ORDER BY sl.id DESC
  LIMIT %s
  OFFSET %s
  """
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (int(limit), int(offset)))
            return [dict(r) for r in cur.fetchall()]


def list_operation_daily_counts(
    *,
    tz_offset_seconds: int,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Aggregate operation log density by day (local day buckets using a numeric UTC offset in seconds).

    Notes:
    - We intentionally use seconds instead of PostgreSQL's numeric time zone strings (e.g. '+08:00'),
      because PostgreSQL interprets numeric zones using POSIX sign conventions (reversed vs the common ISO form).
    """
    sql = """
 SELECT (((sl.at AT TIME ZONE 'UTC') + (%s * INTERVAL '1 second'))::date) AS day, COUNT(*) AS cnt
 FROM system_log sl
 WHERE (
   sl.event_type LIKE 'candidate.%%' OR
   sl.event_type LIKE 'exam.%%' OR
   sl.event_type IN ('assignment.create','exam.enter','exam.finish')
  ) AND sl.event_type <> 'llm.usage'
  """
    params: list[Any] = [int(tz_offset_seconds or 0)]
    if at_from is not None:
        sql += "\n AND sl.at >= %s"
        params.append(at_from)
    if at_to is not None:
        sql += "\n AND sl.at <= %s"
        params.append(at_to)
    sql += "\n GROUP BY day\n ORDER BY day ASC\n"
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]


def count_operation_logs_by_category() -> dict[str, int]:
    """
    Count operation logs grouped into UI categories across the whole DB.

    Categories:
      - candidate: candidate.* ops
      - exam: exam.* ops (excluding grading and assignment timeline)
      - grading: exam.grade
      - assignment: assignment.create / exam.enter / exam.finish
    """
    sql = """
 SELECT
    SUM(CASE WHEN sl.event_type LIKE 'candidate.%%' THEN 1 ELSE 0 END) AS candidate_cnt,
    SUM(CASE WHEN sl.event_type LIKE 'exam.%%' AND sl.event_type NOT IN ('exam.grade','exam.enter','exam.finish') THEN 1 ELSE 0 END) AS exam_cnt,
    SUM(CASE WHEN sl.event_type = 'exam.grade' THEN 1 ELSE 0 END) AS grading_cnt,
    SUM(CASE WHEN sl.event_type IN ('assignment.create','exam.enter','exam.finish') THEN 1 ELSE 0 END) AS assignment_cnt
  FROM system_log sl
  WHERE (
    sl.event_type LIKE 'candidate.%%' OR
    sl.event_type LIKE 'exam.%%' OR
    sl.event_type IN ('assignment.create','exam.enter','exam.finish')
  ) AND sl.event_type <> 'llm.usage'
  """
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            row = cur.fetchone() or {}
            out: dict[str, int] = {"candidate": 0, "exam": 0, "grading": 0, "assignment": 0}
            try:
                out["candidate"] = int(row.get("candidate_cnt") or 0)
            except Exception:
                out["candidate"] = 0
            try:
                out["exam"] = int(row.get("exam_cnt") or 0)
            except Exception:
                out["exam"] = 0
            try:
                out["grading"] = int(row.get("grading_cnt") or 0)
            except Exception:
                out["grading"] = 0
            try:
                out["assignment"] = int(row.get("assignment_cnt") or 0)
            except Exception:
                out["assignment"] = 0
            return out



def list_system_log_type_counts(
    *,
    query: str | None = None,
    event_type: str | None = None,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
    business_only: bool = False,
) -> list[dict[str, Any]]:
    sql = """
 SELECT event_type, COUNT(*) AS cnt
 FROM system_log
 """
    where_sql, params = _system_log_where_clause(
        query=query,
        event_type=event_type,
        at_from=at_from,
        at_to=at_to,
        business_only=business_only,
    )
    if where_sql:
        sql += where_sql
    sql += "\n GROUP BY event_type\n ORDER BY cnt DESC, event_type ASC\n"
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]


def list_system_log_category_counts(
    *,
    query: str | None = None,
    event_type: str | None = None,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
    business_only: bool = False,
) -> list[dict[str, Any]]:
    """
    Aggregate logs into higher-level categories for UI legend.

    Categories:
      - candidate: candidate.* (and llm.usage tied to candidate)
      - exam: exam CRUD (and llm.usage tied to exam)
      - assignment: invitations + answering timeline (and llm.usage tied to token)
      - ui: page views
      - system: fallback/unknown
    """
    sql = """
 SELECT
   CASE
     WHEN sl.event_type LIKE 'candidate.%%' THEN 'candidate'
     WHEN sl.event_type IN ('exam.upload','exam.update','exam.delete','exam.read') THEN 'exam'
     WHEN sl.event_type IN ('assignment.create','exam.enter','exam.finish') THEN 'assignment'
     WHEN sl.event_type = 'llm.usage' THEN
       CASE
         WHEN sl.token IS NOT NULL AND sl.token <> '' THEN 'assignment'
         WHEN sl.candidate_id IS NOT NULL THEN 'candidate'
         WHEN sl.exam_key IS NOT NULL AND sl.exam_key <> '' THEN 'exam'
         ELSE 'system'
       END
     WHEN sl.event_type IN ('ui.view','admin.view') THEN 'ui'
     ELSE 'system'
   END AS category,
   COUNT(*) AS cnt
 FROM system_log sl
 """
    where_sql, params = _system_log_where_clause(
        query=query,
        event_type=event_type,
        at_from=at_from,
        at_to=at_to,
        table_alias="sl",
        business_only=business_only,
    )
    if where_sql:
        sql += where_sql
    sql += "\n GROUP BY category\n ORDER BY cnt DESC, category ASC\n"
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]


def list_system_log_daily_counts(
    *,
    query: str | None = None,
    event_type: str | None = None,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
    business_only: bool = False,
) -> list[dict[str, Any]]:
    """
    Aggregate log density by day (UTC day buckets).
    """
    sql = """
 SELECT (DATE_TRUNC('day', at))::date AS day, COUNT(*) AS cnt
 FROM system_log
 """
    where_sql, params = _system_log_where_clause(
        query=query,
        event_type=event_type,
        at_from=at_from,
        at_to=at_to,
        business_only=business_only,
    )
    if where_sql:
        sql += where_sql
    sql += "\n GROUP BY day\n ORDER BY day ASC\n"
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]


def count_exam_papers(
    *,
    query: str | None = None,
    invite_start_from: str | None = None,
    invite_start_to: str | None = None,
) -> int:
    sql = """
 SELECT COUNT(*)
 FROM exam_paper ep
 JOIN candidate c ON c.id = ep.candidate_id
 """
    params: list[Any] = []
    where: list[str] = []
    q = str(query or "").strip()
    if q:
        ql = f"%{q}%"
        where.append("(c.name ILIKE %s OR ep.phone LIKE %s OR ep.exam_key ILIKE %s OR ep.token ILIKE %s)")
        params.extend([ql, ql, ql, ql])
    if invite_start_from:
        where.append("ep.invite_start_date >= %s::date")
        params.append(str(invite_start_from).strip())
    if invite_start_to:
        where.append("ep.invite_start_date <= %s::date")
        params.append(str(invite_start_to).strip())
    if where:
        sql += " WHERE " + " AND ".join(where)
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return int(cur.fetchone()[0])
