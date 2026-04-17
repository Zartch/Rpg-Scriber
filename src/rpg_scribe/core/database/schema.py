"""Database schema SQL DDL for RPG Scribe."""
from __future__ import annotations


SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    game_system TEXT,
    language TEXT DEFAULT 'es',
    description TEXT,
    campaign_summary TEXT DEFAULT '',
    speaker_map JSON,
    dm_speaker_id TEXT,
    custom_instructions TEXT,
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    discord_id TEXT,
    discord_name TEXT,
    character_name TEXT,
    character_description TEXT
);

CREATE TABLE IF NOT EXISTS npcs (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    name TEXT,
    description TEXT,
    first_seen_session TEXT,
    merged_into TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    started_at REAL,
    ended_at REAL,
    session_summary TEXT,
    session_chronology TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    speaker_id TEXT,
    speaker_name TEXT,
    text TEXT,
    timestamp REAL,
    confidence REAL,
    is_ingame BOOLEAN
);

CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    name TEXT,
    description TEXT,
    first_seen_session TEXT,
    merged_into TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS campaign_entities (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    name TEXT,
    entity_type TEXT,
    description TEXT,
    first_seen_session TEXT,
    merged_into TEXT DEFAULT '',
    tags_json TEXT DEFAULT '[]',
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    question TEXT,
    answer TEXT,
    answered_at REAL,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS relationship_types (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    canonical_key TEXT NOT NULL,
    label TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    aliases_json TEXT,
    usage_count INTEGER DEFAULT 0,
    relation_family TEXT DEFAULT '',
    polarity TEXT DEFAULT 'neutral',
    is_canonical INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL,
    UNIQUE (campaign_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS character_relationships (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    source_key TEXT NOT NULL,
    target_key TEXT NOT NULL,
    type_key TEXT NOT NULL,
    type_label TEXT NOT NULL,
    notes TEXT,
    relation_family TEXT DEFAULT '',
    strength REAL DEFAULT 0.5,
    confidence REAL DEFAULT 0.5,
    polarity TEXT DEFAULT 'neutral',
    certainty TEXT DEFAULT 'explicit',
    origin TEXT DEFAULT 'extracted',
    is_active INTEGER DEFAULT 1,
    source_session_id TEXT DEFAULT '',
    evidence_snippets_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    type_label_raw TEXT DEFAULT '',
    created_at REAL,
    updated_at REAL,
    UNIQUE (campaign_id, source_key, target_key, type_key)
);

CREATE TABLE IF NOT EXISTS campaign_summaries (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    content TEXT NOT NULL,
    trigger_session_id TEXT,
    session_count INTEGER DEFAULT 0,
    generated_at REAL
);

CREATE TABLE IF NOT EXISTS word_replacements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT REFERENCES campaigns(id),
    original_word TEXT NOT NULL,
    replacement_word TEXT NOT NULL,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS transcription_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transcription_id INTEGER REFERENCES transcriptions(id),
    original_word TEXT NOT NULL,
    new_word TEXT NOT NULL,
    word_position INTEGER,
    edited_at REAL
);
"""
