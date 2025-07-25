# =====================================================================================
# ||                            GODFATHER MOVIE BOT (Final Corrected Version)        ||
# ||---------------------------------------------------------------------------------||
# || TypeError এবং TgCrypto সমস্যার সমাধানের পর এটি চূড়ান্ত কোড।                       ||
# =====================================================================================

import os
import re
import base64
import logging
from dotenv import load_dotenv
from threading import Thread

# --- ওয়েব সার্ভার ও বট লাইব্রেরি ---
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from bson.objectid import ObjectId

# --- ধাপ ১: পরিবেশ সেটআপ এবং কনফিগারেশন ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)

# --- ধাপ ২: কনফিগারেশন ভেরিয়েবল লোড ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    MONGO_URL = os.environ.get("MONGO_URL")
    AD_PAGE_URL = os.environ.get("AD_PAGE_URL")
    ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(',')]
    PORT = int(os.environ.get("PORT", 8080))
except (ValueError, TypeError) as e:
    LOGGER.critical(f"Configuration error: One or more environment variables are missing or invalid. Error: {e}")
    exit()

# --- ধাপ ৩: ক্লায়েন্ট, ডাটাবেস এবং ওয়েব অ্যাপ ইনিশিয়ালাইজেশন ---
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["MovieDB"]
movies = db["movies"]
users = db["users"]
channels = db["channels"]

web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Bot is alive!", 200

# ========= 📄 হেল্পার ফাংশন ========= #
def is_admin(user_id):
    return user_id in ADMIN_IDS

# ========= 📢 চ্যানেল থেকে স্বয়ংক্রিয় মুভি সেভ ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
def save_movie(client, message):
    channel_id = message.chat.id
    if not channels.find_one({"_id": channel_id}): return
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
    data = {"title": title, "year": year, "language": language, "file_id": file_id, "chat_id": message.chat.id, "msg_id": message.id}
    if not movies.find_one({"title": title, "year": year}):
        movies.insert_one(data)
        LOGGER.info(f"✅ Movie Saved: {title} ({year}) from channel {channel_id}")

# ========= 🎬 স্টার্ট কমান্ড এবং ভেরিফিকেশন হ্যান্ডলার (সর্বপ্রথম প্রায়োরিটি) ========= #
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
                client.copy_message(chat_id=user_id, from_chat_id=movie['chat_id'], message_id=movie['msg_id'], caption=f"✅ **Verification Successful!**\n\n🎬 **{movie['title']} ({movie['year']})**\n\nThank you for using our bot!")
            else:
                message.reply_text("❌ Sorry, the movie could not be found. It might have been removed.")
        except Exception as e:
            LOGGER.error(f"Deep link error for user {user_id}: {e}")
            message.reply_text("🤔 Invalid or expired verification link.")
    else:
        message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\n\nI am a movie search bot. Just send me the name of the movie you want to find.")

# ========= 🛠️ অ্যাডমিন কমান্ডস (উচ্চ প্রায়োরিটি) ========= #
@app.on_message(filters.command("stats") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
def stats_command(_, message):
    total_users = users.count_documents({})
    total_movies = movies.count_documents({})
    total_channels = channels.count_documents({})
    message.reply_text(f"📊 **Bot Statistics**\n\n👥 Total Users: `{total_users}`\n🎬 Total Movies: `{total_movies}`\n📢 Authorized Channels: `{total_channels}`")

@app.on_message(filters.command("addchannel") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
def add_channel_command(_, message):
    try:
        channel_id = int(message.text.split(None, 1)[1])
        if channel_id > -1000000000000:
            return message.reply("❌ Invalid Channel ID. It must be a 13-digit negative number (e.g., -100xxxxxxxxxx).")
        if channels.find_one({"_id": channel_id}):
            message.reply("⚠️ This channel is already authorized.")
        else:
            channels.insert_one({"_id": channel_id})
            message.reply(f"✅ Channel `{channel_id}` has been added.")
    except (IndexError, ValueError):
        message.reply("❌ **Usage:** `/addchannel <channel_id>`")

# ... (অন্যান্য অ্যাডমিন কমান্ডগুলো এখানে থাকবে) ...
@app.on_message(filters.command("delchannel") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
def del_channel_command(_, message):
    try:
        channel_id = int(message.text.split(None, 1)[1])
        result = channels.delete_one({"_id": channel_id})
        if result.deleted_count: message.reply(f"✅ Channel `{channel_id}` has been removed.")
        else: message.reply("⚠️ Channel not found in the authorized list.")
    except (IndexError, ValueError): message.reply("❌ **Usage:** `/delchannel <channel_id>`")

@app.on_message(filters.command("channels") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
def list_channels_command(_, message):
    all_channels = list(channels.find({}))
    if not all_channels: return message.reply("No channels have been authorized yet.")
    text = "📄 **Authorized Channels:**\n\n"
    for channel in all_channels:
        text += f"• `{channel['_id']}`\n"
    message.reply(text)


# ========= 🔎 মুভি সার্চ (সর্বশেষ প্রায়োরিটি) ========= #
# *** এখানে ~filters.command বাদ দেওয়া হয়েছে, কারণ এটি অপ্রয়োজনীয় এবং ত্রুটির কারণ ছিল ***
@app.on_message(filters.private & filters.text)
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
            f"🎬 **{result['title']} ({result['year']})**\n🌐 Language: {result['language']}\n\n➡️ To get the movie, please click the button below and verify.",
            reply_markup=btn, disable_web_page_preview=True)
    else:
        message.reply_text("❌ **Movie Not Found!**\n\nPlease check the spelling or try another name.")

# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা ========= #
def run_web_server():
    web_app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    LOGGER.info("Starting web server for health checks on a background thread...")
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    LOGGER.info("The Don is waking up... Starting Pyrogram client on the main thread.")
    app.run()
    LOGGER.info("The Don is resting... Bot has stopped.")
