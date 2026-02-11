from __future__ import annotations

import json
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


def init_db() -> None:
    """
    Create required DB objects (only candidate table + enum).
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

    schema_ddl = """
 CREATE TABLE IF NOT EXISTS candidate (
   id               BIGSERIAL PRIMARY KEY,
   name             TEXT NOT NULL,
   phone            TEXT NOT NULL,
   created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
   updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
   status           candidate_status NOT NULL DEFAULT 'created',
   exam_key         TEXT NULL,
   score            INT NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
   exam_started_at  TIMESTAMPTZ NULL,
   exam_submitted_at TIMESTAMPTZ NULL,
  duration_seconds INT NULL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
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

ALTER TABLE candidate ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
UPDATE candidate SET updated_at = NOW() WHERE updated_at IS NULL;
ALTER TABLE candidate ALTER COLUMN updated_at SET DEFAULT NOW();
ALTER TABLE candidate ALTER COLUMN updated_at SET NOT NULL;

-- Ensure status default is "created" even when the table already existed (CREATE TABLE IF NOT EXISTS won't update defaults).
ALTER TABLE candidate ALTER COLUMN status SET DEFAULT 'created'::candidate_status;

 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS exam_key TEXT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS exam_started_at TIMESTAMPTZ NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS exam_submitted_at TIMESTAMPTZ NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS duration_seconds INT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_bytes BYTEA NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_filename TEXT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_mime TEXT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_size INT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_parsed JSONB NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS resume_parsed_at TIMESTAMPTZ NULL;

 DO $$
 BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'candidate_duration_seconds_check') THEN
     BEGIN
       ALTER TABLE candidate
         ADD CONSTRAINT candidate_duration_seconds_check
         CHECK (duration_seconds IS NULL OR duration_seconds >= 0);
     EXCEPTION
       WHEN OTHERS THEN
         NULL;
     END;
   END IF;
 END$$;

  -- Drop deprecated columns (we no longer use them).
  ALTER TABLE candidate DROP COLUMN IF EXISTS interview;
  ALTER TABLE candidate DROP COLUMN IF EXISTS remark;
  
  -- Migrate legacy status values to the new lifecycle (best-effort).
  UPDATE candidate
 SET status = CASE
  WHEN status::text = 'distributed' THEN 'distributed'::candidate_status
  WHEN status::text = 'verified' THEN 'verified'::candidate_status
  WHEN status::text = 'finished' THEN 'finished'::candidate_status
  WHEN status::text = 'send' AND exam_key IS NOT NULL THEN 'distributed'::candidate_status
  WHEN status::text = 'send' AND exam_key IS NULL THEN 'created'::candidate_status
  ELSE 'created'::candidate_status
END
WHERE status::text IN ('send', 'distributed', 'verified', 'finished');

-- If a record is marked distributed but has no exam assigned, treat it as created.
UPDATE candidate
SET status = 'created'::candidate_status
WHERE status = 'distributed'::candidate_status AND exam_key IS NULL;

 CREATE INDEX IF NOT EXISTS idx_candidate_phone ON candidate(phone);
 CREATE INDEX IF NOT EXISTS idx_candidate_status ON candidate(status);
 CREATE INDEX IF NOT EXISTS idx_candidate_created_at ON candidate(created_at);
 """
    try:
        # PostgreSQL requires committing enum value changes before using them in
        # defaults/updates within the same session. Execute enum DDL separately.
        with conn_scope() as conn:
            with conn.cursor() as cur:
                cur.execute(enum_ddl)
        with conn_scope() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_ddl)
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
   status,
   exam_key,
   score,
   exam_started_at,
   exam_submitted_at,
   duration_seconds,
   (resume_bytes IS NOT NULL) AS has_resume
  FROM candidate
  """
    params: list[Any] = []      # 最多返回多少条
    if query:   # 搜索关键字
        qraw = str(query or "").strip()
        q = f"%{qraw}%"  # 包含query这个内容就可以
        where_parts: list[str] = []
        if qraw.isdigit():
            where_parts.append("id = %s")
            params.append(int(qraw))
        where_parts.append("name ILIKE %s")  # 不区分大小写的模糊查询
        where_parts.append("phone LIKE %s")
        params.extend([q, q])  # 一个给name，一个给phone
        sql += " WHERE " + " OR ".join(where_parts)

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
    sql = "SELECT COUNT(*) FROM candidate"
    params: list[Any] = []
    if query:
        qraw = str(query or "").strip()
        q = f"%{qraw}%"
        where_parts: list[str] = []
        if qraw.isdigit():
            where_parts.append("id = %s")
            params.append(int(qraw))
        where_parts.append("name ILIKE %s")
        where_parts.append("phone LIKE %s")
        params.extend([q, q])
        sql += " WHERE " + " OR ".join(where_parts)
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return int(cur.fetchone()[0])


def has_recent_exam_submission(name: str, phone: str, *, months: int = 6) -> bool:
    if months <= 0:
        return False
    sql = """
SELECT 1
FROM candidate
WHERE name=%s AND phone=%s
  AND exam_submitted_at IS NOT NULL
  AND exam_submitted_at >= (NOW() - (%s || ' months')::interval)
LIMIT 1
"""
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (name, phone, int(months)))
            return cur.fetchone() is not None


def has_recent_exam_submission_by_phone(phone: str, *, months: int = 6) -> bool:
    if months <= 0:
        return False
    sql = """
SELECT 1
FROM candidate
WHERE phone=%s
  AND exam_submitted_at IS NOT NULL
  AND exam_submitted_at >= (NOW() - (%s || ' months')::interval)
LIMIT 1
"""
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(phone or ""), int(months)))
            return cur.fetchone() is not None


def get_candidate_by_phone(phone: str) -> dict[str, Any] | None:
    sql = """
 SELECT id, name, phone, created_at, status, exam_key, score, exam_started_at, exam_submitted_at, duration_seconds
 FROM candidate
WHERE phone = %s
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
 SELECT id, name, phone, created_at, updated_at, status, exam_key, score, exam_started_at, exam_submitted_at, duration_seconds,
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
  resume_parsed_at=NOW(),
  updated_at=NOW()
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
   resume_parsed_at=NOW(),
   updated_at=NOW()
 WHERE id=%s
 """
    else:
        sql = """
 UPDATE candidate
 SET
   resume_parsed=%s,
   updated_at=NOW()
 WHERE id=%s
 """
    parsed_param = None
    if resume_parsed is not None:
        parsed_param = psycopg2.extras.Json(resume_parsed, dumps=lambda x: json.dumps(x, ensure_ascii=False))
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (parsed_param, int(candidate_id)))


# 设置id值候选者的状态
def set_candidate_status(candidate_id: int, status: str) -> None:
    sql = "UPDATE candidate SET status = %s, updated_at=NOW() WHERE id = %s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (status, int(candidate_id)))

# 根据id值设置试卷id值
def set_candidate_exam_key(candidate_id: int, exam_key: str) -> None:
    sql = "UPDATE candidate SET exam_key=%s, updated_at=NOW() WHERE id=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(exam_key or ""), int(candidate_id)))


def mark_exam_deleted(exam_key: str, *, marker: str = "已删除") -> int:
    """
    When an exam is deleted, preserve candidate history but mark the exam reference.
    Returns number of affected rows.
    """
    sql = "UPDATE candidate SET exam_key=%s WHERE exam_key=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(marker), str(exam_key or "")))
            return int(cur.rowcount or 0)


def rename_exam_key(old_exam_key: str, new_exam_key: str) -> int:
    """
    Rename exam_key references in candidate table.
    Returns number of affected rows.
    """
    sql = "UPDATE candidate SET exam_key=%s WHERE exam_key=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(new_exam_key or ""), str(old_exam_key or "")))
            return int(cur.rowcount or 0)

# 根据id修改候选者姓名和手机号
def update_candidate(candidate_id: int, *, name: str, phone: str, created_at=None) -> None:
    if created_at is None:
        sql = "UPDATE candidate SET name=%s, phone=%s, updated_at=NOW() WHERE id=%s"
        params = (name, phone, int(candidate_id))
    else:
        sql = "UPDATE candidate SET name=%s, phone=%s, created_at=%s, updated_at=NOW() WHERE id=%s"
        params = (name, phone, created_at, int(candidate_id))
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def reset_candidate_exam_state(candidate_id: int) -> None:
    sql = """
 UPDATE candidate
 SET
   status='created',
   exam_key=NULL,
   score=0,
   exam_started_at=NULL,
   exam_submitted_at=NULL,
   duration_seconds=NULL,
   updated_at=NOW()
 WHERE id=%s
 """
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (int(candidate_id),))


# 根据id号删除候选者id
def delete_candidate(candidate_id: int) -> None:
    sql = "DELETE FROM candidate WHERE id=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (int(candidate_id),))


# 根据id值创建候选者开始试卷时间
def set_candidate_exam_started_at(candidate_id: int, started_at) -> None:
    sql = """
UPDATE candidate
SET exam_started_at = COALESCE(exam_started_at, %s)
WHERE id = %s
"""
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (started_at, int(candidate_id)))


# 通过姓名和电话验证候选者
def verify_candidate(candidate_id: int, *, name: str, phone: str) -> bool:
    sql = "SELECT 1 FROM candidate WHERE id=%s AND name=%s AND phone=%s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (int(candidate_id), name, phone))
            return cur.fetchone() is not None


# 更新候选者数据表
def update_candidate_result(
    candidate_id: int,
    *,
    status: str,
    score: int,
    exam_started_at=None,
    exam_submitted_at=None,
    duration_seconds: int | None,
) -> None:
    sql = """
UPDATE candidate
SET status=%s,
    score=%s,
    exam_started_at=COALESCE(exam_started_at, %s),
    exam_submitted_at=%s,
    duration_seconds=%s
WHERE id=%s
"""
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    status,
                    int(score),
                    exam_started_at,
                    exam_submitted_at,
                    duration_seconds,
                    int(candidate_id),
                ),
            )
