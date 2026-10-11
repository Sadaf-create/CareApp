"""Care Circle — run with: python -m streamlit run app.py"""
import csv
import io
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote
import streamlit as st
import core

st.set_page_config(page_title='Care Circle',page_icon='🤝',layout='centered')
# Community Cloud exposes configured secrets here; the worker reads the local TOML.
for key in ('DATABASE_URL','TELEGRAM_BOT_TOKEN','TELEGRAM_BOT_USERNAME','APP_URL'):
    if key not in __import__('os').environ:
        try:
            if key in st.secrets:
                __import__('os').environ[key]=str(st.secrets[key])
        except FileNotFoundError:
            pass

st.markdown('''<style>
.stApp {background: #f6f8fc;}
h1,h2,h3 {color:#173953;}
.stButton button {min-height:48px; border-radius:12px;}
[data-testid="stMetric"] {background:white; padding:16px; border-radius:14px;}
</style>''',unsafe_allow_html=True)
st.title('🤝 Care Circle')
st.caption('Ask for help. Find a willing member. Keep everyone informed.')
try:
    core.init()
except Exception:
    st.error('Cannot connect to the database. Check the private database settings and try again.')
    st.stop()

TZS=['Asia/Karachi','Asia/Riyadh','Asia/Dubai','Europe/London','Europe/Paris','America/New_York','America/Chicago','America/Los_Angeles','Asia/Kolkata','Asia/Singapore','Australia/Sydney','UTC']

def run(action,*args):
    try:
        result=action(*args)
        st.session_state['flash']='Saved successfully.'
        return result
    except ValueError as e:
        st.session_state['flash_error']=str(e)
        st.error(str(e))
    except Exception:
        st.session_state['flash_error']='Could not save. Refresh and try again; check database settings if the problem continues.'
        st.error(st.session_state['flash_error'])
    return None

def refresh():
    st.rerun()

def when(ts,tz):
    return datetime.fromtimestamp(ts,ZoneInfo(tz)).strftime('%a %d %b %Y · %I:%M %p %Z') if ts else '—'

def timestamp(day,clock,tz):
    wall=datetime.combine(day,clock)
    zone=ZoneInfo(tz)
    a=wall.replace(tzinfo=zone,fold=0)
    b=wall.replace(tzinfo=zone,fold=1)
    valid=[]
    for candidate in (a,b):
        if datetime.fromtimestamp(candidate.timestamp(),zone).replace(tzinfo=None)==wall:
            valid.append(candidate)
    if not valid:
        raise ValueError('That local time does not exist because clocks change. Choose another time.')
    if a.utcoffset()!=b.utcoffset() and len(valid)==2:
        raise ValueError('That time occurs twice because clocks change. Choose an unambiguous time.')
    return int(valid[0].timestamp())

if 'uid' not in st.session_state:
    signin,signup=st.tabs(['Sign in','Create account'])
    with signin:
        with st.form('login'):
            username=st.text_input('Username')
            password=st.text_input('Password',type='password',max_chars=128)
            if st.form_submit_button('Sign in',use_container_width=True):
                uid=core.login(username,password)
                if uid:
                    st.session_state['uid']=uid
                    refresh()
                else:
                    st.error('Incorrect details, or the account is temporarily locked. After five failed attempts, wait five minutes.')
    with signup:
        st.info('Create separate accounts for the elder and each family member. No paid services or AI key required.')
        with st.form('register'):
            name=st.text_input('Your name',max_chars=80)
            uname=st.text_input('Choose a username',max_chars=40)
            pw=st.text_input('Choose a password (at least 10 characters)',type='password',max_chars=128)
            confirm=st.text_input('Confirm password',type='password',max_chars=128)
            tz=st.selectbox('Your timezone',TZS)
            if st.form_submit_button('Create account',use_container_width=True):
                if pw!=confirm:
                    st.error('Passwords do not match.')
                else:
                    uid=run(core.register,uname,name,pw,tz)
                    if uid:
                        st.session_state['uid']=uid
                        refresh()
    st.stop()

uid=st.session_state['uid']
u=core.user(uid)
if not u:
    st.session_state.clear()
    refresh()
tz=u['timezone']
with st.sidebar:
    st.subheader(u['name'])
    st.caption('Timezone: '+tz)
    if st.button('Refresh updates',use_container_width=True):
        refresh()
    if st.button('Sign out',use_container_width=True):
        st.session_state.clear()
        refresh()
    st.caption('The prototype refreshes when you interact or press Refresh. Telegram messages arrive without keeping this page open.')
if 'flash' in st.session_state:
    st.success(st.session_state.pop('flash'))
if 'flash_error' in st.session_state:
    st.error(st.session_state.pop('flash_error'))

@st.fragment(run_every='30s')
def worker_status():
    beat=core.heartbeat()
    if beat and core.now()-beat<120:
        st.caption('🟢 Reminder worker checked in recently. Telegram delivery also requires your account to be linked.')
    else:
        st.warning('Phone reminder worker is offline or not configured. Calendar downloads and in-app messages are still available.')
worker_status()
if not core.config('DATABASE_URL'):
    st.info('Local mode: data is saved in care.db on this computer. For Community Cloud, configure shared PostgreSQL before using real data.')

page=st.radio('Open', ['Care tasks','My commitments','Care groups','Notifications','Phone reminders'],horizontal=True,label_visibility='collapsed')
cs=core.circles(uid)

if page=='Care groups':
    st.subheader('Your care groups')
    st.write('Create groups such as Family, Friends, or Neighbours. Priority 1 appears first; priority controls display order, not automatic escalation.')
    for c in cs:
        with st.expander(c['name']+' · Priority '+str(c['priority'])):
            st.write(', '.join(m['name'] for m in core.members(uid,c['id'])))
            st.caption('Invite only people you trust. Members can see requests and response summaries in this group.')
            st.code(c['invite'],language=None)
            url=core.config('APP_URL')
            text=f"Please join our Care Circle group: {c['name']}. Create an account, open Care groups → Join group, and enter this code: {c['invite']}"
            if url.startswith('https://'):
                text+='\n'+url
            st.link_button('Share invitation through WhatsApp','https://wa.me/?text='+quote(text))
            st.download_button('Download invitation text',text,file_name='care_invitation.txt',key='invite_'+c['id'])
            if c['owner']==uid:
                with st.form('priority_'+c['id']):
                    priority=st.selectbox('Group priority',[1,2,3],index=c['priority']-1,key='p_'+c['id'])
                    rotate=st.checkbox('Replace invitation code (old code stops working)',key='r_'+c['id'])
                    if st.form_submit_button('Save group settings'):
                        run(core.change_circle,uid,c['id'],priority,rotate)
                        refresh()
    left,right=st.tabs(['Create group','Join group'])
    with left:
        with st.form('circle'):
            name=st.text_input('Group name',max_chars=80)
            priority=st.selectbox('Priority',[1,2,3])
            if st.form_submit_button('Create group'):
                if run(core.create_circle,uid,name,priority):
                    refresh()
    with right:
        with st.form('join'):
            invite=st.text_input('Invitation code')
            if st.form_submit_button('Join group'):
                if run(core.join_circle,uid,invite):
                    refresh()

elif page=='Phone reminders':
    st.subheader('Connect Telegram reminders')
    st.write('Receive request updates and confirmed-task reminders 12 hours and 1 hour before the task. Both the requester and the assigned helper receive reminders.')
    st.caption('Only future reminder times are scheduled. If you accept a task less than an hour before it starts, you receive confirmation but no past reminder. Phone notification settings must allow Telegram alerts.')
    bot=core.config('TELEGRAM_BOT_USERNAME').lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}',bot) or not core.config('TELEGRAM_BOT_TOKEN'):
        st.warning('The app owner must add the Telegram bot token and bot username, then run worker.py. See README.md in the download.')
    else:
        st.write('Linked: '+('Yes' if u['telegram'] else 'No'))
        if st.button('Generate my connection link',use_container_width=True):
            code=core.link_code(uid)
            st.session_state['telegram_link']='https://t.me/'+bot+'?start='+code
        if 'telegram_link' in st.session_state:
            st.link_button('Open Telegram and press Start',st.session_state['telegram_link'],use_container_width=True)
            st.caption('Link expires after 15 minutes. Wait up to 20 seconds, then press Refresh updates. Keep this private link to yourself.')
        if u['telegram'] and st.button('Disconnect Telegram'):
            core.unlink(uid)
            st.session_state.pop('telegram_link',None)
            refresh()
    st.info('Backup option: download the confirmed task as a calendar event and import it into your phone calendar. Calendar apps handle imported alarms differently—test them on your phone.')

elif page=='Notifications':
    st.subheader('Your notifications')
    notes=core.inbox(uid)
    if not notes:
        st.info('No notifications yet.')
    for n in notes:
        with st.container(border=True):
            st.write(('🔵 ' if not n['seen'] else '')+n['message'])
            st.caption('Task '+n['task_id'][:8]+' · '+when(n['due'],tz)+' · Phone delivery: '+n['state'])
    if st.button('Mark all as read'):
        core.mark_seen(uid)
        refresh()

elif not cs:
    st.info('Open Care groups to create a group or join one using an invitation code.')
else:
    byid={c['id']:c for c in cs}
    cid=st.selectbox('Care group',list(byid),format_func=lambda x:byid[x]['name']+' · Priority '+str(byid[x]['priority']))
    tasks=core.task_list(uid,cid)
    if page=='Care tasks':
        with st.expander('➕ Request help',expanded=not tasks):
            with st.form('task'):
                title=st.text_input('What help do you need?',placeholder='Take me to my hospital appointment',max_chars=120)
                details=st.text_area('Instructions',max_chars=2000)
                location=st.text_input('Meeting place',max_chars=200)
                today=datetime.now(ZoneInfo(tz))
                day=st.date_input('Date',value=(today+timedelta(days=1)).date(),min_value=today.date())
                clock=st.time_input('Time',value=today.replace(hour=10,minute=0,second=0,microsecond=0).time())
                duration=st.number_input('Expected duration (minutes)',min_value=15,max_value=720,value=60,step=15)
                if st.form_submit_button('Send care request',use_container_width=True):
                    try:
                        start=timestamp(day,clock,tz)
                        if run(core.create_task,uid,cid,title,details,location,start,duration):
                            refresh()
                    except ValueError as e:
                        st.error(str(e))
    else:
        tasks=[t for t in tasks if t['assignee']==uid or t['creator']==uid]
    a,b,c=st.columns(3)
    a.metric('Open',sum(t['status']=='Open' for t in tasks))
    b.metric('Confirmed',sum(t['status']=='Assigned' for t in tasks))
    c.metric('Done',sum(t['status']=='Done' for t in tasks))
    show=st.selectbox('Show',['Upcoming','All','Open','Assigned','Done','Cancelled'])
    if show=='Upcoming':
        tasks=[t for t in tasks if t['start']>core.now() and t['status'] in ('Open','Assigned')]
        tasks.sort(key=lambda t:t['start'])
    elif show!='All':
        tasks=[t for t in tasks if t['status']==show]
    if not tasks:
        st.info('No tasks in this view.')
    report=[]
    for t in tasks:
        rs=core.response_list(uid,t['id'])
        for r in rs:
            report.append({'Task':t['title'],'Reference':t['id'][:8],'Scheduled':when(t['start'],tz),
                'Status':t['status'],'Assigned helper':t['helper'] or '', 'Member':r['name'],
                'Response':r['answer'] or 'Not responded','Proposed time':when(r['proposed'],tz),'Note':r['note'] or ''})
        with st.container(border=True):
            st.subheader(t['title'])
            st.write('📅 '+when(t['start'],tz))
            st.caption(t['status']+' · Requested by '+t['requester']+' · Reference '+t['id'][:8])
            if t['helper']:
                st.success('Confirmed helper: '+t['helper'])
            if t['location']:
                st.write('📍 '+t['location'])
            if t['details']:
                st.write(t['details'])
            st.caption('Expected duration: '+str(t['duration'])+' minutes')
            if t['status']=='Open' and t['start']>core.now() and uid!=t['creator']:
                with st.form('respond_'+t['id']):
                    answer=st.radio('Your response',['Yes','No','Other time'],horizontal=True,key='ans_'+t['id'])
                    st.caption('For Other time, choose a proposal below. Yes and No ignore these date/time fields.')
                    local=datetime.fromtimestamp(t['start'],ZoneInfo(tz))
                    day=st.date_input('Alternative date',value=local.date(),key='day_'+t['id'])
                    clock=st.time_input('Alternative time',value=local.time(),key='clock_'+t['id'])
                    note=st.text_input('Optional message',max_chars=500,key='note_'+t['id'])
                    if st.form_submit_button('Send response',use_container_width=True):
                        try:
                            proposed=timestamp(day,clock,tz) if answer=='Other time' else None
                            run(core.respond,uid,t['id'],answer,proposed,note)
                        except ValueError as e:
                            st.error(str(e))
                        else:
                            refresh()
            with st.expander('Responses and summary'):
                names={r['id']:r['name'] for r in rs}
                for r in rs:
                    st.write(r['name']+' — '+(r['answer'] or 'Not responded'))
                    if r['proposed']:
                        st.caption('Proposed: '+when(r['proposed'],tz))
                    if r['note']:
                        st.caption(r['note'])
                if not rs:
                    st.caption('Invite members to this group so they can respond.')
                if uid==t['creator'] and t['status']=='Open':
                    for r in rs:
                        if r['answer']=='Other time' and r['proposed']>core.now():
                            if st.button('Approve '+r['name']+' · '+when(r['proposed'],tz),key='approve_'+t['id']+r['id']):
                                run(core.approve_alternative,uid,t['id'],r['id'])
                                refresh()
            if t['status']=='Assigned' and uid in (t['creator'],t['assignee']):
                st.download_button('📅 Download phone calendar event',core.calendar(t),file_name='care_'+t['id'][:8]+'.ics',mime='text/calendar',key='ics_'+t['id'])
                st.caption('Import this event into your calendar. If the task is reopened or cancelled, remove its old calendar event manually.')
                if st.button('Mark done',key='done_'+t['id']):
                    run(core.finish,uid,t['id'],'Done')
                    refresh()
                if t['start']>core.now() and st.button('Release assignment and reopen',key='release_'+t['id']):
                    run(core.finish,uid,t['id'],'Open')
                    refresh()
            if uid==t['creator'] and t['status'] in ('Open','Assigned'):
                if st.button('Cancel task',key='cancel_'+t['id']):
                    run(core.finish,uid,t['id'],'Cancelled')
                    refresh()
    if report:
        output=io.StringIO()
        w=csv.DictWriter(output,fieldnames=list(report[0]))
        w.writeheader()
        # Prevent spreadsheet formula injection in member-provided values.
        w.writerows({k: ("'"+str(v) if str(v).lstrip().startswith(('=','+','-','@')) else v) for k,v in row.items()} for row in report)
        st.download_button('Download response summary (CSV)',output.getvalue().encode('utf-8-sig'),file_name='care_summary.csv',mime='text/csv')
