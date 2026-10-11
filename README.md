# Care Circle — free care coordination prototype

Built from Notes.docx and your description. Python + Streamlit; no n8n, Zapier,
OpenAI key, paid SMS, or paid WhatsApp API. You can use the software without
subscription charges. Existing internet/electricity costs still apply.

## What works

- Separate password-protected accounts for the elder, children, friends and helpers.
- Private groups with unguessable invitation codes and priority 1/2/3.
- Requests with date, time, meeting place, instructions and duration.
- Responses: Yes, No, or Other time with a proposed date/time and optional note.
- The first Yes reserves a request for one helper. Concurrent acceptances cannot
  assign two helpers. Requests are for one helper each.
- An alternative time changes nothing until the requester approves it; approval
  confirms that member at the new time.
- Responses and waiting members are shown in a summary; export the current view
  as a CSV report. All members of a group can see its tasks and response summary.
- Assigned tasks can be completed or reopened; the requester can cancel a task.
- Request/update messages in the app, plus optional Telegram delivery.
- Both requester and confirmed helper get 12-hour and 1-hour reminders if those
  reminder times were still in the future when the task was confirmed.
- Telegram connection uses a private, expiring one-time link, not a manually
  guessed phone number or chat ID.
- A phone calendar event with both alarms is available for confirmed tasks.
- Timezones are stored per account; task instants are stored in UTC.

## 1. Run locally on Windows — easiest first test

Install Python 3.11 or newer. Extract this ZIP into a normal folder, such as:

    C:\Users\unita\Documents\CareCircle

Double-click **start_windows.bat**. The first run installs the packages and opens
Streamlit in your browser. If Python is installed without the Windows `py`
launcher, use the manual commands below instead.

In Command Prompt (CMD), from the extracted folder:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py --server.address 0.0.0.0
```

No PowerShell activation or execution-policy change is required.
Open http://localhost:8501 on your laptop.

For a phone on the **same Wi-Fi**, use the Network URL printed by Streamlit, such
as http://192.168.1.20:8501. Allow Python through Windows Firewall on your private
network if prompted. The laptop must remain running. A local network URL does
not work for family outside your Wi-Fi. Use this local HTTP mode only for a
trusted test network; use cloud HTTPS for internet access.

Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.address 0.0.0.0
```

Local accounts and tasks are stored in care.db beside app.py. Back this file up
while the app and worker are stopped. Do not upload it to GitHub.

## 2. Try a complete example

1. Create the elder account. Open Care groups and create Family, priority 1.
2. Copy the group's invitation code.
3. In another browser/private window or phone, create a child/helper account.
4. Open Care groups → Join group and enter the invitation code.
5. In the elder account, create “Take me to hospital” for tomorrow afternoon.
6. In the helper account, press Refresh and respond Other time. Propose a later time.
7. In the elder account, open Responses and summary and approve that proposal.
8. Both accounts now see the confirmed helper and time.
9. Download the calendar event to test alarms on your own phone.
10. Create another request and test Yes and No with additional accounts.

Accounts are not supplied with default passwords. You choose your own.
This prototype has no password reset or email verification; remember your password.
Group priority sorts the groups. It does not delay messages or automatically
escalate unanswered tasks to a different group. A request targets one group;
all registered members in that group can respond.

## 3. Real phone notifications through Telegram

Sharing a URL through WhatsApp is free and supported. Automatic WhatsApp or SMS
reminders are not implemented. Telegram is the free notification channel here.
The phone must have Telegram, and its operating-system notification settings
must allow alerts. The browser does not need to stay open.

1. Open Telegram's verified @BotFather and send /newbot.
2. Choose a name and username; save the bot token privately.
3. Copy .streamlit/secrets.example.toml to .streamlit/secrets.toml.
4. Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USERNAME (username without @).
5. Keep DATABASE_URL empty for local testing. APP_URL can be empty locally.
6. Run **start_reminders_windows.bat** in a second window, or:

```bat
.venv\Scripts\python.exe worker.py
```

7. In each person's app account, open Phone reminders → Generate my connection
   link → Open Telegram and press Start. This link expires after 15 minutes.
8. Wait about 20 seconds, then press Refresh updates in the app. Linked should
   show Yes. Each person must connect their own account this way.
9. Create a new task. Confirm it. Check the confirmation message on the phone.

**Testing the 1-hour alarm without waiting a whole day:** create a task about
1 hour and 2 minutes from now and accept it promptly. The 1-hour reminder should
arrive about 2 minutes later, with up to 20 seconds normal worker polling delay.
For the 12-hour alarm, use a task 12 hours and 2 minutes from now.

Run only one reminder worker for this bot. No webhook should be configured for
this bot, because the worker uses Telegram getUpdates polling. A bot already
used by another program should not be reused here. The worker handles only
private chats for account linking.

The laptop running worker.py must stay awake, online and connected to the correct
database. Turning it off pauses reminders. When it restarts, missed reminders
for tasks that have not yet begun are delivered late and labelled accordingly.
Reminders for tasks already started are expired instead of sent. Tasks confirmed
inside a lead-time window do not receive retroactive alarms for that window;
they receive immediate confirmation instead.

Delivery failures are retried with backoff. Notification records use transactional
leases to prevent normal concurrent duplicates, but a crash after Telegram
accepts a message and before the database records success can cause a duplicate.
This prototype does not promise exactly-once delivery or guaranteed alarm timing.

Messages contain a generic update, task reference and time. Medical instructions,
names and meeting locations stay inside the logged-in app.

## 4. Share with family anywhere: Streamlit Community Cloud

**Do not deploy SQLite as the real shared database.** Community Cloud local files
are not guaranteed to survive restarts. Also, Community Cloud can hibernate, so
an in-app background thread would not provide dependable scheduled reminders.

Use this arrangement:

- Streamlit Community Cloud: phone/laptop web interface over HTTPS.
- Supabase Free PostgreSQL: shared persistent accounts, tasks and notification queue.
- Your existing laptop: worker.py connects to that same PostgreSQL database and
  sends Telegram messages even while Streamlit is sleeping.

Within current free-plan limits this avoids subscription fees, but is not an
always-on guarantee. Supabase Free currently has a 500 MB database limit and can
pause projects after a week of inactivity. Review current limits before setup;
remain on the Free plan and do not select paid add-ons.

### Deployment steps

1. Create a Supabase project on its Free plan. Save the database password privately.
2. Use Connect to copy the PostgreSQL connection string. Prefer the **session
   pooler** connection for compatibility with IPv4 networks. This is a database
   URL starting postgresql://, not the Supabase HTTPS project URL and not an anon key.
3. Replace the password placeholder in that URL. URL-encode special password
   characters if needed. Ensure the URL includes `sslmode=require` (append with
   `?` if there is no query string, otherwise `&`). Example with placeholders:

```text
postgresql://DATABASE_USER:ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

4. Create a GitHub repository and upload app.py, core.py, worker.py and requirements.txt
   to its root. README.md and tests can also be included. Upload .gitignore too.
   Do not upload secrets.toml, care.db or .venv.
5. Sign in to https://share.streamlit.io and create an app from that repository,
   selecting app.py as the entry point.
6. In the app's Secrets settings paste:

```toml
DATABASE_URL = "YOUR_PRIVATE_POSTGRESQL_CONNECTION_STRING"
TELEGRAM_BOT_TOKEN = "YOUR_PRIVATE_BOT_TOKEN"
TELEGRAM_BOT_USERNAME = "your_bot_username"
APP_URL = "https://your-app-name.streamlit.app"
```

7. Deploy. The app creates its tables automatically. Its database account must
   have permission to create tables and enable row-level security. Supabase's
   private Postgres connection is used only on the server; row-level security
   blocks anonymous access through the public Data API. This prototype implements
   account authentication itself, not Supabase Auth.
8. Put the **same four settings** into the laptop copy's .streamlit/secrets.toml.
   Run worker.py on that laptop. All devices and the worker now use the same data.
9. Create fresh accounts/groups on the cloud app. Switching from SQLite does not
   migrate your local test data automatically.
10. Copy the HTTPS Streamlit URL into WhatsApp, or use the in-app Share invitation
    through WhatsApp button. Every member registers and joins using the code.

If the web app sleeps, a family member may have to wake it when opening the link;
the separately running worker still queries the shared database. If the database
is unavailable, the worker retries but cannot deliver on time. The screen shows
whether the worker has checked in recently; that status is not proof that a
particular message reached a phone.

## 5. Phone calendar backup

Once a task is assigned, requester/helper can download its .ics file and import
it into a calendar app. It includes 12-hour and 1-hour display alarms, but some
calendar apps ignore imported alarms or ask for manual reminder settings. Test
this on the actual device. Import may be easier through Google Calendar on a
laptop than through a mobile browser. This is a one-time event export, not a live
calendar sync: remove old calendar events manually after cancellation/reopening.

## What was changed from Notes.docx

- Implemented directly in Python instead of n8n/Zapier.
- Replaced the API/LLM idea with ordinary coordination rules: this problem does
  not require generation, crawling, machine learning, or paid model calls.
- Added verified opt-in Telegram linking and a dedicated worker for reminders.
- Added a durable cloud database option rather than relying on hosted SQLite.
- Phone contacts are not read automatically. Invite people using your existing
  WhatsApp/contact list; they become app members after joining. A website cannot
  assume permission to read everyone's contacts.
- No automatic request assignment by AI: the first willing member accepts, or
  the requester explicitly approves an alternative proposed time.

## Files

- app.py — responsive Streamlit screens.
- core.py — accounts, groups, transactions, task rules, reminders and calendar files.
- worker.py — Telegram linking and queued message delivery.
- requirements.txt — install dependencies.
- .streamlit/secrets.example.toml — private configuration template.
- start_windows.bat — install/start the web app.
- start_reminders_windows.bat — start the separate phone reminder worker.
- tests/test_core.py — isolated functional tests, no real messages sent.

## Validation and scope

Run:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Eleven tests passed, including a two-account Streamlit screen workflow.
Tests cover access restrictions, password checks and lockout, simultaneous
acceptance, alternative approval, reminder scheduling, delivery retry and normal
deduplication, cancellation, reopening, short-notice tasks and calendar export.
Telegram transport is simulated in tests: a real bot and phone must be linked
before live delivery can be tested. PostgreSQL deployment requires your own
credentials and should be tested after configuration. This is a care coordination
prototype, with no emergency escalation, native push notifications, automatic
phone-contact access, or guaranteed availability. It has no account recovery,
member removal, role delegation, or scheduled automatic backups yet. Keep the
first pilot to a small trusted group; do not treat it as an emergency service.

## Official references checked 11 October 2026

- Streamlit hosting: https://docs.streamlit.io/deploy/streamlit-community-cloud
- Hibernation: https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app
- Local storage caveat: https://docs.streamlit.io/develop/concepts/connections/connecting-to-data
- Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- Supabase Free limits: https://supabase.com/pricing
- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram FAQ: https://core.telegram.org/bots/faq
