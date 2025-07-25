# =====================================================================================
# ||        GODFATHER MOVIE BOT (v2.5 - Hardcoded Channel Version)                   ||
# ||---------------------------------------------------------------------------------||
# ||     এই সংস্করণে ফাইল চ্যানেল আইডি সরাসরি কোডে সেট করা হয়েছে।                     ||
# =====================================================================================

import os
import re
import base64
import logging
import asyncio
from dotenv import load_dotenv
from threading import Thread
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId

# --- পরিবেশ সেটআপ ও কনফিগারেশন ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)

# << --- গুরুত্বপূর্ণ পরিবর্তন: আপনার ফাইল চ্যানেলের আইডি এখানে দিন --- >>
# আপনার চ্যানেল আইডি অবশ্যই -100 দিয়ে শুরু হতে হবে। যেমন: -1001234567890
FILE_CHANNEL_ID = -1002744890741  # <====== আপনার ফাইল চ্যানেলের আইডি এখানে দিন

if FILE_CHANNEL_ID == -1002744890741:
    LOGGER.warning("Please update the FILE_CHANNEL_ID in the code with your actual channel ID.")

try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    MONGO_URL = os.environ.get("MONGO_URL")
    AD_PAGE_URL = os.environ.get("AD_PAGE_URL")
    ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(',') if id.strip()]
    PORT = int(os.environ.get("PORT", 8080))
    DELETE_DELAY = 15 * 60
except (ValueError, TypeError) as e:
    LOGGER.critical(f"Configuration error in environment variables: {e}")
    exit()

# --- ক্লায়েন্ট, ডাটাবেস ও ওয়েব অ্যাপ ---
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["MovieDB"]
movie_info_db = db["movie_info"]
files_db = db["files"]
users_db = db["users"]
# 'channels_db' এর আর প্রয়োজন নেই

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Bot is alive and running!"

# ========= 📄 হেল্পার ফাংশন ও ফিল্টার ========= #
def is_admin(_, __, message):
    return message.from_user and message.from_user.id in ADMIN_IDS

admin_filter = filters.create(is_admin)

# ... (অন্যান্য হেল্পার ফাংশন অপরিবর্তিত)
async def delete_messages_after_delay(messages, delay):
    await asyncio.sleep(delay)
    for msg in messages:
        try: await msg.delete()
        except Exception: pass

# ========= 📢 চ্যানেল থেকে মুভি সেভ (সরলীকৃত) ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
async def save_movie_quality(client, message):
    # << --- পরিবর্তন: এখন ডাটাবেস চেক না করে সরাসরি আইডি'র সাথে মেলানো হচ্ছে --- >>
    if message.chat.id != FILE_CHANNEL_ID:
        return

    caption = message.caption or ""
    title_match = re.search(r"(.+?)\s*\((\d{4})\)", caption, re.IGNORECASE)
    
    if not title_match:
        LOGGER.warning(f"Could not parse 'Title (YYYY)' from msg {message.id} in channel {message.chat.id}. Caption: '{caption}'")
        return
        
    title, year = re.sub(r'[\.\_]', ' ', title_match.group(1).strip()), title_match.group(2)
    search_title = f"{title.lower()} {year}"
    quality = next((q for q in ["480p", "720p", "1080p", "2160p", "4k"] if q in caption.lower()), "Unknown")
    language = next((lang for lang in ["hindi", "bangla", "english", "tamil", "telugu", "malayalam", "kannada"] if lang in caption.lower()), "Unknown")
    
    movie_doc = await movie_info_db.find_one_and_update(
        {"search_title": search_title},
        {"$setOnInsert": {"title": title, "year": year, "search_title": search_title}},
        upsert=True, return_document=True
    )
    
    await files_db.update_one(
        {"movie_id": movie_doc['_id'], "quality": quality, "language": language},
        {"$set": {
            "file_id": message.video.file_id if message.video else message.document.file_id,
            "chat_id": message.chat.id,
            "msg_id": message.id
        }},
        upsert=True
    )
    LOGGER.info(f"✅ Indexed: {title} ({year}) [{quality} - {language}] from hardcoded channel {message.chat.id}")

# ========= 💻 অ্যাডমিন কমান্ড হ্যান্ডলার (সরলীকৃত) ========= #
@app.on_message(filters.command("stats") & admin_filter)
async def stats_command(client, message):
    total_users = await users_db.count_documents({})
    total_movies = await movie_info_db.count_documents({})
    total_files = await files_db.count_documents({})
    await message.reply_text(
        f"📊 **Bot Stats**\n\n"
        f"👥 Users: `{total_users}`\n"
        f"🎬 Movies: `{total_movies}`\n"
        f"📁 Files: `{total_files}`\n\n"
        f"📢 **Indexing Channel:** `{FILE_CHANNEL_ID}` (Hardcoded)"
    )

# চ্যানেল ম্যানেজমেন্ট কমান্ডগুলো (`/addchannel`, `/delchannel`, `/channels`) মুছে ফেলা হয়েছে।

# ========= 🙋‍♂️ ইউজার কমান্ড ও কলব্যাক হ্যান্ডলার (অপরিবর্তিত) ========= #
# start_handler, callback_handler, show_quality_options, smart_search_handler 
# ফাংশনগুলো আগের মতোই থাকবে, কোনো পরিবর্তনের প্রয়োজন নেই।
# ... (পূর্ববর্তী উত্তর থেকে এই ফাংশনগুলো এখানে কপি-পেস্ট করুন) ...

# --- ধাপ ২: সাধারণ ইউজার কমান্ড হ্যান্ডলার ---
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    if not await users_db.find_one({"_id": user_id}):
        await users_db.insert_one({"_id": user_id, "name": message.from_user.first_name})
    if len(message.command) > 1:
        try:
            payload = message.command[1]
            decoded_data = base64.urlsafe_b64decode(payload).decode()
            parts = decoded_data.split('_')
            if len(parts) != 3: raise ValueError("Invalid payload")
            action, data_id, verified_user_id_str = parts
            if user_id != int(verified_user_id_str): return await message.reply_text("😡 Verification Failed!")
            if action == "file":
                file_doc = await files_db.find_one({"_id": ObjectId(data_id)})
                if file_doc:
                    movie_doc = await movie_info_db.find_one({"_id": file_doc['movie_id']})
                    final_caption = (f"🎬 **{movie_doc['title']} ({movie_doc['year']})**\n✨ **Quality:** {file_doc['quality']}\n🌐 **Language:** {file_doc['language']}\n\n🙏 Thank you!")
                    movie_msg = await client.copy_message(chat_id=user_id, from_chat_id=file_doc['chat_id'], message_id=file_doc['msg_id'], caption=final_caption)
                    warning_msg = await message.reply_text(f"❗ File auto-deletes in **{DELETE_DELAY // 60} mins**.", quote=True)
                    asyncio.create_task(delete_messages_after_delay([movie_msg, warning_msg], DELETE_DELAY))
        except Exception as e: LOGGER.error(f"Deep link error: {e}"); await message.reply_text("🤔 Invalid/expired link.")
    else: await message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\nSend me a movie name to search.")

# --- ধাপ ৩: কলব্যাক হ্যান্ডলার ---
@app.on_callback_query()
async def callback_handler(client, callback_query):
    data, user_id = callback_query.data, callback_query.from_user.id
    if data.startswith("showqual_"):
        movie_id = ObjectId(data.split("_", 1)[1])
        await show_quality_options(callback_query.message, movie_id, is_edit=True)
    elif data.startswith("getfile_"):
        file_id_str = data.split("_", 1)[1]
        encoded_data = base64.urlsafe_b64encode(f'file_{file_id_str}_{user_id}'.encode()).decode()
        verification_url = f"{AD_PAGE_URL}?data={encoded_data}"
        await callback_query.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ ভেরিফাই করে ডাউনলোড করুন", url=verification_url)]]))
    await callback_query.answer()

async def show_quality_options(message, movie_id, is_edit=False):
    files_cursor = files_db.find({"movie_id": movie_id})
    files = await files_cursor.to_list(length=None)
    if not files: await message.reply_text("Sorry, no files found."); return
    movie = await movie_info_db.find_one({"_id": movie_id})
    buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"getfile_{f['_id']}")] for f in files]
    text = f"🎬 **{movie['title']} ({movie['year']})**\n\n👇 Select quality:"
    try:
        if is_edit: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        else: await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    except Exception as e: LOGGER.error(f"Show quality options error: {e}")

# --- ধাপ ৪: সাধারণ টেক্সট হ্যান্ডলার (চূড়ান্ত এবং সঠিক) ---
@app.on_message((filters.private | filters.group) & filters.text & ~filters.command(prefixes="/"))
async def smart_search_handler(client, message):
    if message.text.startswith('/') or message.from_user.is_bot: return
    query = message.text.strip()
    pipeline = [{'$search': {'index': 'default', 'autocomplete': {'query': query, 'path': 'search_title'}}}, {'$limit': 5}]
    results_cursor = movie_info_db.aggregate(pipeline)
    results = await results_cursor.to_list(length=None)

    if not results:
        if message.chat.type == ChatType.PRIVATE: await message.reply_text("❌ **Movie Not Found!**")
        return
    
    if len(results) == 1 and results[0]['title'].lower() == query.lower():
        await show_quality_options(message, results[0]['_id'])
    else:
        buttons = [[InlineKeyboardButton(f"🎬 {movie['title']} ({movie['year']})", callback_data=f"showqual_{movie['_id']}")] for movie in results]
        await message.reply_text("🤔 Did you mean one of these?", reply_markup=InlineKeyboardMarkup(buttons), quote=True)

# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা ========= #
def run_web_server():
    web_app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    LOGGER.info("Starting web server...")
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    LOGGER.info("The Don is waking up...")
    app.run()
    LOGGER.info("The Don is resting...")
