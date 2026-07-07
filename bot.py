"""
Simple Calendar Bot - Works without OpenAI
"""

import os
import re
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from datetime import datetime, timedelta
import pytz  # You'll need to add this to requirements.txt

# Set IST timezone
IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.utc

def get_ist_time():
    """Get current time in IST"""
    return datetime.now(IST)

def convert_to_ist(utc_time):
    """Convert UTC time to IST"""
    if utc_time.tzinfo is None:
        utc_time = pytz.utc.localize(utc_time)
    return utc_time.astimezone(IST)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Simple storage
events_db = {}

class Event:
    def __init__(self, title, start_time, end_time, location="", attendees=None):
        self.id = f"evt_{int(start_time.timestamp())}"
        self.title = title
        self.start_time = start_time
        self.end_time = end_time
        self.location = location
        self.attendees = attendees or []

def get_events(user_id):
    return events_db.get(user_id, [])

def add_event(user_id, event):
    if user_id not in events_db:
        events_db[user_id] = []
    events_db[user_id].append(event)
    events_db[user_id].sort(key=lambda e: e.start_time)

def parse_message(message):
    """Simple NLP without OpenAI"""
    msg_lower = message.lower()
    
    # Check for schedule intent
    schedule_words = ["schedule", "book", "add", "create", "plan", "meeting", "appointment"]
    if any(word in msg_lower for word in schedule_words):
        # Extract title
        title = "Event"
        if "meeting" in msg_lower:
            title = "Meeting"
        elif "call" in msg_lower:
            title = "Call"
        elif "lunch" in msg_lower:
            title = "Lunch"
        elif "dinner" in msg_lower:
            title = "Dinner"
        
        # Extract date
        date = datetime.now().date()
        if "tomorrow" in msg_lower:
            date = (datetime.now() + timedelta(days=1)).date()
        
        # Extract time
        time_match = re.search(r"(\d{1,2}):(\d{2})", msg_lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
        else:
            hour, minute = 9, 0
        
        # Extract duration
        duration = 60
        duration_match = re.search(r"(\d+)\s*min", msg_lower)
        if duration_match:
            duration = int(duration_match.group(1))
        elif "hour" in msg_lower:
            hour_match = re.search(r"(\d+)\s*hour", msg_lower)
            if hour_match:
                duration = int(hour_match.group(1)) * 60
        
        # Extract location
        location = ""
        loc_match = re.search(r"(?:at|in)\s+([A-Za-z\s]+?)(?:\s+(?:at|with|for|on)\s|$)", message)
        if loc_match:
            location = loc_match.group(1).strip()
        
        # Extract attendees
        attendees = re.findall(r"(?:with|and)\s+([A-Z][a-z]+)", message)
        
        return {
            "intent": "schedule",
            "title": title,
            "date": date,
            "time": (hour, minute),
            "duration": duration,
            "location": location,
            "attendees": attendees
        }
    
    # Check for query
    query_words = ["what", "schedule", "today", "tomorrow", "events"]
    if any(word in msg_lower for word in query_words):
        return {"intent": "query"}
    
    # Check for cancel
    cancel_words = ["cancel", "delete", "remove"]
    if any(word in msg_lower for word in cancel_words):
        return {"intent": "cancel"}
    
    return {"intent": "unknown"}

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome = (
        f"👋 Hello {user.first_name}!\n\n"
        "I'm your Calendar Assistant.\n\n"
        "Try:\n"
        "• \"Meeting tomorrow at 2pm with Sarah\"\n"
        "• \"What's on today?\"\n"
        "• \"Cancel my meeting\"\n\n"
        "Let's get started!"
    )
    await update.message.reply_text(welcome)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 How to use me:\n\n"
        "Schedule: \"Team meeting tomorrow at 3pm\"\n"
        "View: \"What's on today?\"\n"
        "Cancel: \"Cancel my meeting\"\n\n"
        "Commands:\n"
        "/start - Welcome\n"
        "/help - This help\n"
        "/today - Today's events"
    )
    await update.message.reply_text(help_text)

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    today_start = datetime.now().replace(hour=0, minute=0, second=0)
    today_end = today_start + timedelta(days=1)
    
    user_events = [e for e in get_events(user_id) 
                   if today_start <= e.start_time < today_end]
    
    if not user_events:
        await update.message.reply_text("📭 No events today. You're free! 🎉")
        return
    
    msg = "📅 Your Schedule - Today\n━━━━━━━━━━━━━━\n\n"
    for event in user_events:
        time_str = event.start_time.strftime("%I:%M %p")
        duration = (event.end_time - event.start_time).seconds // 60
        msg += f"⏰ {time_str} - {event.title}\n"
        msg += f"   ⏱️ {duration} min"
        if event.location:
            msg += f" | 📍 {event.location}"
        if event.attendees:
            msg += f" | 👥 {', '.join(event.attendees)}"
        msg += "\n\n"
    
    await update.message.reply_text(msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    message = update.message.text
    
    await update.message.chat.send_action(action="typing")
    
    parsed = parse_message(message)
    intent = parsed["intent"]
    
    if intent == "schedule":
        date = parsed["date"]
        hour, minute = parsed["time"]
        start_time = datetime.combine(date, datetime.min.time().replace(hour=hour, minute=minute))
        end_time = start_time + timedelta(minutes=parsed["duration"])
        
        event = Event(
            parsed["title"],
            start_time,
            end_time,
            parsed["location"],
            parsed["attendees"]
        )
        add_event(user_id, event)
        
        reply = f"✅ Event Scheduled!\n\n"
        reply += f"📌 {event.title}\n"
        reply += f"📅 {start_time.strftime('%A, %B %d at %I:%M %p')}\n"
        reply += f"⏱️ {parsed['duration']} minutes\n"
        if event.location:
            reply += f"📍 {event.location}\n"
        if event.attendees:
            reply += f"👥 {', '.join(event.attendees)}\n"
        reply += "\n🔔 I'll remind you before the event!"
        
        await update.message.reply_text(reply)
    
    elif intent == "query":
        await today_command(update, context)
    
    elif intent == "cancel":
        await update.message.reply_text("❓ Which event would you like to cancel? Tell me the title.")
    
    else:
        await update.message.reply_text(
            "🤔 I'm not sure what you mean. Try:\n"
            "\"Schedule a meeting tomorrow at 2pm\"\n"
            "\"What's on today?\""
        )

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    for user_id, events in events_db.items():
        for event in events:
            for reminder_min in [1440, 120, 15]:
                reminder_time = event.start_time - timedelta(minutes=reminder_min)
                time_diff = (reminder_time - now).total_seconds() / 60
                
                if 0 <= time_diff <= 1:
                    try:
                        if reminder_min >= 1440:
                            when = "tomorrow"
                        elif reminder_min >= 60:
                            when = f"in {reminder_min // 60} hours"
                        else:
                            when = f"in {reminder_min} minutes"
                        
                        msg = f"⏰ Reminder: {event.title} {when}!\n"
                        msg += f"📅 {event.start_time.strftime('%A, %B %d at %I:%M %p')}"
                        if event.location:
                            msg += f"\n📍 {event.location}"
                        
                        await context.bot.send_message(chat_id=user_id, text=msg)
                    except Exception as e:
                        print(f"Reminder error: {e}")

def main():
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN not set!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.job_queue.run_repeating(check_reminders, interval=60, first=10)
    
    print("🤖 Bot started!")
    application.run_polling()

if __name__ == "__main__":
    main()
                
