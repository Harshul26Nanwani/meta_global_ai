import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / 'traceback.db'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                parent_run_id TEXT,
                task_description TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                agent_version TEXT,
                model_provider TEXT,
                model_identifier TEXT,
                metadata TEXT DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                input_payload TEXT DEFAULT '{}',
                output_payload TEXT DEFAULT '{}',
                status TEXT NOT NULL,
                artifact_references TEXT DEFAULT '[]',
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS diagnoses (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                suspected_divergence_event_id TEXT NOT NULL,
                supporting_event_ids TEXT DEFAULT '[]',
                classification TEXT NOT NULL,
                confidence_estimate TEXT,
                alternative_explanations TEXT DEFAULT '[]',
                recommended_correction TEXT NOT NULL,
                replay_plan TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_results (
                id TEXT PRIMARY KEY,
                original_run_id TEXT NOT NULL,
                replay_run_id TEXT NOT NULL,
                diagnosis_id TEXT,
                correction_applied TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                assertion_results TEXT DEFAULT '{}',
                state_diff TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(original_run_id) REFERENCES runs(id),
                FOREIGN KEY(replay_run_id) REFERENCES runs(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_run_record(task_description: str, scenario_id: str, agent_version: str,
                     model_provider: str, model_identifier: str, parent_run_id: Optional[str] = None,
                     status: str = 'running', metadata: Optional[Dict[str, Any]] = None):
    metadata = metadata or {}
    run_id = str(uuid.uuid4())
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO runs (
                id, parent_run_id, task_description, scenario_id, status,
                started_at, completed_at, agent_version, model_provider,
                model_identifier, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, parent_run_id, task_description, scenario_id, status, ts, None,
             agent_version, model_provider, model_identifier, json.dumps(metadata))
        )
        conn.commit()
        return get_run(run_id)
    finally:
        conn.close()


def get_run(run_id: str):
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_runs():
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT runs.*,
                   COALESCE(event_counts.event_count, 0) AS event_count,
                   COALESCE(event_counts.failed_event_count, 0) AS failed_event_count
            FROM runs
            LEFT JOIN (
                SELECT run_id,
                       COUNT(*) AS event_count,
                       SUM(CASE WHEN status = 'failure' THEN 1 ELSE 0 END) AS failed_event_count
                FROM events
                GROUP BY run_id
            ) AS event_counts ON event_counts.run_id = runs.id
            ORDER BY runs.started_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_events(run_id: str):
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM events WHERE run_id = ? ORDER BY sequence_number ASC',
            (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_event_record(run_id: str, event_type: str, status: str, input_payload: Optional[Dict[str, Any]] = None,
                       output_payload: Optional[Dict[str, Any]] = None, artifact_references: Optional[List[str]] = None):
    conn = get_connection()
    try:
        next_sequence = conn.execute(
            'SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM events WHERE run_id = ?',
            (run_id,)
        ).fetchone()[0]
        event_id = str(uuid.uuid4())
        payload = input_payload or {}
        output = output_payload or {}
        refs = artifact_references or []
        conn.execute(
            """
            INSERT INTO events (
                id, run_id, sequence_number, timestamp, event_type,
                input_payload, output_payload, status, artifact_references
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, run_id, next_sequence, now_iso(), event_type,
             json.dumps(payload), json.dumps(output), status, json.dumps(refs))
        )
        conn.commit()
        row = conn.execute('SELECT * FROM events WHERE id = ?', (event_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def create_diagnosis_record(run_id: str, summary: str, suspected_divergence_event_id: str,
                           supporting_event_ids: List[str], classification: str,
                           confidence_estimate: Optional[str], alternative_explanations: List[str],
                           recommended_correction: str, replay_plan: Optional[Dict[str, Any]] = None):
    diagnosis_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO diagnoses (
                id, run_id, summary, suspected_divergence_event_id,
                supporting_event_ids, classification, confidence_estimate,
                alternative_explanations, recommended_correction, replay_plan, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (diagnosis_id, run_id, summary, suspected_divergence_event_id,
             json.dumps(supporting_event_ids), classification, confidence_estimate,
             json.dumps(alternative_explanations), recommended_correction,
             json.dumps(replay_plan or {}), now_iso())
        )
        conn.commit()
        row = conn.execute('SELECT * FROM diagnoses WHERE id = ?', (diagnosis_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_latest_diagnosis_for_run(run_id: str):
    conn = get_connection()
    try:
        row = conn.execute(
            'SELECT * FROM diagnoses WHERE run_id = ? ORDER BY created_at DESC LIMIT 1',
            (run_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_replay_record(original_run_id: str, replay_run_id: str, diagnosis_id: Optional[str],
                        correction_applied: str, verification_status: str,
                        assertion_results: Optional[Dict[str, Any]] = None, state_diff: Optional[Dict[str, Any]] = None):
    record_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO replay_results (
                id, original_run_id, replay_run_id, diagnosis_id,
                correction_applied, verification_status, assertion_results, state_diff, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (record_id, original_run_id, replay_run_id, diagnosis_id, correction_applied,
             verification_status, json.dumps(assertion_results or {}), json.dumps(state_diff or {}), now_iso())
        )
        conn.commit()
        row = conn.execute('SELECT * FROM replay_results WHERE id = ?', (record_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_replay_records(original_run_id: str):
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM replay_results WHERE original_run_id = ? ORDER BY created_at DESC',
            (original_run_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


init_db()
