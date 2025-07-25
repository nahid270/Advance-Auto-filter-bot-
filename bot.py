# =====================================================================================
# ||                  GODFATHER MOVIE BOT (Final Stable Version)                     ||
# ||---------------------------------------------------------------------------------||
# || AttributeError এবং Unpacking Error সমাধানের পর এটি চূড়ান্ত সংস্করণ।              ||
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
# *** পরিবর্তন ১: ChatType ইম্পোর্ট করা হয়েছে ***
from pyrogram.enums import ChatType
from pymongo import MongoClient
from bson.objectid import ObjectId

# --- পরিবেশ সেটআপ ও কনফিগারেশন ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)

try:
    API_ID, API_HASH, BOT_TOKEN, MONGO_URL, AD_PAGE_URL, BOT_USERNAME = (
        int(os.environ.get("API_ID")), os.environ.get("API_HASH"), os.environ.get("BOT_TOKEN"),
        os.environ.get("MONGO_URL"), os.environ.get("AD_PAGE_URL"), os.environ.get("BOT_USERNAME")
    )
    ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(',')]
    PORT = int(os.environ.get("PORT", 8080))
    DELETE_DELAY = 15 * 60
except (ValueError, TypeError) as e:
    LOGGER.critical(f"Configuration error: {e}"); exit()

# --- ক্লায়েন্ট, ডাটাবেস ও ওয়েব অ্যাপ ---
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["MovieDB"]
movie_info_db = db["movie_info"]
files_db = db["files"]
users_db = db["users"]
channels_db = db["channels"]

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Bot is alive!"

# ========= 📄 হেল্পার ফাংশন ========= #
def is_admin(user_id): return user_id in ADMIN_IDS

async def delete_messages_after_delay(messages, delay):
    await asyncio.sleep(delay)
    for msg in messages:
        try: await msg.delete()
        except Exception as e: LOGGER.warning(f"Could not delete message {msg.id}: {e}")

# ========= 📢 চ্যানেল থেকে মুভি সেভ ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
async def save_movie_quality(client, message):
    if not channels_db.find_one({"_id": message.chat.id}): return
    caption = message.caption or ""
    title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", caption)
    if not title_match: LOGGER.warning(f"Could not parse title from message {message.id}"); return
    title, year = re.sub(r'[\.\_]', ' ', title_match.group(1).strip()), title_match.group(2)
    search_title = f"{title.lower()} {year}"
    quality = next((q for q in ["480p", "720p", "1080p", "2160p", "4K"] if q in caption.lower()), "Unknown")
    language = next((lang for lang in ["Hindi", "Bangla", "English", "Tamil", "Telugu", "Malayalam", "Kannada"] if lang.lower() in caption.lower()), "Unknown")
    movie_doc = movie_info_db.find_one_and_update(
        {"search_title": search_title}, {"$setOnInsert": {"title": title, "year": year, "search_title": search_title}},
        upsert=True, return_document=True
    )
    files_db.update_one(
        {"movie_id": movie_doc['_id'], "quality": quality, "language": language},
        {"$set": {"file_id": message.video.file_id if message.video else message.document.file_id, "chat_id": message.chat.id, "msg_id": message.id}},
        upsert=True
    )
    LOGGER.info(f"✅ Saved/Updated: {title} ({year}) [{quality} - {language}]")

# ========= 🎬 স্টার্ট কমান্ড এবং ভেরিফিকেশন হ্যান্ডলার (ত্রুটি সমাধান করা হয়েছে) ========= #
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    if not users_db.find_one({"_id": user_id}):
        users_db.insert_one({"_id": user_id, "name": message.from_user.first_name})

    if len(message.command) > 1:
        try:
            payload = message.command[1]
            decoded_data = base64.urlsafe_b64decode(payload).decode()
            
            # *** পরিবর্তন ২: পেলোড ফরম্যাট চেক করা হচ্ছে ***
            parts = decoded_data.split('_')
            if len(parts) != 3:
                raise ValueError("Invalid payload format")
            
            action, data_id, verified_user_id_str = parts

            if user_id != int(verified_user_id_str):
                return await message.reply_text("😡 **Verification Failed!** This link wasn't for you.")

            if action == "file":
                file_doc = files_db.find_one({"_id": ObjectId(data_id)})
                if file_doc:
                    movie_doc = movie_info_db.find_one({"_id": file_doc['movie_id']})
                    final_caption = (f"🎬 **{movie_doc['title']} ({movie_doc['year']})**\n✨ **Quality:** {file_doc['quality']}\n🌐 **Language:** {file_doc['language']}\n\n🙏 Thank you!")
                    movie_msg = await client.copy_message(chat_id=user_id, from_chat_id=file_doc['chat_id'], message_id=file_doc['msg_id'], caption=final_caption)
                    warning_msg = await message.reply_text(f"❗ **Important:** This file will be auto-deleted in **{DELETE_DELAY // 60} minutes**.", quote=True)
                    asyncio.create_task(delete_messages_after_delay([movie_msg, warning_msg], DELETE_DELAY))
                else: await message.reply_text("❌ Sorry, this file could not be found.")
        except (ValueError, Exception) as e:
            LOGGER.error(f"Deep link error for user {user_id}: {e}")
            await message.reply_text("🤔 Invalid or expired verification link.")
    else:
        await message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\nI am a movie search bot.")

# ========= 🛠️ অ্যাডমিন কমান্ডস (অপরিবর্তিত) ========= #
# ...

# ========= 🔎 স্মার্ট সার্চ (ত্রুটি সমাধান করা হয়েছে) ========= #
@app.on_message((filters.private | filters.group) & filters.text)
async def smart_search_handler(client, message):
    if message.from_user.is_bot: return
        
    query = message.text.strip()
    pipeline = [{'$search': {'index': 'default', 'autocomplete': {'query': query, 'path': 'search_title'}}}, {'$limit': 5}]
    results = list(movie_info_db.aggregate(pipeline))

    if not results:
        # *** পরিবর্তন ৩: ChatType সঠিকভাবে ব্যবহার করা হয়েছে ***
        if message.chat.type == ChatType.PRIVATE:
            await message.reply_text("❌ **Movie Not Found!**")
        return

    if len(results) == 1 and results[0]['title'].lower() == query.lower():
        await show_quality_options(message, results[0]['_id'])
    else:
        buttons = [[InlineKeyboardButton(f"🎬 {movie['title']} ({movie['year']})", callback_data=f"showqual_{movie['_id']}")] for movie in results]
        await message.reply_text("🤔 Did you mean one of these?", reply_markup=InlineKeyboardMarkup(buttons), quote=True)

# ========= 👆 কলব্যাক এবং কোয়ালিটি অপশন হ্যান্ডলার (অপরিবর্তিত) ========= #
@app.on_callback_query()
async def callback_handler(client, callback_query):
    data, user_id = callback_query.data, callback_query.from_user.id
    if data.startswith("showqual_"):
        movie_id = ObjectId(data.split("_")[1])
        await show_quality_options(callback_query.message, movie_id, is_edit=True)
    elif data.startswith("getfile_"):
        file_id_str = data.split("_")[1]
        encoded_data = base64.urlsafe_b64encode(f'file_{file_id_str}_{user_id}'.encode()).decode()
        verification_url = f"{AD_PAGE_URL}?data={encoded_data}"
        await callback_query.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ ভেরিফাই করে ডাউনলোড করুন", url=verification_url)]]))
    await callback_query.answer()

async def show_quality_options(message, movie_id, is_edit=False):
    files = list(files_db.find({"movie_id": movie_id}))
    if not files: await message.reply_text("Sorry, no files found for this movie."); return
    movie = movie_info_db.find_one({"_id": movie_id})
    buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"getfile_{f['_id']}")] for f in files]
    text = f"🎬 **{movie['title']} ({movie['year']})**\n\n👇 Please select your desired quality:"
    try:
        if is_edit: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        else: await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    except Exception as e: LOGGER.error(f"Error in show_quality_options: {e}")

# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা (অপরিবর্তিত) ========= #
def run_web_server(): web_app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    LOGGER.info("Starting web server...")
    web_thread = Thread(target=run_web_server); web_thread.start()
    LOGGER.info("The Don is waking up..."); app.run()
    LOGGER.info("The Don is resting...")
