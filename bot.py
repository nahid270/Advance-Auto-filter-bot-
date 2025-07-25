# =====================================================================================
# ||      GODFATHER MOVIE BOT (v3.0 - Final & Reliable Regex Search Version)         ||
# ||---------------------------------------------------------------------------------||
# ||     Atlas Search ছাড়া Regex ভিত্তিক নির্ভরযোগ্য সার্চ। কোনো বিশেষ DB কনফিগারেশন প্রয়োজন নেই।     ||
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

# --- আপনার ফাইল চ্যানেলের আইডি এখানে দিন ---
# আইডি অবশ্যই একটি সংখ্যা হতে হবে, যেমন: -1001234567890
FILE_CHANNEL_ID = -1002744890741 # <====== আপনার আসল ফাইল চ্যানেলের আইডি এখানে দিন

if FILE_CHANNEL_ID == -1001234567890:
    LOGGER.warning("CRITICAL: Please update the FILE_CHANNEL_ID in the code with your actual channel ID.")

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

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Bot is alive and running!"


# ========= 📄 হেল্পার ফাংশন ========= #
def is_admin(_, __, message):
    return message.from_user and message.from_user.id in ADMIN_IDS
admin_filter = filters.create(is_admin)

async def delete_messages_after_delay(messages, delay):
    await asyncio.sleep(delay)
    for msg in messages:
        try: await msg.delete()
        except Exception: pass


# ========= 📢 চ্যানেল থেকে মুভি সেভ ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
async def save_movie_quality(client, message):
    if message.chat.id != FILE_CHANNEL_ID: return
    
    caption = message.caption or ""
    # এখানে Regex উন্নত করা হয়েছে যেন ব্র্যাকেট ছাড়াও সাল খুঁজে পায়
    title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", caption, re.IGNORECASE)
    
    if not title_match:
        LOGGER.warning(f"Could not parse Title and Year from msg {message.id}. Caption: '{caption}'")
        return
        
    # নামের মধ্য থেকে অপ্রয়োজনীয় শব্দ বাদ দেওয়া হচ্ছে
    raw_title = title_match.group(1).strip()
    year = title_match.group(2)
    # নামের শেষে থাকা সিজন বা অন্য তথ্য বাদ দেওয়া
    clean_title = re.sub(r'\s*S\d+.*', '', raw_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r'[\.\_]', ' ', clean_title)

    quality = next((q for q in ["480p", "720p", "1080p", "2160p", "4k"] if q in caption.lower()), "Unknown")
    language = next((lang for lang in ["hindi", "bangla", "english", "tamil", "telugu", "malayalam", "kannada"] if lang.lower() in caption.lower()), "Unknown")
    
    movie_doc = await movie_info_db.find_one_and_update(
        {"title_lower": clean_title.lower(), "year": year},
        {"$setOnInsert": {"title": clean_title, "year": year, "title_lower": clean_title.lower()}},
        upsert=True, return_document=True
    )
    
    await files_db.update_one(
        {"movie_id": movie_doc['_id'], "quality": quality, "language": language},
        {"$set": {"file_id": message.video.file_id if message.video else message.document.file_id, "chat_id": message.chat.id, "msg_id": message.id}},
        upsert=True
    )
    LOGGER.info(f"✅ Indexed: {clean_title} ({year}) [{quality} - {language}]")


# ========= 💻 অ্যাডমিন ও সাধারণ কমান্ড ========= #
@app.on_message(filters.command("stats") & admin_filter)
async def stats_command(client, message):
    total_users = await users_db.count_documents({})
    total_movies = await movie_info_db.count_documents({})
    total_files = await files_db.count_documents({})
    await message.reply_text( f"📊 **Bot Stats**\n\n👥 Users: `{total_users}`\n🎬 Movies: `{total_movies}`\n📁 Files: `{total_files}`\n\n📢 **Indexing Channel:** `{FILE_CHANNEL_ID}` (Hardcoded)" )

@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    if not await users_db.find_one({"_id": user_id}):
        await users_db.insert_one({"_id": user_id, "name": message.from_user.first_name})
    if len(message.command) > 1:
        try:
            # ... (এই অংশটি অপরিবর্তিত)
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

# ========= 🔄 কলব্যাক হ্যান্ডলার ========= #
@app.on_callback_query()
async def callback_handler(client, callback_query):
    # ... (এই অংশটি অপরিবর্তিত)
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
    # ... (এই অংশটি অপরিবর্তিত)
    files_cursor = files_db.find({"movie_id": movie_id})
    files = await files_cursor.to_list(length=None)
    if not files: await message.reply_text("Sorry, no files found for this movie."); return
    movie = await movie_info_db.find_one({"_id": movie_id})
    if not movie: await message.reply_text("Sorry, could not find movie details."); return
    buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"getfile_{f['_id']}")] for f in sorted(files, key=lambda x: x.get('quality', ''))]
    text = f"🎬 **{movie['title']} ({movie['year']})**\n\n👇 Select quality:"
    try:
        if is_edit: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        else: await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    except Exception as e: LOGGER.error(f"Show quality options error: {e}")


# ========= 🔎 চূড়ান্ত এবং নির্ভরযোগ্য Regex সার্চ হ্যান্ডলার ========= #
@app.on_message((filters.private | filters.group) & filters.text)
async def reliable_search_handler(client, message):
    if message.text.startswith("/") or message.from_user.is_bot:
        return

    query = message.text.strip()
    # ব্যবহারকারীর ইনপুট থেকে শুধুমাত্র মূল শব্দগুলো নেওয়া হচ্ছে
    # যেমন: "watch sarzameen movie online free" হয়ে যাবে "sarzameen movie"
    cleaned_query = ' '.join(re.findall(r'\b[a-z\d]+\b', query.lower()))
    if not cleaned_query: return

    # Regex তৈরি করা হচ্ছে যা প্রতিটি শব্দের কাছাকাছি মিল খুঁজবে
    # যেমন: 'sarza meen' দিয়ে সার্চ করলে 'sarzameen' খুঁজে পাবে
    search_pattern = '.*'.join(cleaned_query.split())
    search_regex = re.compile(search_pattern, re.IGNORECASE)

    try:
        # ডাটাবেসে title_lower ফিল্ডে সরাসরি Regex দিয়ে সার্চ করা হচ্ছে
        results_cursor = movie_info_db.find({'title_lower': search_regex}).limit(10)
        results = await results_cursor.to_list(length=None)
        
        LOGGER.info(f"Regex search for '{cleaned_query}' (pattern: '{search_pattern}') found {len(results)} results.")

    except Exception as e:
        LOGGER.error(f"Database find error: {e}")
        await message.reply_text("⚠️ Bot is facing a database issue. Please report to the admin.")
        return

    if not results:
        if message.chat.type == ChatType.PRIVATE:
            await message.reply_text(f"❌ **Movie Not Found!**\n\nCould not find any movie matching '*{query}*'. Please check the spelling.")
        return
    
    # ফলাফল প্রদর্শন
    if len(results) == 1:
        await show_quality_options(message, results[0]['_id'])
    else:
        buttons = [
            [InlineKeyboardButton(f"🎬 {movie['title']} ({movie['year']})", callback_data=f"showqual_{movie['_id']}")]
            for movie in results
        ]
        await message.reply_text("🤔 Did you mean one of these?", reply_markup=InlineKeyboardMarkup(buttons), quote=True)


# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা ========= #
def run_web_server():
    web_app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    LOGGER.info("Starting web server...")
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    LOGGER.info("The Don is waking up... (Reliable Regex Search Mode)")
    app.run()
    LOGGER.info("The Don is resting...")
