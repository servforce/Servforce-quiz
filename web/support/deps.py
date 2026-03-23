from __future__ import annotations

import html
import os
import re
import shutil
import base64
import hashlib
import hmac
import secrets
import threading
import time as time_module
import zipfile
from datetime import datetime, timezone, timedelta
from datetime import date, time as dt_time
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from markupsafe import Markup

from config import ADMIN_PASSWORD, ADMIN_USERNAME, BASE_DIR, SECRET_KEY, STORAGE_DIR, logger
from db import (
    cleanup_duplicate_system_alert_logs,
    create_candidate,
    create_exam_paper,
    delete_exam_assets,
    delete_exam_definition,
    count_candidates,
    count_exam_papers,
    count_operation_logs,
    count_operation_logs_by_category,
    get_assignment_record,
    get_exam_archive_by_name,
    get_exam_archive_by_token,
    get_exam_asset,
    get_exam_definition,
    get_exam_key_by_public_invite_token,
    get_exam_public_invite,
    delete_candidate,
    get_exam_paper_by_token,
    get_candidate,
    get_candidate_name_from_logs,
    get_candidate_by_phone,
    get_candidate_resume,
    init_db,
    list_candidates,
    list_assignment_tokens,
    list_exam_archives_for_phone,
    list_exam_definitions,
    list_exam_papers,
    list_estimated_sms_calls_daily_counts,
    list_operation_daily_counts,
    list_operation_logs,
    list_operation_logs_after_id,
    list_system_status_daily_metrics,
    mark_exam_deleted,
    get_runtime_daily_metric_int,
    get_runtime_daily_metric_json,
    get_runtime_kv,
    rename_assignment_exam_key,
    rename_exam_archives_exam_key,
    rename_exam_assets,
    rename_exam_definition,
    rename_exam_key,
    replace_exam_assets,
    save_assignment_record,
    save_exam_archive,
    save_exam_definition,
    set_exam_public_invite,
    set_runtime_daily_metric_json,
    set_runtime_kv,
    incr_runtime_daily_metric_int,
    set_exam_paper_entered_at,
    set_exam_paper_finished_at,
    set_exam_paper_invite_window_if_missing,
    set_exam_paper_status,
    update_candidate,
    update_candidate_resume,
    update_candidate_resume_parsed,
    update_exam_paper_result,
    verify_candidate,
)
import markdown as mdlib
from qml.parser import QmlParseError, parse_qml_markdown
from services.assignment_service import (
    assignment_locked,
    compute_min_submit_seconds,
    create_assignment,
    load_assignment,
    save_assignment,
)
from services.aliyun_sms import send_sms_verify_code
from services.audit_context import audit_context, get_audit_context
from services.grading_service import generate_candidate_remark, grade_attempt
from services.exam_generation_service import check_exam_prompt_completeness, generate_exam_from_prompt
from services.resume_service import (
    clean_projects_raw_for_display,
    extract_resume_text,
    extract_resume_section,
    extract_experience_raw,
    parse_resume_details_llm,
    parse_resume_identity_fast,
    parse_resume_identity_llm,
    parse_resume_name_llm,
    split_projects_raw_into_blocks,
)
from services.system_log import log_event
from services.system_metrics import (
    backfill_missing_system_alert_levels,
    emit_alerts_for_current_snapshot,
    get_daily_metric,
    incr_sms_calls_and_alert,
)
from services.university_tags import classify_university
from storage.json_store import ensure_dirs
from web.auth import admin_required
