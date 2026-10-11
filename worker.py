"""Run one copy: python worker.py. Keep this process online for phone reminders."""
import json
import logging
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
import core

LOG = logging.getLogger('care-worker')

def telegram(method, data):
    token = core.config('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('Telegram is not configured')
    req = urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,
              data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    # Never print request URLs or exception text, as they may contain the bot token.
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.load(response)
    if not result.get('ok'):
        raise RuntimeError('Telegram request failed')
    return result['result']

def poll_links():
    with core.db() as d:
        row=d.one("SELECT value FROM worker_state WHERE id='telegram_offset'")
        offset=int(row['value']) if row else 0
    updates=telegram('getUpdates',{'offset':offset,'timeout':0,'allowed_updates':['message']})
    for item in updates:
        message=item.get('message',{})
        chat=message.get('chat',{})
        text=message.get('text','')
        if chat.get('type')=='private' and text.startswith('/start '):
            code=text.split(' ',1)[1].strip()
            ok=core.connect_telegram(code,chat['id'])
            telegram('sendMessage',{'chat_id':chat['id'],'text':
                     'Care Circle reminders are connected. Keep Telegram notifications enabled.' if ok else
                     'Link expired or already used. Generate a new link inside Care Circle.'})
        elif chat.get('type')=='private' and text.startswith('/start'):
            telegram('sendMessage',{'chat_id':chat['id'],'text':'Log in to Care Circle and open Phone reminders to connect your account.'})
        with core.db() as d:
            d.run("INSERT INTO worker_state VALUES('telegram_offset',?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",(str(item['update_id']+1),))

def process_due(send=telegram):
    """One sweep; transactional claims prevent two workers sending a job together."""
    clock=core.now()
    with core.db() as d:
        d.run("INSERT INTO worker_state VALUES('heartbeat',?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",(str(clock),))
        jobs=d.all("""SELECT n.id FROM notices n WHERE n.state='pending' AND n.due<=?
                      AND n.retry_at<=? AND n.lease_until<=? ORDER BY n.due LIMIT 50""",(clock,clock,clock))
    count=0
    for job in jobs:
        with core.db() as d:
            cur=d.run("""UPDATE notices SET lease_until=? WHERE id=? AND state='pending'
                         AND lease_until<=? AND retry_at<=?""",(clock+120,job['id'],clock,clock))
            if cur.rowcount != 1:
                continue
            n=d.one('SELECT * FROM notices WHERE id=?',(job['id'],))
            t=d.one('SELECT * FROM tasks WHERE id=?',(n['task_id'],))
            u=d.one('SELECT telegram,timezone FROM users WHERE id=?',(n['user_id'],))
            stale = n['revision'] != t['revision'] or n['expires'] <= core.now()
            if n['kind'].startswith('reminder_'):
                stale = stale or t['status']!='Assigned' or n['user_id'] not in (t['creator'],t['assignee'])
            if stale:
                d.run("UPDATE notices SET state='expired',lease_until=0 WHERE id=?",(n['id'],))
                continue
            if not u['telegram']:
                d.run('UPDATE notices SET retry_at=?,lease_until=0 WHERE id=?',(clock+60,n['id']))
                continue
        try:
            date=datetime.fromtimestamp(t['start'],ZoneInfo(u['timezone'])).strftime('%d %b %Y, %I:%M %p %Z')
            late='\nDelivered late; check the scheduled time.' if n['kind'].startswith('reminder_') and core.now()-n['due']>120 else ''
            # No medical details, names or locations are sent to Telegram.
            text=n['message']+'\nTask reference: '+t['id'][:8]+'\nScheduled: '+date+late
            url=core.config('APP_URL')
            if url.startswith('https://'):
                text+='\nOpen Care Circle: '+url
            send('sendMessage',{'chat_id':u['telegram'],'text':text})
            with core.db() as d:
                d.run("UPDATE notices SET state='sent',attempts=attempts+1,lease_until=0 WHERE id=?",(n['id'],))
            count+=1
            time.sleep(0.05)
        except Exception:
            with core.db() as d:
                attempts=n['attempts']+1
                d.run('UPDATE notices SET attempts=?,retry_at=?,lease_until=0 WHERE id=?',
                     (attempts,core.now()+min(3600,30*2**min(attempts,7)),n['id']))
            LOG.warning('Notification delivery failed; retry scheduled (task %s).',t['id'][:8])
    return count

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    core.init()
    if not core.config('TELEGRAM_BOT_TOKEN'):
        LOG.error('Add TELEGRAM_BOT_TOKEN to .streamlit/secrets.toml or your environment first.')
        return
    LOG.info('Reminder worker started. Keep the computer awake and online. Run only one copy.')
    while True:
        try:
            poll_links()
            count=process_due()
            if count:
                LOG.info('Sent %s notification(s).',count)
        except Exception:
            LOG.warning('Database or Telegram connection failed. Will retry in 20 seconds.')
        time.sleep(20)

if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Worker stopped. Phone reminders are paused.')
