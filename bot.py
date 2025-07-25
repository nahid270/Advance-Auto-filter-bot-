# =====================================================================================
# ||                            GODFATHER MOVIE BOT                                  ||
# ||---------------------------------------------------------------------------------||
# || এই বটটি একটি স্বয়ংক্রিয় মুভি ম্যানেজমেন্ট এবং ডেলিভারি সিস্টেম।                    ||
# || এটি ওয়েব সার্ভারে ডিপ্লয় করার জন্য প্রস্তুত করা হয়েছে।                             ||
# =====================================================================================

import os
import re
import base64
import logging
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from bson.objectid import ObjectId

# --- নতুন ইম্পোর্টস: ওয়েব সার্ভারের জন্য ---
from flask import Flask
from threading import Thread

# --- ধাপ ১: পরিবেশ সেটআপ এবং কনফিগারেশন ---
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)

# --- ধাপ ২: বট এবং ডাটাবেসের জন্য প্রয়োজনীয় ভেরিয়েবল লোড ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    MONGO_URL = os.environ.get("MONGO_URL")
    AD_PAGE_URL = os.environ.get("AD_PAGE_URL")
    ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(',')]
    # --- নতুন ভেরিয়েবল: ওয়েব সার্ভারের জন্য পোর্ট ---
    PORT = int(os.environ.get("PORT", 8080))
except (ValueError, TypeError) as e:
    LOGGER.critical(f"Configuration error: One or more environment variables are missing or invalid. Error: {e}")
    exit()

# --- ধাপ ৩: টেলিগ্রাম ক্লায়েন্ট এবং MongoDB ডাটাবেস সংযোগ ---
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["MovieDB"]
movies = db["movies"]
users = db["users"]
channels = db["channels"]

# --- ধাপ ৪: ওয়েব সার্ভার ইন্টিগ্রেশন (Flask) ---
# একটি সাধারণ Flask অ্যাপ তৈরি করা হচ্ছে যা সার্ভারকে জানাবে বটটি সচল আছে।
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    """এটি একটি হেলথ চেক এন্ডপয়েন্ট, যা 200 OK স্ট্যাটাস রিটার্ন করে।"""
    return "Bot is alive and kicking!", 200

def run_web_server():
    """Flask ওয়েব সার্ভারটি চালানোর জন্য একটি ফাংশন।"""
    web_app.run(host='0.0.0.0', port=PORT)

# ========= 📄 হেল্পার ফাংশন (পূর্বের মতোই) ========= #
def is_admin(user_id):
    return user_id in ADMIN_IDS

# ========= 📢 চ্যানেল থেকে মুভি সেভ করা (পূর্বের মতোই) ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
def save_movie(client, message):
    channel_id = message.chat.id
    if not channels.find_one({"_id": channel_id}):
        return

    text_to_parse = message.caption or ""
    title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", text_to_parse)
    if not title_match:
        LOGGER.warning(f"Could not parse title from message {message.id} in channel {channel_id}")
        return

    title = re.sub(r'[\.\_]', ' ', title_match.group(1).strip())
    year = title_match.group(2)
    
    languages = ["Hindi", "Bangla", "English", "Tamil", "Telugu", "Malayalam", "Kannada"]
    language = "Unknown"
    for lang in languages:
        if lang.lower() in text_to_parse.lower():
            language = lang
            break

    file_id = message.video.file_id if message.video else message.document.file_id

    data = {
        "title": title,
        "year": year,
        "language": language,
        "file_id": file_id,
        "chat_id": message.chat.id,
        "msg_id": message.id,
    }

    if not movies.find_one({"title": title, "year": year}):
        movies.insert_one(data)
        LOGGER.info(f"✅ Movie Saved: {title} ({year}) from channel {channel_id}")

# ========= 🔎 ইউজারদের জন্য সার্চ ও ভেরিফিকেশন (পূর্বের মতোই) ========= #
@app.on_message(filters.private & filters.text & ~filters.command("start"))
def search_movie(client, message):
    query = message.text.strip()
    result = movies.find_one({"title": {"$regex": query, "$options": "i"}})
    
    if result:
        movie_id = str(result['_id'])
        user_id = message.from_user.id
        encoded_data = base64.urlsafe_b64encode(f'{movie_id}-{user_id}'.encode()).decode()
        verification_url = f"{AD_PAGE_URL}?data={encoded_data}"
        
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Please Verify to Watch", url=verification_url)]])
        message.reply_text(
            f"🎬 **{result['title']} ({result['year']})**\n"
            f"🌐 Language: {result['language']}\n\n"
            "➡️ To get the movie, please click the button below and verify.",
            reply_markup=btn,
            disable_web_page_preview=True
        )
    else:
        message.reply_text("❌ **Movie Not Found!**\n\nPlease check the spelling or try another name.")

# ========= 🎬 ভেরিফিকেশন শেষে ফাইল পাঠানো (পূর্বের মতোই) ========= #
@app.on_message(filters.private & filters.command("start"))
def start_handler(client, message):
    user_id = message.from_user.id
    if not users.find_one({"_id": user_id}):
        users.insert_one({"_id": user_id, "name": message.from_user.first_name})
        LOGGER.info(f"New user saved: {user_id}")

    if len(message.command) > 1:
        try:
            payload = message.command[1]
            decoded_data = base64.urlsafe_b64decode(payload).decode()
            movie_id_str, verified_user_id_str = decoded_data.split('-')

            if user_id != int(verified_user_id_str):
                return message.reply_text("😡 **Verification Failed!** This link was not generated for you.")

            movie = movies.find_one({"_id": ObjectId(movie_id_str)})
            if movie:
                client.copy_message(
                    chat_id=user_id,
                    from_chat_id=movie['chat_id'],
                    message_id=movie['msg_id'],
                    caption=f"✅ **Verification Successful!**\n\n🎬 **{movie['title']} ({movie['year']})**\n\nThank you for using our bot!"
                )
            else:
                message.reply_text("❌ Sorry, the movie could not be found. It might have been removed.")
        except Exception as e:
            LOGGER.error(f"Deep link error for user {user_id}: {e}")
            message.reply_text("🤔 Invalid or expired verification link.")
    else:
        message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\n\nI am a movie search bot. Just send me the name of the movie you want to find.")


# ========= 🛠️ অ্যাডমিন কমান্ডস (পূর্বের মতোই) ========= #
# ... (এখানে আপনার অ্যাডমিন কমান্ডের কোডগুলো থাকবে, কোনো পরিবর্তন ছাড়াই)
@app.on_message(filters.command("stats") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
def stats_command(_, message):
    total_users = users.count_documents({})
    total_movies = movies.count_documents({})
    total_channels = channels.count_documents({})
    message.reply_text(
        f"📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"🎬 Total Movies: `{total_movies}`\n"
        f"📢 Authorized Channels: `{total_channels}`"
    )

@app.on_message(filters.command("addchannel") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
def add_channel_command(_, message):
    try:
        channel_id = int(message.text.split()[1])
        if channel_id > -1000000000000:
            return message.reply("❌ Invalid Channel ID. It must be a 13-digit negative number (e.g., -100xxxxxxxx).")
        
        if channels.find_one({"_id": channel_id}):
            message.reply("⚠️ This channel is already authorized.")
        else:
            channels.insert_one({"_id": channel_id})
            message.reply(f"✅ Channel `{channel_id}` has been added.")
    except (IndexError, ValueError):
        message.reply("❌ **Usage:** `/addchannel <channel_id>`")

@app.on_message(filters.command("delchannel") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
def del_channel_command(_, message):
    try:
        channel_id = int(message.text.split()[1])
        result = channels.delete_one({"_id": channel_id})
        if result.deleted_count:
            message.reply(f"✅ Channel `{channel_id}` has been removed.")
        else:
            message.reply("⚠️ Channel not found in the authorized list.")
    except (IndexError, ValueError):
        message.reply("❌ **Usage:** `/delchannel <channel_id>`")

@app.on_message(filters.command("channels") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
def list_channels_command(_, message):
    all_channels = list(channels.find({}))
    if not all_channels:
        return message.reply("No channels have been authorized yet.")
    
    text = "📄 **Authorized Channels:**\n\n"
    for channel in all_channels:
        text += f"• `{channel['_id']}`\n"
    message.reply(text)

# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা ========= #
if __name__ == "__main__":
    LOGGER.info("Starting web server for health checks...")
    # ওয়েব সার্ভারটিকে একটি ব্যাকগ্রাউন্ড থ্রেডে চালানো হচ্ছে
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    LOGGER.info("The Don is waking up... Bot is starting...")
    # Pyrogram ক্লায়েন্ট মূল থ্রেডে চলবে
    app.run()
    LOGGER.info("The Don is resting... Bot has stopped.")
