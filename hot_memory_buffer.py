import json
import os
from datetime import datetime, timedelta

LOG_PATH = r'F:\Galactic AI\logs\chat_history.jsonl'
BUFFER_PATH = r'F:\Galactic AI\logs\conversations\hot_buffer.json'
WINDOW_MINUTES = 30

# NOTE (2026-02-24): Disabled by default.
# Galactic AI now uses the ConversationArchiverSkill hot buffer at:
#   logs/conversations/hot_buffer.json
# Keeping this module importable avoids touching gateway_v2.py (protected),
# but prevents duplicate hot_buffer.json writes to logs/.
ENABLE_LEGACY_HOT_BUFFER = False

def update_hot_buffer():
    if not ENABLE_LEGACY_HOT_BUFFER:
        return

    """Reads the chat history and keeps only the last 30 minutes of messages."""
    if not os.path.exists(LOG_PATH):
        return

    hot_messages = []
    cutoff_time = datetime.now() - timedelta(minutes=WINDOW_MINUTES)

    try:
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    msg = json.loads(line)
                    # Assuming each msg has a 'timestamp' or we use the log order
                    # If no timestamp in JSON, we'll need to infer or add it in gateway_v2
                    # For now, let's assume we filter the last N lines as a proxy if timestamp is missing,
                    # but the goal is true time-based filtering.
                    msg_time_str = msg.get('timestamp')
                    if msg_time_str:
                        msg_time = datetime.fromisoformat(msg_time_str)
                        if msg_time > cutoff_time:
                            hot_messages.append(msg)
                    else:
                        # Fallback: keep last 20 messages if no timestamp
                        hot_messages.append(msg)
                except:
                    continue

        # Keep only the tail if it's too long
        if not any(m.get('timestamp') for m in hot_messages):
            hot_messages = hot_messages[-20:]

        with open(BUFFER_PATH, 'w', encoding='utf-8') as f:
            json.dump({
                "last_updated": datetime.now().isoformat(),
                "window_minutes": WINDOW_MINUTES,
                "messages": hot_messages
            }, f, indent=2)
            
        print(f"Hot buffer updated: {len(hot_messages)} messages saved.")
    except Exception as e:
        print(f"Error updating buffer: {e}")

if __name__ == '__main__':
    update_hot_buffer()