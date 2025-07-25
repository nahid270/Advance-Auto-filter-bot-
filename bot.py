# =====================================================================================
# ||      GODFATHER MOVIE BOT (v5.0 - Final with Bulk Indexing)                     ||
# ||---------------------------------------------------------------------------------||
# || এই সংস্করণে স্বয়ংক্রিয় এবং কমান্ড-ভিত্তিক উভয় প্রকার ইনডেক্সিং রয়েছে।        ||
# || গ্রুপে সার্চ করলে সাইলেন্ট এবং প্রাইভেটে রিপ্লাই দেবে ও মেসেজ অটো-ডিলিট হবে।  ||
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
from pyrogram.errors import MessageNotModified
from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId

# --- পরিবেশ সেটআপ ও কনফিগারেশন ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)

# --- আপনার প্রধান ফাইল চ্যানেলের আইডি এখানে দিন ---
FILE_CHANNEL_ID = int(os.environ.get("FILE_CHANNEL_ID", "0"))
if FILE_CHANNEL_ID == 0:
    LOGGER.critical("CRITICAL: Please update the FILE_CHANNEL_ID in your environment variables or in the code.")
    exit()

try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    MONGO_URL = os.environ.get("MONGO_URL")
    AD_PAGE_URL = os.environ.get("AD_PAGE_URL")
    ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(',') if id.strip()]
    PORT = int(os.environ.get("PORT", 8080))
    DELETE_DELAY = 15 * 60  # 15 মিনিট
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
    """কমান্ডটি অ্যাডমিন পাঠিয়েছে কিনা তা পরীক্ষা করে"""
    return message.from_user and message.from_user.id in ADMIN_IDS

admin_filter = filters.create(is_admin)

async def delete_messages_after_delay(messages_to_delete, delay):
    """নির্দিষ্ট সময় পর মেসেজ ডিলিট করার টাস্ক তৈরি করে"""
    await asyncio.sleep(delay)
    for msg in messages_to_delete:
        try:
            if msg: await msg.delete()
        except Exception:
            pass

async def index_file(message):
    """একটি মেসেজ থেকে ফাইল ইনডেক্স করার মূল লজিক। সফল হলে True, ব্যর্থ হলে False রিটার্ন করে।"""
    try:
        if not (message.video or message.document): return False
        
        caption = message.caption or ""
        # শিরোনাম এবং বছর বের করার চেষ্টা
        title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", caption, re.IGNORECASE)
        year = None
        if title_match:
            raw_title = title_match.group(1).strip()
            year = title_match.group(2)
        else:
            stop_words = ['480p', '720p', '1080p', '2160p', '4k', 'hindi', 'english', 'bangla', 'bengali', 'dual', 'audio', 'web-dl', 'hdrip', 'bluray', 'webrip']
            title_words = []
            for word in caption.split():
                if any(stop in word.lower() for stop in stop_words): break
                title_words.append(word)
            raw_title = ' '.join(title_words).strip()

        if not raw_title:
            LOGGER.warning(f"Could not parse a valid title from caption: '{caption}' in chat {message.chat.id}")
            return False

        clean_title = re.sub(r'[\.\_]', ' ', raw_title).strip()
        quality = next((q for q in ["480p", "720p", "1080p", "2160p", "4k"] if q in caption.lower()), "Unknown")
        languages_to_check = ["hindi", "bangla", "bengali", "english", "tamil", "telugu", "malayalam", "kannada"]
        language = "Unknown"
        for lang in languages_to_check:
            if lang in caption.lower():
                language = "Bangla" if lang in ["bangla", "bengali"] else lang.capitalize()
                break
        
        query = {"title_lower": clean_title.lower()}
        if year: query["year"] = year
        movie_doc = await movie_info_db.find_one_and_update(
            query, 
            {"$setOnInsert": {"title": clean_title, "year": year, "title_lower": clean_title.lower()}}, 
            upsert=True, 
            return_document=True
        )
        
        file_info = message.video or message.document
        await files_db.update_one(
            {"movie_id": movie_doc['_id'], "quality": quality, "language": language},
            {"$set": {"file_id": file_info.file_id, "chat_id": message.chat.id, "msg_id": message.id}},
            upsert=True
        )
        return True
    except Exception as e:
        LOGGER.error(f"Error indexing file from message {message.id} in chat {message.chat.id}: {e}")
        return False

# ========= 📢 স্বয়ংক্রিয় ইনডেক্সিং হ্যান্ডলার ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
async def auto_index_handler(client, message):
    if message.chat.id == FILE_CHANNEL_ID:
        if await index_file(message):
            log_year = ""
            if message.caption:
                match = re.search(r"\((\d{4})\)", message.caption)
                if match: log_year = f"({match.group(1)})"
            LOGGER.info(f"✅ Auto-Indexed: '{message.caption.splitlines()[0]}' {log_year} from main channel.")

# ========= 👮 অ্যাডমিন কমান্ড ========= #
@app.on_message(filters.command("stats") & admin_filter)
async def stats_command(client, message):
    total_users, total_movies, total_files = await asyncio.gather(
        users_db.count_documents({}), 
        movie_info_db.count_documents({}), 
        files_db.count_documents({})
    )
    await message.reply_text(
        f"📊 **Bot Stats**\n\n"
        f"👥 মোট ব্যবহারকারী: `{total_users}`\n"
        f"🎬 মোট মুভি: `{total_movies}`\n"
        f"📁 মোট ফাইল: `{total_files}`\n\n"
        f"📢 **স্বয়ংক্রিয় ইনডেক্সিং চ্যানেল:** `{FILE_CHANNEL_ID}`"
    )

@app.on_message(filters.command("index") & admin_filter)
async def bulk_index_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "<b>❌ ভুল ব্যবহার।</b>\n\n"
            "অনুগ্রহ করে একটি চ্যানেল আইডি দিন।\n"
            "<b>ব্যবহারের নিয়ম:</b> <code>/index -100xxxxxxxxxx</code>"
        )

    try:
        target_channel_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("<b>❌ ভুল চ্যানেল আইডি।</b> আইডি অবশ্যই একটি সংখ্যা হতে হবে।")

    status_msg = await message.reply_text(f"⏳ চ্যানেল `{target_channel_id}` থেকে ইনডেক্সিং শুরু হচ্ছে... অনুগ্রহ করে অপেক্ষা করুন।")

    total_scanned = 0
    successfully_indexed = 0

    try:
        async for history_message in client.get_chat_history(target_channel_id):
            total_scanned += 1
            if await index_file(history_message):
                successfully_indexed += 1
            
            if total_scanned % 200 == 0:
                try:
                    await status_msg.edit_text(
                        f"⏳ ইনডেক্সিং চলছে...\n\n"
                        f"📄 মোট মেসেজ স্ক্যান করা হয়েছে: `{total_scanned}`\n"
                        f"📥 সফলভাবে ইনডেক্স হয়েছে: `{successfully_indexed}`"
                    )
                except MessageNotModified:
                    pass

    except Exception as e:
        await status_msg.edit_text(f"<b>⚠️ একটি সমস্যা হয়েছে:</b>\n\n`{e}`\n\nদয়া করে নিশ্চিত করুন বটটি ওই চ্যানেলের অ্যাডমিন এবং মেসেজ পড়ার অনুমতি আছে।")
        return

    await status_msg.edit_text(
        f"✅ <b>ইনডেক্সিং সম্পন্ন!</b>\n\n"
        f"📄 মোট মেসেজ স্ক্যান করা হয়েছে: `{total_scanned}`\n"
        f"📥 সফলভাবে ইনডেক্স হয়েছে: `{successfully_indexed}`"
    )

# ========= 🤖 স্টার্ট এবং কলব্যাক হ্যান্ডলার ========= #
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    await users_db.update_one({"_id": user_id}, {"$set": {"name": message.from_user.first_name}}, upsert=True)
    
    if len(message.command) > 1:
        try:
            payload = message.command[1]
            decoded_data = base64.urlsafe_b64decode(payload).decode()
            action, data_id, verified_user_id_str = decoded_data.split('_')
            
            if user_id != int(verified_user_id_str):
                return await message.reply_text("😡 এই লিঙ্কটি আপনার জন্য নয়।")

            if action == "file":
                file_doc = await files_db.find_one({"_id": ObjectId(data_id)})
                if file_doc:
                    movie_doc = await movie_info_db.find_one({"_id": file_doc['movie_id']})
                    display_year = f"({movie_doc['year']})" if movie_doc.get('year') else ""
                    final_caption = (f"🎬 **{movie_doc['title']} {display_year}**\n"
                                     f"✨ **Quality:** {file_doc['quality']}\n"
                                     f"🌐 **Language:** {file_doc['language']}\n\n"
                                     f"🙏 Thank you for using our bot!")
                    
                    movie_msg = await client.copy_message(chat_id=user_id, from_chat_id=file_doc['chat_id'], message_id=file_doc['msg_id'], caption=final_caption)
                    warning_msg = await message.reply_text(f"❗ ফাইলটি **{DELETE_DELAY // 60} মিনিট** পর অটো-ডিলিট হয়ে যাবে।", quote=True)
                    asyncio.create_task(delete_messages_after_delay([movie_msg, warning_msg], DELETE_DELAY))
        except Exception as e:
            LOGGER.error(f"Deep link error: {e}")
            await message.reply_text("🤔 লিঙ্কটি সম্ভবত inválid বা মেয়াদোত্তীর্ণ।")
    else:
        reply_msg = await message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\nSend me a movie or series name to search.")
        asyncio.create_task(delete_messages_after_delay([message, reply_msg], 120))

@app.on_callback_query()
async def callback_handler(client, callback_query):
    data, user_id = callback_query.data, callback_query.from_user.id
    
    if data.startswith("showqual_"):
        movie_id = ObjectId(data.split("_", 1)[1])
        new_msg = await show_quality_options(callback_query.message, movie_id, is_edit=True, return_message=True)
        if new_msg:
            asyncio.create_task(delete_messages_after_delay([new_msg], DELETE_DELAY))

    elif data.startswith("getfile_"):
        file_id_str = data.split("_", 1)[1]
        encoded_data = base64.urlsafe_b64encode(f'file_{file_id_str}_{user_id}'.encode()).decode()
        verification_url = f"{AD_PAGE_URL}?data={encoded_data}"
        await callback_query.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ ভেরিফাই করে ডাউনলোড করুন", url=verification_url)]]))
    
    await callback_query.answer()

async def show_quality_options(message, movie_id, is_edit=False, return_message=False):
    try:
        files = await files_db.find({"movie_id": movie_id}).sort("quality").to_list(length=None)
        if not files:
            text = "দুঃখিত, এই মুভির জন্য কোনো ফাইল পাওয়া যায়নি।"
            reply_msg = await message.edit_text(text) if is_edit else await message.reply_text(text, quote=True)
            return reply_msg if return_message else None

        movie = await movie_info_db.find_one({"_id": movie_id})
        display_year = f"({movie['year']})" if movie and movie.get('year') else ""
        text = f"🎬 **{movie['title']} {display_year}**\n\n👇 আপনার পছন্দের কোয়ালিটি বেছে নিন:"
        buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"getfile_{f['_id']}")] for f in files]
        
        if is_edit:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            return message if return_message else None
        else:
            return await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)

    except MessageNotModified:
        return message if return_message else None
    except Exception as e:
        LOGGER.error(f"Show quality options error: {e}")
        return None

# ========= 🔎 চূড়ান্ত Regex সার্চ হ্যান্ডলার ========= #
@app.on_message((filters.private | filters.group) & filters.text & ~filters.command(["start", "stats", "index"]))
async def reliable_search_handler(client, message):
    if not message.text or message.from_user.is_bot: return

    query = message.text.strip()
    cleaned_query = ' '.join(re.findall(r'\b[a-zA-Z0-9]+\b', query.lower()))
    if not cleaned_query: return
    
    search_pattern = '.*'.join(cleaned_query.split())
    search_regex = re.compile(search_pattern, re.IGNORECASE)
    
    messages_to_delete = [message]
    reply_msg = None

    try:
        results = await movie_info_db.find({'title_lower': search_regex}).limit(10).to_list(length=10)
    except Exception as e:
        LOGGER.error(f"Database find error: {e}")
        if message.chat.type == ChatType.PRIVATE:
            reply_msg = await message.reply_text("⚠️ ডাটাবেস সংযোগে একটি সমস্যা হয়েছে।")
            messages_to_delete.append(reply_msg)
        asyncio.create_task(delete_messages_after_delay(messages_to_delete, 60))
        return

    if not results:
        if message.chat.type == ChatType.PRIVATE:
            reply_msg = await message.reply_text("❌ **মুভিটি খুঁজে পাওয়া যায়নি!**\n\nঅনুগ্রহ করে নামের বানানটি পরীক্ষা করে আবার চেষ্টা করুন।", quote=True)
    elif len(results) == 1:
        reply_msg = await show_quality_options(message, results[0]['_id'], return_message=True)
    else:
        buttons = []
        for movie in results:
            display_year = f"({movie['year']})" if movie.get('year') else ""
            buttons.append([InlineKeyboardButton(f"🎬 {movie['title']} {display_year}", callback_data=f"showqual_{movie['_id']}")])
        
        reply_msg = await message.reply_text("🤔 আপনি কি এগুলোর মধ্যে কোনো একটি খুঁজছেন?", reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    
    if reply_msg:
        messages_to_delete.append(reply_msg)
    
    if messages_to_delete:
        asyncio.create_task(delete_messages_after_delay(messages_to_delete, DELETE_DELAY))

# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা ========= #
def run_web_server():
    """Flask web server-কে একটি আলাদা থ্রেডে চালায়।"""
    web_app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    LOGGER.info("Starting web server on a separate thread...")
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    LOGGER.info("The Don is waking up... (v5.0 - Final with Bulk Indexing)")
    app.run()
    LOGGER.info("The Don is resting...")
