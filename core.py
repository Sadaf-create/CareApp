"""Care Circle data and rules. SQLite locally; PostgreSQL for shared hosting."""
import os
import json
import uuid
import secrets
import hashlib
import hmac
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent

def config(key, default=''):
    value = os.getenv(key)
    if value is not None:
        return value
    path = ROOT / '.streamlit' / 'secrets.toml'
    if path.exists():
        return tomllib.loads(path.read_text(encoding='utf-8')).get(key, default)
    return default

def now():
    return int(datetime.now(timezone.utc).timestamp())

def new_id():
    return uuid.uuid4().hex

class DB:
    def __init__(self, conn, postgres):
        self.conn, self.postgres = conn, postgres
    def run(self, sql, args=()):
        return self.conn.execute(sql.replace('?', '%s') if self.postgres else sql, args)
    def one(self, sql, args=()):
        row = self.run(sql, args).fetchone()
        return dict(row) if row else None
    def all(self, sql, args=()):
        return [dict(r) for r in self.run(sql, args).fetchall()]

@contextmanager
def db():
    url = config('DATABASE_URL')
    if url:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=15)
    else:
        conn = sqlite3.connect(str(config('SQLITE_PATH', ROOT / 'care.db')), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('BEGIN IMMEDIATE')
    try:
        yield DB(conn, bool(url))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

SCHEMA = [
'''CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 password TEXT NOT NULL, timezone TEXT NOT NULL, telegram TEXT NOT NULL DEFAULT '',
 link_code TEXT NOT NULL DEFAULT '', link_until BIGINT NOT NULL DEFAULT 0,
 failures INTEGER NOT NULL DEFAULT 0, locked_until BIGINT NOT NULL DEFAULT 0)''',
'''CREATE TABLE IF NOT EXISTS circles (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL REFERENCES users(id),
 invite TEXT UNIQUE NOT NULL, priority INTEGER NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS members (
 circle_id TEXT NOT NULL REFERENCES circles(id), user_id TEXT NOT NULL REFERENCES users(id),
 PRIMARY KEY(circle_id,user_id))''',
'''CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, circle_id TEXT NOT NULL REFERENCES circles(id),
 creator TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, details TEXT NOT NULL,
 location TEXT NOT NULL, start BIGINT NOT NULL, duration INTEGER NOT NULL,
 status TEXT NOT NULL, assignee TEXT REFERENCES users(id), revision INTEGER NOT NULL,
 created BIGINT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS responses (
 task_id TEXT NOT NULL REFERENCES tasks(id), user_id TEXT NOT NULL REFERENCES users(id),
 answer TEXT NOT NULL, proposed BIGINT, note TEXT NOT NULL, updated BIGINT NOT NULL,
 PRIMARY KEY(task_id,user_id))''',
'''CREATE TABLE IF NOT EXISTS notices (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), task_id TEXT REFERENCES tasks(id),
 revision INTEGER NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
 due BIGINT NOT NULL, expires BIGINT NOT NULL, seen INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 retry_at BIGINT NOT NULL DEFAULT 0, lease_until BIGINT NOT NULL DEFAULT 0,
 UNIQUE(user_id,task_id,revision,kind))''',
'''CREATE TABLE IF NOT EXISTS worker_state (id TEXT PRIMARY KEY, value TEXT NOT NULL)'''
]

def init():
    with db() as d:
        for sql in SCHEMA:
            d.run(sql)
        # Prevent accidental anonymous access via Supabase's public Data API.
        # The server uses the private PostgreSQL connection, never a browser key.
        if d.postgres:
            for table in ('users','circles','members','tasks','responses','notices','worker_state'):
                d.run(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
    return salt + ':' + digest

def register(username, name, password, tz):
    from zoneinfo import ZoneInfo
    ZoneInfo(tz)
    username = username.strip().lower()
    if not 3 <= len(username) <= 40 or not all(c.isalnum() or c in '._-' for c in username):
        raise ValueError('Use a username of 3–40 letters, numbers, dots, underscores or hyphens.')
    if not name.strip() or len(name.strip()) > 80 or len(password) < 10 or len(password) > 128:
        raise ValueError('Enter a name (up to 80 characters) and a password of 10–128 characters.')
    uid = new_id()
    with db() as d:
        if d.one('SELECT id FROM users WHERE username=?', (username,)):
            raise ValueError('That username is already taken.')
        d.run('INSERT INTO users(id,username,name,password,timezone) VALUES(?,?,?,?,?)',
              (uid, username, name.strip(), password_hash(password), tz))
    return uid

def login(username, password):
    with db() as d:
        u = d.one('SELECT * FROM users WHERE username=?', (username.strip().lower(),))
        if not u:
            password_hash(password[:128], '00' * 16)
            return None
        if u['locked_until'] > now():
            return None
        valid = hmac.compare_digest(password_hash(password[:128], u['password'].split(':')[0]), u['password'])
        if not valid:
            failures = u['failures'] + 1
            d.run('UPDATE users SET failures=?,locked_until=? WHERE id=?',
                  (failures, now()+300 if failures >= 5 else 0, u['id']))
            return None
        d.run('UPDATE users SET failures=0,locked_until=0 WHERE id=?', (u['id'],))
        return u['id']

def user(uid):
    with db() as d:
        return d.one('SELECT id,username,name,timezone,telegram FROM users WHERE id=?', (uid,))

def check_member(d, uid, cid):
    if not d.one('SELECT user_id FROM members WHERE circle_id=? AND user_id=?', (cid,uid)):
        raise ValueError('You are not a member of this care group.')

def create_circle(uid, name, priority):
    if not name.strip() or len(name) > 80:
        raise ValueError('Enter a group name of up to 80 characters.')
    cid = new_id()
    with db() as d:
        d.run('INSERT INTO circles VALUES(?,?,?,?,?)', (cid,name.strip(),uid,secrets.token_urlsafe(18),int(priority)))
        d.run('INSERT INTO members VALUES(?,?)', (cid,uid))
    return cid

def join_circle(uid, invite):
    with db() as d:
        c = d.one('SELECT * FROM circles WHERE invite=?', (invite.strip(),))
        if not c:
            raise ValueError('Invalid invitation code. Ask the group creator for the current code.')
        d.run('INSERT INTO members VALUES(?,?) ON CONFLICT DO NOTHING', (c['id'],uid))
        return c['id']

def circles(uid):
    with db() as d:
        return d.all('SELECT c.* FROM circles c JOIN members m ON c.id=m.circle_id WHERE m.user_id=? ORDER BY priority,name', (uid,))

def members(uid, cid):
    with db() as d:
        check_member(d,uid,cid)
        return d.all('SELECT u.id,u.name,u.username FROM users u JOIN members m ON u.id=m.user_id WHERE m.circle_id=? ORDER BY u.name', (cid,))

def change_circle(uid, cid, priority, rotate=False):
    with db() as d:
        c = d.one('SELECT * FROM circles WHERE id=? AND owner=?', (cid,uid))
        if not c:
            raise ValueError('Only the group creator can change group settings.')
        d.run('UPDATE circles SET priority=?,invite=? WHERE id=?',
              (int(priority),secrets.token_urlsafe(18) if rotate else c['invite'],cid))

def notice(d, uid, task, kind, message, due=None):
    d.run('''INSERT INTO notices(id,user_id,task_id,revision,kind,message,due,expires)
             VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
          (new_id(),uid,task['id'],task['revision'],kind,message,now() if due is None else due,task['start']))

def announce(d, t, kind, message):
    for m in d.all('SELECT user_id FROM members WHERE circle_id=?', (t['circle_id'],)):
        notice(d,m['user_id'],t,kind,message)

def get_task(d, uid, tid, lock=False):
    sql = 'SELECT * FROM tasks WHERE id=?'
    if lock and d.postgres:
        sql += ' FOR UPDATE'
    t = d.one(sql, (tid,))
    if not t:
        raise ValueError('Task not found.')
    check_member(d,uid,t['circle_id'])
    return t

def create_task(uid, cid, title, details, location, start, duration):
    if not title.strip() or len(title)>120 or len(details)>2000 or len(location)>200:
        raise ValueError('Title required (max 120 characters); details max 2000, location max 200.')
    if start <= now() or not 15 <= duration <= 720:
        raise ValueError('Choose a future date/time and a duration between 15 and 720 minutes.')
    t = dict(id=new_id(),circle_id=cid,creator=uid,title=title.strip(),details=details,
             location=location,start=int(start),duration=int(duration),status='Open',assignee=None,revision=1,created=now())
    with db() as d:
        check_member(d,uid,cid)
        d.run('INSERT INTO tasks(id,circle_id,creator,title,details,location,start,duration,status,assignee,revision,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', tuple(t.values()))
        announce(d,t,'request','A new care request is waiting for a response.')
    return t['id']

def reminders(d, t):
    recipients = {t['creator'],t['assignee']}
    for hours in (12,1):
        due = t['start']-hours*3600
        # Confirmation arrives immediately; only future lead-time alarms are scheduled.
        if due >= now():
            for uid in recipients:
                notice(d,uid,t,f'reminder_{hours}',f'{hours}-hour reminder for your confirmed care task.',due)

def respond(uid, tid, answer, proposed=None, note=''):
    if answer not in ('Yes','No','Other time') or len(note)>500:
        raise ValueError('Choose Yes, No or Other time; note max 500 characters.')
    with db() as d:
        t = get_task(d,uid,tid,True)
        if t['creator'] == uid:
            raise ValueError('The requester cannot volunteer for their own task.')
        if t['status'] != 'Open' or t['start'] <= now():
            raise ValueError('This task is no longer open. Another member may have accepted it.')
        if answer == 'Other time' and (proposed is None or proposed <= now()):
            raise ValueError('Choose a future alternative date/time.')
        if answer != 'Other time':
            proposed = None
        d.run('''INSERT INTO responses VALUES(?,?,?,?,?,?) ON CONFLICT(task_id,user_id)
                 DO UPDATE SET answer=excluded.answer,proposed=excluded.proposed,note=excluded.note,updated=excluded.updated''',
              (tid,uid,answer,proposed,note,now()))
        if answer == 'Yes':
            d.run("UPDATE tasks SET status='Assigned',assignee=?,revision=revision+1 WHERE id=?", (uid,tid))
            t.update(status='Assigned',assignee=uid,revision=t['revision']+1)
            announce(d,t,'assigned','A member has accepted this care task.')
            reminders(d,t)
        else:
            notice(d,t['creator'],t,'response_'+uid+'_'+str(now()),'A member has responded to your care request.')

def approve_alternative(uid, tid, volunteer):
    with db() as d:
        t = get_task(d,uid,tid,True)
        if t['creator'] != uid or t['status'] != 'Open':
            raise ValueError('Only the requester can approve a time while the task is open.')
        r = d.one('SELECT * FROM responses WHERE task_id=? AND user_id=?', (tid,volunteer))
        check_member(d,volunteer,t['circle_id'])
        if not r or r['answer'] != 'Other time' or r['proposed'] <= now():
            raise ValueError('This proposal is no longer valid.')
        d.run("UPDATE tasks SET start=?,status='Assigned',assignee=?,revision=revision+1 WHERE id=?", (r['proposed'],volunteer,tid))
        t.update(start=r['proposed'],status='Assigned',assignee=volunteer,revision=t['revision']+1)
        announce(d,t,'assigned','The requester approved a new time. This care task is confirmed.')
        reminders(d,t)

def finish(uid, tid, action):
    if action not in ('Done','Cancelled','Open'):
        raise ValueError('Invalid action.')
    with db() as d:
        t = get_task(d,uid,tid,True)
        allowed = uid == t['creator'] or (uid == t['assignee'] and action in ('Done','Open'))
        if not allowed or t['status'] not in ('Open','Assigned'):
            raise ValueError('You cannot change this task.')
        if action == 'Done' and t['status'] != 'Assigned':
            raise ValueError('Only an assigned task can be marked done.')
        if action == 'Open' and (t['status'] != 'Assigned' or t['start'] <= now()):
            raise ValueError('Only a future assigned task can be reopened.')
        d.run('UPDATE tasks SET status=?,assignee=?,revision=revision+1 WHERE id=?',
              (action,None if action=='Open' else t['assignee'],tid))
        if action == 'Open':
            d.run('DELETE FROM responses WHERE task_id=?', (tid,))
        t.update(status=action,revision=t['revision']+1)
        announce(d,t,'status','Care task status changed to '+action+'.')

def task_list(uid, cid):
    with db() as d:
        check_member(d,uid,cid)
        return d.all('''SELECT t.*,u.name AS requester,a.name AS helper FROM tasks t
           JOIN users u ON u.id=t.creator LEFT JOIN users a ON a.id=t.assignee
           WHERE t.circle_id=? ORDER BY t.start DESC''', (cid,))

def response_list(uid, tid):
    with db() as d:
        t = get_task(d,uid,tid)
        return d.all('''SELECT u.id,u.name,u.username,r.answer,r.proposed,r.note
           FROM members m JOIN users u ON u.id=m.user_id
           LEFT JOIN responses r ON r.user_id=u.id AND r.task_id=?
           WHERE m.circle_id=? AND u.id<>? ORDER BY u.name''', (tid,t['circle_id'],t['creator']))

def inbox(uid):
    with db() as d:
        return d.all('''SELECT n.*,t.status,t.start FROM notices n JOIN tasks t ON t.id=n.task_id
        WHERE n.user_id=? AND n.due<=? AND n.revision=t.revision ORDER BY n.due DESC LIMIT 100''', (uid,now()))

def mark_seen(uid):
    with db() as d:
        d.run('UPDATE notices SET seen=1 WHERE user_id=? AND due<=?', (uid,now()))

def link_code(uid):
    code = secrets.token_urlsafe(24)
    with db() as d:
        d.run('UPDATE users SET link_code=?,link_until=? WHERE id=?', (code,now()+900,uid))
    return code

def unlink(uid):
    with db() as d:
        d.run("UPDATE users SET telegram='',link_code='',link_until=0 WHERE id=?", (uid,))

def connect_telegram(code, chat_id):
    with db() as d:
        u = d.one('SELECT id FROM users WHERE link_code=? AND link_until>?', (code,now()))
        if not u:
            return False
        # A private chat belongs to one app account; linking again moves the binding.
        d.run("UPDATE users SET telegram='' WHERE telegram=?", (str(chat_id),))
        d.run("UPDATE users SET telegram=?,link_code='',link_until=0 WHERE id=?", (str(chat_id),u['id']))
        return True

def heartbeat():
    with db() as d:
        r = d.one("SELECT value FROM worker_state WHERE id='heartbeat'")
        return int(r['value']) if r else 0

def calendar(t):
    def esc(s):
        return str(s).replace('\\','\\\\').replace('\n','\\n').replace(';','\\;').replace(',','\\,').replace('\r','')
    def stamp(ts):
        return datetime.fromtimestamp(ts,timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Care Circle//Prototype//EN','BEGIN:VEVENT',
             'UID:'+t['id']+'@carecircle.local','SEQUENCE:'+str(t['revision']),
             'DTSTAMP:'+stamp(now()),'DTSTART:'+stamp(t['start']),
             'DTEND:'+stamp(t['start']+t['duration']*60),'SUMMARY:'+esc(t['title']),
             'DESCRIPTION:'+esc(t['details']),'LOCATION:'+esc(t['location'])]
    for hours in (12,1):
        lines += ['BEGIN:VALARM','ACTION:DISPLAY',f'TRIGGER:-PT{hours}H','DESCRIPTION:Care task reminder','END:VALARM']
    lines += ['END:VEVENT','END:VCALENDAR']
    # Fold UTF-8 lines to the RFC 5545 75-octet limit without splitting characters.
    folded = []
    for line in lines:
        piece=''
        for char in line:
            if len((piece+char).encode())>75:
                folded.append(piece)
                piece=' '
            piece+=char
        folded.append(piece)
    return ('\r\n'.join(folded)+'\r\n').encode()
