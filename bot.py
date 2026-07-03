"""
Simple AI Calendar Bot for Telegram
Works on Railway - no database needed!
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import openai

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get API keys from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Simple storage (events stay in memory while bot runs)
events_db = {}  # user_id -> list of events
user_profiles = {}


class Event:
    """Simple event class"""
    def __init__(self, title, start_time, end_time, location="", attendees=None):
        self.id = f"evt_{int(start_time.timestamp())}"
        self.title = title
        self.start_time = start_time
        self.end_time = end_time
        self.location = location
        self.attendees = attendees or []
        self.reminders_sent = set()  # Track which reminders were sent


def get_user_events(user_id: str) -> List[Event]:
    """Get all events for a user"""
    return events_db.get(user_id, [])


def add_event(user_id: str, event: Event):
    """Add event to user's calendar"""
    if user_id not in events_db:
        events_db[user_id] = []
    events_db[user_id].append(event)
    # Sort by start time
    events_db[user_id].sort(key=lambda e: e.start_time)


def find_events_by_title(user_id: str, title_query: str) -> List[Event]:
    """Find events matching a title search"""
    events = get_user_events(user_id)
    matches = []
    query_lower = title_query.lower()
    for event in events:
        if query_lower in event.title.lower():
            matches.append(event)
    return matches


# ============================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    user_id = str(user.id)
    
    # Save user profile
    user_profiles[user_id] = {
        "name": user.first_name or "User",
        "id": user_id
    }
    
    welcome = (
        f"👋 Hello {user.first_name}!\n\n"
        "I'm your AI Calendar Assistant.\n\n"
        "Just chat naturally:\n"
        "• \"Meeting tomorrow at 2pm with Sarah\"\n"
        "• \"What's on my schedule today?\"\n"
        "• \"Cancel my dentist appointment\"\n\n"
        "Try it now!"
    )
    await update.message.reply_text(welcome)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "📖 How to use me:\n\n"
        "Schedule:\n"
        "• \"Team meeting tomorrow at 3pm\"\n"
        "• \"Lunch Friday at 12:30 at The Grill\"\n"
        "• \"Urgent: Client call Monday 10am for 30 min\"\n\n"
        "View:\n"
        "• \"What's on today?\"\n"
        "• \"Show my schedule this week\"\n\n"
        "Cancel:\n"
        "• \"Cancel my dentist appointment\"\n\n"
        "Commands:\n"
        "/start - Welcome\n"
        "/help - This help\n"
        "/today - Today's events"
    )
    await update.message.reply_text(help_text)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's events"""
    user_id = str(update.effective_user.id)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    user_events = get_user_events(user_id)
    today_events = [
        e for e in user_events 
        if today_start <= e.start_time < today_end
    ]
    
    if not today_events:
        await update.message.reply_text("📭 No events today. You're free! 🎉")
        return
    
    msg = "📅 Your Schedule - Today\n━━━━━━━━━━━━━━\n\n"
    for event in today_events:
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


# ============================================================
# OPENAI FUNCTION CALLING FOR SMART NLP
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages using OpenAI"""
    user_id = str(update.effective_user.id)
    message = update.message.text
    
    # Show typing indicator
    await update.message.chat.send_action(action="typing")
    
    try:
        # Use OpenAI to understand the message
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"""You are a calendar assistant bot. Today's date is {datetime.now().strftime('%Y-%m-%d')}.
                    
                    Analyze the user's message and respond with ONE of these formats:
                    
                    1. SCHEDULE|title|YYYY-MM-DD|HH:MM|duration_minutes|location|attendee1,attendee2
                       Example: SCHEDULE|Team Meeting|2026-07-05|14:00|60|Conference Room|Sarah,Mike
                    
                    2. QUERY|period
                       period can be: today, tomorrow, this_week, next_week
                       Example: QUERY|today
                    
                    3. CANCEL|event_title_keyword
                       Example: CANCEL|dentist
                    
                    4. CHAT|your_friendly_response
                       Use for greetings, thanks, or unclear requests
                       Example: CHAT|Hello! How can I help you today?
                    
                    Rules:
                    - If user says "tomorrow", use date: {(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')}
                    - If user says a day name (Monday, Tuesday, etc.), calculate the next occurrence
                    - Convert all times to 24-hour format HH:MM
                    - Default duration is 60 minutes if not specified
                    - Extract location after words like "at", "in"
                    - Extract attendees after words like "with", "and"
                    - If message is unclear, use CHAT format to ask for clarification"""
                },
                {"role": "user", "content": message}
            ],
            temperature=0.1
        )
        
        ai_response = response.choices[0].message.content.strip()
        logger.info(f"OpenAI response: {ai_response}")
        
        # Parse the response
        if ai_response.startswith("SCHEDULE|"):
            await handle_schedule(user_id, ai_response, update)
        elif ai_response.startswith("QUERY|"):
            await handle_query(user_id, ai_response, update)
        elif ai_response.startswith("CANCEL|"):
            await handle_cancel(user_id, ai_response, update)
        else:
            # CHAT or fallback
            chat_response = ai_response.split("|", 1)[1] if "|" in ai_response else ai_response
            await update.message.reply_text(chat_response)
            
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await update.message.reply_text(
            "🤔 I'm having trouble understanding. Try something like:\n"
            "\"Schedule a meeting tomorrow at 2pm with Sarah\""
        )


async def handle_schedule(user_id: str, ai_response: str, update: Update):
    """Create an event from OpenAI parsed data"""
    parts = ai_response.split("|")
    # parts: [SCHEDULE, title, date, time, duration, location, attendees]
    
    title = parts[1] if len(parts) > 1 else "Untitled Event"
    date_str = parts[2] if len(parts) > 2 else datetime.now().strftime("%Y-%m-%d")
    time_str = parts[3] if len(parts) > 3 else "09:00"
    duration = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 60
    location = parts[5] if len(parts) > 5 else ""
    attendees = [a.strip() for a in parts[6].split(",") if a.strip()] if len(parts) > 6 else []
    
    # Parse datetime
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        hour, minute = map(int, time_str.split(":"))
        start_time = datetime.combine(date, datetime.min.time().replace(hour=hour, minute=minute))
        end_time = start_time + timedelta(minutes=duration)
    except ValueError:
        await update.message.reply_text("❌ I couldn't understand the date/time. Please try again.")
        return
    
    # Check for conflicts
    user_events = get_user_events(user_id)
    conflicts = []
    for existing in user_events:
        if existing.start_time < end_time and existing.end_time > start_time:
            conflicts.append(existing)
    
    # Create event
    event = Event(title, start_time, end_time, location, attendees)
    add_event(user_id, event)
    
    # Build response
    reply = f"✅ Event Scheduled!\n\n"
    reply += f"📌 {title}\n"
    reply += f"📅 {start_time.strftime('%A, %B %d at %I:%M %p')}\n"
    reply += f"⏱️ {duration} minutes\n"
    if location:
        reply += f"📍 {location}\n"
    if attendees:
        reply += f"👥 {', '.join(attendees)}\n"
    
    if conflicts:
        reply += f"\n⚠️ Conflict Alert: You have {len(conflicts)} overlapping event(s):\n"
        for c in conflicts:
            reply += f"   • {c.title} ({c.start_time.strftime('%I:%M %p')})\n"
    
    reply += "\n🔔 I'll remind you before the event!"
    await update.message.reply_text(reply)


async def handle_query(user_id: str, ai_response: str, update: Update):
    """Show schedule for requested period"""
    parts = ai_response.split("|")
    period = parts[1] if len(parts) > 1 else "today"
    
    now = datetime.now()
    
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = "Today"
    elif period == "tomorrow":
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = "Tomorrow"
    elif period == "this_week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        label = "This Week"
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = "Today"
    
    user_events = get_user_events(user_id)
    period_events = [e for e in user_events if start <= e.start_time < end]
    
    if not period_events:
        await update.message.reply_text(f"📭 No events scheduled for {label.lower()}. You're free! 🎉")
        return
    
    msg = f"📅 Your Schedule - {label}\n━━━━━━━━━━━━━━\n\n"
    for event in period_events:
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


async def handle_cancel(user_id: str, ai_response: str, update: Update):
    """Cancel an event"""
    parts = ai_response.split("|")
    keyword = parts[1] if len(parts) > 1 else ""
    
    if not keyword:
        await update.message.reply_text("❓ Which event would you like to cancel?")
        return
    
    matches = find_events_by_title(user_id, keyword)
    
    if not matches:
        await update.message.reply_text(f"❌ I couldn't find any event matching '{keyword}'.")
        return
    
    if len(matches) == 1:
        event = matches[0]
        # Remove from database
        events_db[user_id] = [e for e in events_db[user_id] if e.id != event.id]
        await update.message.reply_text(
            f"✅ Cancelled!\n\n"
            f"🗑️ {event.title} on {event.start_time.strftime('%A, %B %d at %I:%M %p')} "
            f"has been removed from your calendar."
        )
    else:
        msg = f"🔍 I found {len(matches)} matching events. Which one?\n\n"
        for i, event in enumerate(matches, 1):
            msg += f"{i}. {event.title} - {event.start_time.strftime('%a %b %d %I:%M %p')}\n"
        msg += "\nReply with the number."
        await update.message.reply_text(msg)


# ============================================================
# REMINDER SYSTEM
# ============================================================

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Check and send reminders every minute"""
    now = datetime.now()
    
    for user_id, events in events_db.items():
        for event in events:
            # Check each reminder time (24h, 2h, 15min before)
            for reminder_min in [1440, 120, 15]:
                if reminder_min in event.reminders_sent:
                    continue  # Already sent
                
                reminder_time = event.start_time - timedelta(minutes=reminder_min)
                time_diff = (reminder_time - now).total_seconds() / 60
                
                # If reminder time is within the last minute
                if 0 <= time_diff <= 1:
                    try:
                        # Format reminder message
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
                        event.reminders_sent.add(reminder_min)
                        logger.info(f"Sent reminder to {user_id} for {event.title}")
                        
                    except Exception as e:
                        logger.error(f"Failed to send reminder: {e}")


# ============================================================
# MAIN
# ============================================================

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN not set!")
        print("Set it as an environment variable.")
        return
    
    if not OPENAI_API_KEY:
        print("❌ ERROR: OPENAI_API_KEY not set!")
        return
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    
    # Add message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Schedule reminder checks (every 60 seconds)
    application.job_queue.run_repeating(check_reminders, interval=60, first=10)
    
    print("🤖 Bot is starting...")
    print("✅ Ready to receive messages!")
    
    # Run the bot
    application.run_polling()


if __name__ == "__main__":
    main()
                        
