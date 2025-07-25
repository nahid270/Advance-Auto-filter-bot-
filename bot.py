# =====================================================================================
# ||      GODFATHER MOVIE BOT (v4.4 - Final with Smart Search)                     ||
# ||---------------------------------------------------------------------------------||
# || এই সংস্করণে গ্রুপ ও প্রাইভেট চ্যাটের সমস্ত মেসেজ অটো-ডিলিট করা হবে।            ||
# || গ্রুপে সার্চ করে মুভি না পেলে বট চুপ থাকবে এবং প্রাইভেটে রিপ্লাই দেবে।        ||
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

# --- আপনার ফাইল চ্যানেলের আইডি এখানে দিন ---
FILE_CHANNEL_ID = -1002744890741  # <====== আপনার আসল ফাইল চ্যানেলের আইডি এখানে দিন
if FILE_CHANNEL_ID == 0:
    LOGGER.critical("CRITICAL: Please update the FILE_CHANNEL_ID in the code.")
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

# ========= 📢 নমনীয় ইনডেক্সিং হ্যান্ডলার ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
async def flexible_save_movie_quality(client, message):
    if message.chat.id != FILE_CHANNEL_ID: return
    caption = message.caption or ""
    # শিরোনাম এবং বছর বের করার চেষ্টা
    title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", caption, re.IGNORECASE)
    year = None
    if title_match:
        raw_title = title_match.group(1).strip()
        year = title_match.group(2)
    else: # যদি বছর খুঁজে না পাওয়া যায়, তবে স্টপ-ওয়ার্ড ব্যবহার করে শিরোনাম বের করা
        stop_words = ['480p', '720p', '1080p', '2160p', '4k', 'hindi', 'english', 'bangla', 'bengali', 'dual', 'audio', 'web-dl', 'hdrip', 'bluray', 'webrip']
        title_words = []
        for word in caption.split():
            if any(stop in word.lower() for stop in stop_words): break
            title_words.append(word)
        raw_title = ' '.join(title_words).strip()

    if not raw_title:
        LOGGER.warning(f"Could not parse a valid title from caption: '{caption}'"); return

    clean_title = re.sub(r'[\.\_]', ' ', raw_title).strip()
    quality = next((q for q in ["480p", "720p", "1080p", "2160p", "4k"] if q in caption.lower()), "Unknown")
    languages_to_check = ["hindi", "bangla", "bengali", "english", "tamil", "telugu", "malayalam", "kannada"]
    caption_lower = caption.lower()
    language = "Unknown"
    for lang in languages_to_check:
        if lang in caption_lower:
            language = "Bangla" if lang in ["bangla", "bengali"] else lang.capitalize()
            break
    
    # ডাটাবেসে মুভির তথ্য সেভ করা
    query = {"title_lower": clean_title.lower()}
    if year: query["year"] = year
    movie_doc = await movie_info_db.find_one_and_update(
        query,
        {"$setOnInsert": {"title": clean_title, "year": year, "title_lower": clean_title.lower()}},
        upsert=True,
        return_document=True
    )
    # ডাটাবেসে ফাইলের তথ্য সেভ করা
    file_info = message.video or message.document
    await files_db.update_one(
        {"movie_id": movie_doc['_id'], "quality": quality, "language": language},
        {"$set": {"file_id": file_info.file_id, "chat_id": message.chat.id, "msg_id": message.id}},
        upsert=True
    )
    log_year = f"({year})" if year else "(No Year)"
    LOGGER.info(f"✅ Indexed: {clean_title} {log_year} [{quality} - {language}]")

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
        f"👥 Users: `{total_users}`\n"
        f"🎬 Movies: `{total_movies}`\n"
        f"📁 Files: `{total_files}`\n\n"
        f"📢 **Indexing Channel:** `{FILE_CHANNEL_ID}`"
    )

# ========= 🤖 স্টার্ট এবং কলব্যাক হ্যান্ডলার ========= #
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    await users_db.update_one({"_id": user_id}, {"$set": {"name": message.from_user.first_name}}, upsert=True)
    
    # ডীপ লিঙ্কিং হ্যান্ডেল করা (ভেরিফিকেশনের পর ফাইল পাঠানোর জন্য)
    if len(message.command) > 1:
        try:
            payload = message.command[1]
            decoded_data = base64.urlsafe_b64decode(payload).decode()
            parts = decoded_data.split('_')
            if len(parts) != 3: raise ValueError("Invalid payload format")
            
            action, data_id, verified_user_id_str = parts
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
                    
                    movie_msg = await client.copy_message(
                        chat_id=user_id, from_chat_id=file_doc['chat_id'],
                        message_id=file_doc['msg_id'], caption=final_caption
                    )
                    warning_msg = await message.reply_text(f"❗ ফাইলটি **{DELETE_DELAY // 60} মিনিট** পর অটো-ডিলিট হয়ে যাবে।", quote=True)
                    asyncio.create_task(delete_messages_after_delay([movie_msg, warning_msg], DELETE_DELAY))
        except Exception as e:
            LOGGER.error(f"Deep link error: {e}")
            await message.reply_text("🤔 লিঙ্কটি সম্ভবত inválid বা মেয়াদোত্তীর্ণ।")
    else:
        reply_msg = await message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\nSend me a movie or series name to search.")
        asyncio.create_task(delete_messages_after_delay([message, reply_msg], 120)) # ২ মিনিট পর ডিলিট হবে

@app.on_callback_query()
async def callback_handler(client, callback_query):
    data, user_id = callback_query.data, callback_query.from_user.id
    
    if data.startswith("showqual_"):
        movie_id = ObjectId(data.split("_", 1)[1])
        # কোয়ালিটি লিস্ট মেসেজটি ১৫ মিনিট থাকবে
        new_msg = await show_quality_options(callback_query.message, movie_id, is_edit=True, return_message=True)
        if new_msg:
            asyncio.create_task(delete_messages_after_delay([new_msg], DELETE_DELAY))

    elif data.startswith("getfile_"):
        file_id_str = data.split("_", 1)[1]
        encoded_data = base64.urlsafe_b64encode(f'file_{file_id_str}_{user_id}'.encode()).decode()
        verification_url = f"{AD_PAGE_URL}?data={encoded_data}"
        await callback_query.message.edit_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton("✅ ভেরিফাই করে ডাউনলোড করুন", url=verification_url)]])
        )
    
    await callback_query.answer()

async def show_quality_options(message, movie_id, is_edit=False, return_message=False):
    """মুভির কোয়ালিটি অপশন দেখায়"""
    reply_msg = None
    try:
        files = await files_db.find({"movie_id": movie_id}).to_list(length=None)
        if not files:
            text = "দুঃখিত, এই মুভির জন্য কোনো ফাইল পাওয়া যায়নি।"
            reply_msg = await message.edit_text(text) if is_edit else await message.reply_text(text)
            return reply_msg if return_message else None

        movie = await movie_info_db.find_one({"_id": movie_id})
        if not movie:
            text = "দুঃখিত, মুভির বিস্তারিত তথ্য পাওয়া যায়নি।"
            reply_msg = await message.edit_text(text) if is_edit else await message.reply_text(text)
            return reply_msg if return_message else None

        display_year = f"({movie['year']})" if movie.get('year') else ""
        text = f"🎬 **{movie['title']} {display_year}**\n\n👇 আপনার পছন্দের কোয়ালিটি বেছে নিন:"
        buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"getfile_{f['_id']}")] 
                   for f in sorted(files, key=lambda x: x.get('quality', ''))]
        
        markup = InlineKeyboardMarkup(buttons)
        if is_edit:
            await message.edit_text(text, reply_markup=markup)
            reply_msg = message
        else:
            reply_msg = await message.reply_text(text, reply_markup=markup, quote=True)
        
        return reply_msg if return_message else None

    except MessageNotModified:
        return message if return_message else None
    except Exception as e:
        LOGGER.error(f"Show quality options error: {e}")
        return None

# ========= 🔎 চূড়ান্ত Regex সার্চ হ্যান্ডলার (গ্রুপে সাইলেন্ট, প্রাইভেটে রেসপন্সিভ) ========= #
@app.on_message((filters.private | filters.group) & filters.text & ~filters.command())
async def reliable_search_handler(client, message):
    if message.from_user.is_bot: return

    query = message.text.strip()
    # শুধুমাত্র অক্ষর ও সংখ্যা নিয়ে সার্চ কোয়েরি তৈরি করা
    cleaned_query = ' '.join(re.findall(r'\b[a-zA-Z0-9]+\b', query.lower()))
    if not cleaned_query: return
    
    # फ्लेক্সিবল সার্চের জন্য Regex প্যাটার্ন তৈরি
    search_pattern = '.*'.join(cleaned_query.split())
    search_regex = re.compile(search_pattern, re.IGNORECASE)
    
    messages_to_delete = [message]
    reply_msg = None

    try:
        results = await movie_info_db.find({'title_lower': search_regex}).limit(10).to_list(length=10)
        LOGGER.info(f"Search for '{cleaned_query}' in chat {message.chat.id} ({message.chat.type.name}) found {len(results)} results.")
    except Exception as e:
        LOGGER.error(f"Database find error: {e}")
        # শুধুমাত্র প্রাইভেট চ্যাটে ডাটাবেস এরর দেখানো ভালো
        if message.chat.type == ChatType.PRIVATE:
            reply_msg = await message.reply_text("⚠️ বট একটি ডাটাবেস সমস্যার সম্মুখীন হয়েছে।")
            messages_to_delete.append(reply_msg)
        asyncio.create_task(delete_messages_after_delay(messages_to_delete, 60))
        return

    if not results:
        # ## <<<--- মূল পরিবর্তন এখানে ---<<< ##
        # শুধুমাত্র প্রাইভেট চ্যাটে "Not Found" মেসেজ পাঠানো হবে
        if message.chat.type == ChatType.PRIVATE:
            reply_msg = await message.reply_text(
                "❌ **মুভিটি খুঁজে পাওয়া যায়নি!**\n\n"
                "অনুগ্রহ করে নামের বানানটি পরীক্ষা করে আবার চেষ্টা করুন।",
                quote=True
            )
            messages_to_delete.append(reply_msg)
        # গ্রুপে কোনো ফলাফল না পাওয়া গেলে বট চুপ থাকবে।

    elif len(results) == 1:
        reply_msg = await show_quality_options(message, results[0]['_id'], return_message=True)
        if reply_msg:
            messages_to_delete.append(reply_msg)
            
    else: # len(results) > 1
        buttons = []
        for movie in results:
            display_year = f"({movie['year']})" if movie.get('year') else ""
            buttons.append([InlineKeyboardButton(f"🎬 {movie['title']} {display_year}", callback_data=f"showqual_{movie['_id']}")])
        
        reply_msg = await message.reply_text(
            "🤔 আপনি কি এগুলোর মধ্যে কোনো একটি খুঁজছেন?",
            reply_markup=InlineKeyboardMarkup(buttons),
            quote=True
        )
        messages_to_delete.append(reply_msg)
    
    # সমস্ত প্রাসঙ্গিক মেসেজ (সার্চ, রিপ্লাই) ডিলিট করার জন্য শিডিউল করা
    if messages_to_delete:
        asyncio.create_task(delete_messages_after_delay(messages_to_delete, DELETE_DELAY))

# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা ========= #
def run_web_server():
    """Flask ওয়েব সার্ভার একটি আলাদা থ্রেডে রান করে"""
    web_app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    LOGGER.info("Starting web server on a separate thread...")
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    LOGGER.info("The Don is waking up... (v4.4 Final - Smart Search)")
    app.run()
    LOGGER.info("The Don is resting...")
