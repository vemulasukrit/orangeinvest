"""Durable local state. Provider commits are separate from agent commits."""
import json
import sqlite3
import threading
import uuid
from pathlib import Path


class Store:
    def __init__(self, path):
        if str(path) != ':memory:':
            Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path) if str(path)!=':memory:' else f'file:errand-{uuid.uuid4().hex}?mode=memory&cache=shared'
        self.uri = str(path)==':memory:'
        self.local = threading.local()
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memory(key TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, session_id TEXT, fingerprint TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, session_id TEXT, body TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS provider_bookings(id TEXT PRIMARY KEY, session_id TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS provider_results(id TEXT PRIMARY KEY, body TEXT);
        CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY, run_id TEXT, session_id TEXT, body TEXT);
        ''')
        self.db.commit()

    @property
    def db(self):
        if not getattr(self.local,'connection',None):
            self.local.connection=sqlite3.connect(self.path,check_same_thread=False,uri=self.uri,timeout=.25)
        return self.local.connection

    def close_thread(self):
        if getattr(self.local,'connection',None):
            self.local.connection.close()
            self.local.connection=None

    def save(self, s):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)', (s['session_id'], json.dumps(s)))

    def get(self, sid=None):
        row = self.db.execute('SELECT body FROM sessions WHERE id=?', (sid,)).fetchone() if sid else self.db.execute('SELECT body FROM sessions ORDER BY rowid LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None

    def bookings(self, sid):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM provider_bookings WHERE session_id=?', (sid,))]

    def memories(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM memory ORDER BY key')]
