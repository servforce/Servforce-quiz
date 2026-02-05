from __future__ import annotations

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
  status           candidate_status NOT NULL DEFAULT 'created',
  exam_key         TEXT NULL,
  score            INT NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
  exam_started_at  TIMESTAMPTZ NULL,
  exam_submitted_at TIMESTAMPTZ NULL,
  duration_seconds INT NULL CHECK (duration_seconds IS NULL OR duration_seconds >= 0)
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

-- Ensure status default is "created" even when the table already existed (CREATE TABLE IF NOT EXISTS won't update defaults).
ALTER TABLE candidate ALTER COLUMN status SET DEFAULT 'created'::candidate_status;

 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS exam_key TEXT NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS exam_started_at TIMESTAMPTZ NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS exam_submitted_at TIMESTAMPTZ NULL;
 ALTER TABLE candidate ADD COLUMN IF NOT EXISTS duration_seconds INT NULL;

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
    limit: int | None = None, offset: int = 0, *, query: str | None = None
) -> list[dict[str, Any]]:
    # 查询的sql语句
    sql = """
SELECT id, name, phone, created_at, status, exam_key, score, exam_started_at, exam_submitted_at, duration_seconds
FROM candidate
"""
    params: list[Any] = []      # 最多返回多少条
    if query:   # 搜索关键字
        sql += " WHERE name ILIKE %s OR phone LIKE %s"      # 不区分大小写的模糊查询
        q = f"%{query}%"    # 包含query这个内容就可以
        params.extend([q, q])   # 一个给name，一个给phone
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
        sql += " WHERE name ILIKE %s OR phone LIKE %s"
        q = f"%{query}%"
        params.extend([q, q])
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


def has_recent_created_by_phone(phone: str, *, months: int = 6) -> bool:
    if months <= 0:
        return False
    sql = """
SELECT 1
FROM candidate
WHERE phone=%s
  AND created_at >= (NOW() - (%s || ' months')::interval)
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


def has_recent_identity(name: str, phone: str, *, months: int = 6) -> bool:
    """
    Business rule helper: treat (name, phone) as an identity. If an identity was
    created within the last `months`, consider it "recent".
    """
    if months <= 0:
        return False
    sql = """
SELECT 1
FROM candidate
WHERE name=%s AND phone=%s
  AND created_at >= (NOW() - (%s || ' months')::interval)
LIMIT 1
"""
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(name or ""), str(phone or ""), int(months)))
            return cur.fetchone() is not None


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
SELECT id, name, phone, created_at, status, exam_key, score, exam_started_at, exam_submitted_at, duration_seconds
FROM candidate
WHERE id = %s
"""
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (int(candidate_id),))
            row = cur.fetchone()
            return dict(row) if row else None

# 设置id值候选者的状态
def set_candidate_status(candidate_id: int, status: str) -> None:
    sql = "UPDATE candidate SET status = %s WHERE id = %s"
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (status, int(candidate_id)))

# 根据id值设置试卷id值
def set_candidate_exam_key(candidate_id: int, exam_key: str) -> None:
    sql = "UPDATE candidate SET exam_key=%s WHERE id=%s"
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
        sql = "UPDATE candidate SET name=%s, phone=%s WHERE id=%s"
        params = (name, phone, int(candidate_id))
    else:
        sql = "UPDATE candidate SET name=%s, phone=%s, created_at=%s WHERE id=%s"
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
  duration_seconds=NULL
WHERE id=%s
"""
    with conn_scope() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (int(candidate_id),))


def bulk_import_candidates(
    records: list[dict[str, Any]], *, overwrite_after_months: int = 6
) -> tuple[int, int]:
    """
    Bulk import candidates from a file:
    - If phone exists and created_at is within overwrite_after_months: reject.
    - If phone exists and is older: overwrite (reset as new).
    - If phone does not exist: create.

    Returns: (created_count, updated_count)
    """
    created = 0
    updated = 0
    months = int(overwrite_after_months)
    with conn_scope() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for r in records:
                name = str(r.get("name") or "").strip()
                phone = str(r.get("phone") or "").strip()
                exam_key = (str(r.get("exam_key") or "").strip() or None)

                cur.execute(
                    """
SELECT id
FROM candidate
WHERE phone=%s
ORDER BY id DESC
LIMIT 1
FOR UPDATE
""",
                    (phone,),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
SELECT 1
FROM candidate
WHERE phone=%s
  AND created_at >= (NOW() - (%s || ' months')::interval)
LIMIT 1
""",
                        (phone, months),
                    )
                    if cur.fetchone() is not None:
                        raise RuntimeError("recent_candidate_in_file")

                    cur.execute(
                        """
UPDATE candidate
SET
  name=%s,
  phone=%s,
  created_at=NOW(),
  status='created',
  exam_key=%s,
  score=0,
  exam_started_at=NULL,
  exam_submitted_at=NULL,
  duration_seconds=NULL
WHERE id=%s
""",
                        (name, phone, exam_key, int(row["id"])),
                    )
                    updated += 1
                else:
                    cur.execute(
                        """
INSERT INTO candidate(name, phone, exam_key)
VALUES (%s, %s, %s)
RETURNING id
""",
                        (name, phone, exam_key),
                    )
                    _ = cur.fetchone()
                    created += 1

    return created, updated

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
