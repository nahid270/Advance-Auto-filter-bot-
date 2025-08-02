# =====================================================================================
# ||      GODFATHER MOVIE BOT (v5.0 - Smart Suggestion Update)                     ||
# ||---------------------------------------------------------------------------------||
# || এই সংস্করণে গ্রুপ ও প্রাইভেট চ্যাটের সমস্ত মেসেজ অটো-ডিলিট করা হবে।            ||
# || গ্রুপে সার্চ করে মুভি না পেলে বট চুপ থাকবে এবং প্রাইভেটে রিপ্লাই দেবে।        ||
# || সার্চ রেজাল্টে পেজিনেশন (পৃষ্ঠা নম্বর) যুক্ত করা হয়েছে।                         ||
# || অ্যাডমিনদের জন্য মুভি ডিলিট করার কমান্ড যুক্ত করা হয়েছে।                       ||
# || মুভি না পেলে ইউজাররা অ্যাডমিনের কাছে অনুরোধ পাঠাতে পারবে এবং অ্যাডমিন রিপ্লাই দিতে পারবে।||
# || নতুন: ভুল বানানের জন্য বট এখন সঠিক নামের সাজেশন দেখাবে।                      ||
# =====================================================================================

import os
import re
import math
import base64
import logging
import asyncio
from dotenv import load_dotenv
from threading import Thread
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from pyrogram.enums import ChatType
from pyrogram.errors import MessageNotModified
from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId
from thefuzz import process

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
    LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID"))
    PORT = int(os.environ.get("PORT", 8080))
    DELETE_DELAY = 15 * 60  # 15 মিনিট
    SEARCH_PAGE_SIZE = 8
except (ValueError, TypeError) as e:
    LOGGER.critical(f"Configuration error in environment variables: {e}")
    exit()

if LOG_CHANNEL_ID == 0:
    LOGGER.critical("CRITICAL: Please set the LOG_CHANNEL_ID in your environment variables.")
    exit()

# --- ক্লায়েন্ট, ডাটাবেস ও ওয়েব অ্যাপ ---
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["MovieDB"]
movie_info_db, files_db, users_db = db["movie_info"], db["files"], db["users"]
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Bot is alive and running!"

# ========= 📄 হেল্পার ফাংশন ========= #
def is_admin(_, __, message):
    return message.from_user and message.from_user.id in ADMIN_IDS
admin_filter = filters.create(is_admin)

async def delete_messages_after_delay(messages_to_delete, delay):
    await asyncio.sleep(delay)
    for msg in messages_to_delete:
        try:
            if msg: await msg.delete()
        except Exception: pass

# ========= 📢 নমনীয় ইনডেক্সিং হ্যান্ডলার ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
async def flexible_save_movie_quality(client, message):
    if message.chat.id != FILE_CHANNEL_ID: return
    caption = message.caption or ""
    title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", caption, re.IGNORECASE)
    year = None
    if title_match:
        raw_title, year = title_match.group(1).strip(), title_match.group(2)
    else:
        stop_words = ['480p', '720p', '1080p', '2160p', '4k', 'hindi', 'english', 'bangla', 'bengali', 'dual', 'audio', 'web-dl', 'hdrip', 'bluray', 'webrip']
        title_words = []
        for word in caption.split():
            if any(stop in word.lower() for stop in stop_words): break
            title_words.append(word)
        raw_title = ' '.join(title_words).strip()
    if not raw_title: LOGGER.warning(f"Could not parse a valid title from caption: '{caption}'"); return
    
    clean_title = re.sub(r'[\.\_]', ' ', raw_title).strip()
    quality = next((q for q in ["480p", "720p", "1080p", "2160p", "4k"] if q in caption.lower()), "Unknown")
    languages_to_check = ["hindi", "bangla", "bengali", "english", "tamil", "telugu", "malayalam", "kannada"]
    caption_lower = caption.lower()
    language = "Unknown"
    for lang in languages_to_check:
        if lang in caption_lower:
            language = "Bangla" if lang in ["bangla", "bengali"] else lang.capitalize()
            break
    
    query = {"title_lower": clean_title.lower()}
    if year: query["year"] = year
    movie_doc = await movie_info_db.find_one_and_update(query, {"$setOnInsert": {"title": clean_title, "year": year, "title_lower": clean_title.lower()}}, upsert=True, return_document=True)
    
    file_info = message.video or message.document
    await files_db.update_one({"movie_id": movie_doc['_id'], "quality": quality, "language": language}, {"$set": {"file_id": file_info.file_id, "chat_id": message.chat.id, "msg_id": message.id}}, upsert=True)
    
    log_year = f"({year})" if year else "(No Year)"
    LOGGER.info(f"✅ Indexed: {clean_title} {log_year} [{quality} - {language}]")

# ========= 👮 অ্যাডমিন কমান্ড ========= #
@app.on_message(filters.command("stats") & admin_filter)
async def stats_command(client, message):
    total_users, total_movies, total_files = await asyncio.gather(users_db.count_documents({}), movie_info_db.count_documents({}), files_db.count_documents({}))
    await message.reply_text(f"📊 **Bot Stats**\n\n👥 Users: `{total_users}`\n🎬 Movies: `{total_movies}`\n📁 Files: `{total_files}`\n\n📢 **Indexing Channel:** `{FILE_CHANNEL_ID}`\n🔔 **Log Channel:** `{LOG_CHANNEL_ID}`")

@app.on_message(admin_filter & filters.reply)
async def admin_reply_handler(client, message):
    if not (message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.is_self): return

    prompt_text = message.reply_to_message.text
    if "কে রিপ্লাই করতে আপনার মেসেজটি এখানে পাঠান" in prompt_text:
        user_id_match = re.search(r"User ID `(\d+)`", prompt_text)
        if user_id_match:
            target_user_id = int(user_id_match.group(1))
            try:
                await message.copy(chat_id=target_user_id)
                await message.reply_text("✅ আপনার বার্তা ব্যবহারকারীর কাছে সফলভাবে পাঠানো হয়েছে।")
                await message.reply_to_message.delete()
            except Exception as e:
                await message.reply_text(f"❌ বার্তা পাঠাতে ব্যর্থ। কারণ: {e}")

@app.on_message(filters.command("del") & admin_filter)
async def delete_movie_command(client, message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **ব্যবহার:** `/del <মুভির নাম>`")
    query = message.text.split(None, 1)[1].strip()
    search_regex = re.compile('.*'.join(query.split()), re.IGNORECASE)
    results = await movie_info_db.find({'title_lower': search_regex}).to_list(length=20)
    if not results: return await message.reply_text(f"❌ `'{query}'` নামে কোনো মুভি খুঁজে পাওয়া যায়নি।")
    buttons = [[InlineKeyboardButton(f"🗑️ {movie['title']} {f'({movie['year']})' if movie.get('year') else ''}", callback_data=f"confirmdel_{movie['_id']}")] for movie in results]
    buttons.append([InlineKeyboardButton("🚫 বাতিল করুন", callback_data="cancel_delete")])
    await message.reply_text("❓ আপনি নিচের কোনটি ডিলিট করতে চান? নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(buttons), quote=True)

@app.on_message(filters.command("delall") & admin_filter)
async def delete_all_command(client, message):
    total_movies = await movie_info_db.count_documents({})
    if total_movies == 0: return await message.reply_text("✅ ডাটাবেস আগে থেকেই খালি আছে।")
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ হ্যাঁ, আমি নিশ্চিত", callback_data="delall_confirm_yes")], [InlineKeyboardButton("🚫 না, থাক", callback_data="cancel_delete")]])
    await message.reply_text(f"🗑️ **সতর্কবার্তা!**\n\nআপনি কি ডাটাবেস থেকে সমস্ত **{total_movies}** টি মুভি এবং তাদের ফাইল স্থায়ীভাবে মুছে ফেলতে চান?\n\n**এই কাজটি আর ফেরানো যাবে না।**", reply_markup=markup, quote=True)

# ========= 🤖 স্টার্ট এবং কলব্যাক হ্যান্ডলার ========= #
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    await users_db.update_one({"_id": user_id}, {"$set": {"name": message.from_user.first_name}}, upsert=True)
    if len(message.command) > 1:
        try:
            decoded_data = base64.urlsafe_b64decode(message.command[1]).decode()
            action, data_id, verified_user_id_str = decoded_data.split('_')
            if user_id != int(verified_user_id_str): return await message.reply_text("😡 এই লিঙ্কটি আপনার জন্য নয়।")
            if action == "file":
                file_doc = await files_db.find_one({"_id": ObjectId(data_id)})
                if file_doc:
                    movie_doc = await movie_info_db.find_one({"_id": file_doc['movie_id']})
                    final_caption = (f"🎬 **{movie_doc['title']} {f'({movie_doc['year']})' if movie_doc.get('year') else ''}**\n"
                                     f"✨ **Quality:** {file_doc['quality']}\n🌐 **Language:** {file_doc['language']}\n\n"
                                     f"🙏 Thank you for using our bot!")
                    movie_msg = await client.copy_message(user_id, file_doc['chat_id'], file_doc['msg_id'], caption=final_caption)
                    warning_msg = await message.reply_text(f"❗ ফাইলটি **{DELETE_DELAY // 60} মিনিট** পর অটো-ডিলিট হয়ে যাবে।", quote=True)
                    asyncio.create_task(delete_messages_after_delay([movie_msg, warning_msg], DELETE_DELAY))
        except Exception as e: LOGGER.error(f"Deep link error: {e}"); await message.reply_text("🤔 লিঙ্কটি সম্ভবত inválid বা মেয়াদোত্তীর্ণ।")
    else:
        reply_msg = await message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\nSend me a movie or series name to search.")
        asyncio.create_task(delete_messages_after_delay([message, reply_msg], 120))

def build_search_results_markup(results, query, current_page, total_count, add_request_button=False):
    buttons = [[InlineKeyboardButton(f"🎬 {movie['title']} {f'({movie['year']})' if movie.get('year') else ''}", callback_data=f"showqual_{movie['_id']}")] for movie in results]
    if total_count > SEARCH_PAGE_SIZE:
        nav_buttons = []
        total_pages = math.ceil(total_count / SEARCH_PAGE_SIZE)
        if current_page > 0: nav_buttons.append(InlineKeyboardButton("⬅️ আগের পাতা", callback_data=f"nav_{current_page-1}_{query}"))
        nav_buttons.append(InlineKeyboardButton(f"📄 {current_page+1}/{total_pages} 📄", callback_data="noop"))
        if (current_page + 1) * SEARCH_PAGE_SIZE < total_count: nav_buttons.append(InlineKeyboardButton("পরের পাতা ➡️", callback_data=f"nav_{current_page+1}_{query}"))
        buttons.append(nav_buttons)
    if add_request_button: buttons.append([InlineKeyboardButton(f"🙏 '{query[:20]}' এর জন্য অনুরোধ করুন", callback_data=f"reqmovie_{query}")])
    return InlineKeyboardMarkup(buttons)

@app.on_callback_query()
async def callback_handler(client, callback_query):
    data, user_id = callback_query.data, callback_query.from_user.id
    if data == "noop": await callback_query.answer(); return
    if data == "cancel_delete": await callback_query.message.edit_text("🚫 ডিলিট অপারেশন বাতিল করা হয়েছে।"); await callback_query.answer(); return

    if data.startswith("showqual_"):
        movie_id = ObjectId(data.split("_", 1)[1])
        new_msg = await show_quality_options(callback_query.message, movie_id, is_edit=True, return_message=True)
        if new_msg: asyncio.create_task(delete_messages_after_delay([new_msg], DELETE_DELAY))
    elif data.startswith("getfile_"):
        file_id_str = data.split("_", 1)[1]
        encoded_data = base64.urlsafe_b64encode(f'file_{file_id_str}_{user_id}'.encode()).decode()
        await callback_query.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ ভেরিফাই করে ডাউনলোড করুন", url=f"{AD_PAGE_URL}?data={encoded_data}")]]))
    elif data.startswith("nav_"):
        try:
            _, page_str, query = data.split("_", 2)
            current_page, search_regex = int(page_str), re.compile('.*'.join(query.split()), re.IGNORECASE)
            total_count = await movie_info_db.count_documents({'title_lower': search_regex})
            results = await movie_info_db.find({'title_lower': search_regex}).skip(current_page * SEARCH_PAGE_SIZE).limit(SEARCH_PAGE_SIZE).to_list(length=SEARCH_PAGE_SIZE)
            if results:
                markup = build_search_results_markup(results, query, current_page, total_count, add_request_button=True)
                await callback_query.message.edit_text("🤔 আপনি কি এগুলোর মধ্যে কোনো একটি খুঁজছেন?", reply_markup=markup)
        except MessageNotModified: pass
        except Exception as e: LOGGER.error(f"Navigation callback error: {e}"); await callback_query.answer("কিছু একটা সমস্যা হয়েছে।", show_alert=True)
    elif data.startswith("reqmovie_"):
        query, user = data.split("_", 1)[1], callback_query.from_user
        admin_message = f"🙏 **নতুন মুভির অনুরোধ**\n\n👤 **ব্যবহারকারী:** {user.mention} (`{user.id}`)\n🎬 **অনুসন্ধান:** `{query}`"
        reply_button = InlineKeyboardMarkup([[InlineKeyboardButton("✍️ ইউজারকে রিপ্লাই দিন", callback_data=f"replyuser_{user.id}")]])
        try:
            await client.send_message(LOG_CHANNEL_ID, admin_message, reply_markup=reply_button)
            await callback_query.message.edit_text("✅ আপনার অনুরোধটি অ্যাডমিনদের কাছে পাঠানো হয়েছে। মুভিটি যুক্ত করা হলে আপনাকে জানানো হতে পারে।")
            LOGGER.info(f"Movie request for '{query}' from user {user.id} has been forwarded.")
        except Exception as e: LOGGER.error(f"Failed to send request to log channel: {e}"); await callback_query.answer("❌ অ্যাডমিনদের কাছে অনুরোধ পাঠাতে ব্যর্থ।", show_alert=True)
    elif data.startswith("replyuser_"):
        if user_id not in ADMIN_IDS: return await callback_query.answer("❌ এটি শুধুমাত্র অ্যাডমিনদের জন্য।", show_alert=True)
        target_user_id = data.split("_", 1)[1]
        await client.send_message(callback_query.message.chat.id, f"✍️ User ID `{target_user_id}` কে রিপ্লাই করতে আপনার মেসেজটি এখানে পাঠান:", reply_markup=ForceReply(selective=True))
        await callback_query.message.delete()
    elif data.startswith("confirmdel_"):
        if user_id not in ADMIN_IDS: return await callback_query.answer("❌ এটি শুধুমাত্র অ্যাডমিনদের জন্য।", show_alert=True)
        movie_id = ObjectId(data.split("_", 1)[1])
        movie_doc = await movie_info_db.find_one_and_delete({"_id": movie_id})
        if not movie_doc: return await callback_query.message.edit_text("❌ এই মুভিটি ইতোমধ্যে ডিলিট করা হয়ে গেছে।")
        files_deleted = await files_db.delete_many({"movie_id": movie_id})
        LOGGER.info(f"ADMIN DELETE: User {user_id} deleted movie '{movie_doc['title']}'. {files_deleted.deleted_count} files removed.")
        await callback_query.message.edit_text(f"✅ **'*{movie_doc['title']}*'** এবং এর সাথে যুক্ত সমস্ত ফাইল সফলভাবে ডিলিট করা হয়েছে।")
    elif data == "delall_confirm_yes":
        if user_id not in ADMIN_IDS: return await callback_query.answer("❌ এটি শুধুমাত্র অ্যাডমিনদের জন্য।", show_alert=True)
        await callback_query.message.edit_text("⏳ সব মুভি এবং ফাইল ডিলিট করা হচ্ছে...")
        movies_deleted, files_deleted = await movie_info_db.delete_many({}), await files_db.delete_many({})
        LOGGER.warning(f"CRITICAL: User {user_id} deleted ALL data. {movies_deleted.deleted_count} movies, {files_deleted.deleted_count} files removed.")
        await callback_query.message.edit_text(f"✅ **সম্পন্ন!**\n\n- মোট মুভি ডিলিট: `{movies_deleted.deleted_count}`\n- মোট ফাইল ডিলিট: `{files_deleted.deleted_count}`")
    await callback_query.answer()

async def show_quality_options(message, movie_id, is_edit=False, return_message=False):
    try:
        files = await files_db.find({"movie_id": movie_id}).sort("quality").to_list(length=None)
        movie = await movie_info_db.find_one({"_id": movie_id})
        if not movie: text = "দুঃখিত, মুভির বিস্তারিত তথ্য পাওয়া যায়নি।"
        elif not files: text = "দুঃখিত, এই মুভির জন্য কোনো ফাইল পাওয়া যায়নি।"
        else:
            text = f"🎬 **{movie['title']} {f'({movie['year']})' if movie.get('year') else ''}**\n\n👇 আপনার পছন্দের কোয়ালিটি বেছে নিন:"
            buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"getfile_{f['_id']}")] for f in files]
            markup = InlineKeyboardMarkup(buttons)
            if is_edit: await message.edit_text(text, reply_markup=markup); return message if return_message else None
            else: return await message.reply_text(text, reply_markup=markup, quote=True) if return_message else None
        
        reply_msg = await message.edit_text(text) if is_edit else await message.reply_text(text)
        return reply_msg if return_message else None
    except MessageNotModified: return message if return_message else None
    except Exception as e: LOGGER.error(f"Show quality options error: {e}"); return None

async def find_suggestions(query, threshold=75, limit=3):
    try:
        all_movies = await movie_info_db.find({}, {"title": 1, "year": 1, "_id": 1}).to_list(length=None)
        if not all_movies: return []
        choices_map = {f"{doc['title']} ({doc.get('year', 'N/A')})": doc['_id'] for doc in all_movies}
        best_matches = process.extract(query, choices_map.keys(), limit=limit)
        suggestions = []
        for title_year, score in best_matches:
            if score >= threshold:
                movie_id = choices_map[title_year]
                for movie in all_movies:
                    if movie['_id'] == movie_id:
                        suggestions.append({"title": movie['title'], "year": movie.get('year'), "_id": movie_id}); break
        return suggestions
    except Exception as e: LOGGER.error(f"Error finding suggestions: {e}"); return []

# ========= 🔎 চূড়ান্ত Regex সার্চ হ্যান্ডলার ========= #
@app.on_message((filters.private | filters.group) & filters.text)
async def reliable_search_handler(client, message):
    if message.text and message.text.startswith('/'): return
    if message.from_user.is_bot: return

    query = message.text.strip()
    cleaned_query = ' '.join(re.findall(r'\b[a-zA-Z0-9]+\b', query.lower()))
    if not cleaned_query: return
    
    search_regex = re.compile('.*'.join(cleaned_query.split()), re.IGNORECASE)
    messages_to_delete, reply_msg = [message], None

    try:
        total_count = await movie_info_db.count_documents({'title_lower': search_regex})
        LOGGER.info(f"Search for '{cleaned_query}' in chat {message.chat.id} ({message.chat.type.name}) found {total_count} results.")
        
        if total_count == 0:
            if message.chat.type == ChatType.PRIVATE:
                suggestions = await find_suggestions(cleaned_query)
                if suggestions:
                    buttons = [[InlineKeyboardButton(f"🤔 {movie['title']} ({movie.get('year', '')})", callback_data=f"showqual_{movie['_id']}")] for movie in suggestions]
                    buttons.append([InlineKeyboardButton(f"🙏 '{query[:20]}' এর জন্য অনুরোধ করুন", callback_data=f"reqmovie_{query}")])
                    reply_msg = await message.reply_text("❌ আপনার সার্চের সাথে সরাসরি কোনো মুভি মেলেনি।\n\n**আপনি কি নিচের মুভিগুলোর কোনো একটি খুঁজছিলেন?**\n\nযদি আপনার কাঙ্ক্ষিত মুভি এখানে না থাকে, তাহলে অনুরোধ বাটনে ক্লিক করুন।", reply_markup=InlineKeyboardMarkup(buttons), quote=True)
                else:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"🙏 '{query[:20]}' এর জন্য অনুরোধ করুন", callback_data=f"reqmovie_{query}")]])
                    reply_msg = await message.reply_text("❌ **মুভিটি খুঁজে পাওয়া যায়নি!**\n\nআপনি চাইলে নিচের বাটনে ক্লিক করে মুভিটির জন্য অ্যাডমিনদের কাছে অনুরোধ করতে পারেন।", reply_markup=markup, quote=True)
                if reply_msg: messages_to_delete.append(reply_msg)
        elif total_count == 1:
            movie = await movie_info_db.find_one({'title_lower': search_regex})
            reply_msg = await show_quality_options(message, movie['_id'], return_message=True)
            if reply_msg: messages_to_delete.append(reply_msg)
        else:
            results = await movie_info_db.find({'title_lower': search_regex}).limit(SEARCH_PAGE_SIZE).to_list(length=SEARCH_PAGE_SIZE)
            markup = build_search_results_markup(results, cleaned_query, 0, total_count, add_request_button=True)
            reply_msg = await message.reply_text("🤔 আপনি কি এগুলোর মধ্যে কোনো একটি খুঁজছেন? যদি আপনার কাঙ্ক্ষিত মুভিটি এখানে না থাকে, তাহলে নিচের অনুরোধ বাটনে ক্লিক করুন।", reply_markup=markup, quote=True)
            messages_to_delete.append(reply_msg)
    except Exception as e:
        LOGGER.error(f"Database search error: {e}")
        if message.chat.type == ChatType.PRIVATE:
            reply_msg = await message.reply_text("⚠️ বট একটি ডাটাবেস সমস্যার সম্মুখীন হয়েছে।")
            messages_to_delete.append(reply_msg)
    finally:
        if messages_to_delete: asyncio.create_task(delete_messages_after_delay(messages_to_delete, DELETE_DELAY))

# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা ========= #
def run_web_server():
    web_app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    LOGGER.info("Starting web server on a separate thread...")
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    LOGGER.info("The Don is waking up... (v5.0 Smart Suggestion Update)")
    app.run()
    LOGGER.info("The Don is resting...")
