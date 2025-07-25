# =====================================================================================
# ||      GODFATHER MOVIE BOT (v5.2 - Final with User-Account Indexer)             ||
# ||---------------------------------------------------------------------------------||
# || নতুন ইনডেক্সিং সিস্টেম: ইউজার-অ্যাকাউন্ট ব্যবহার করে চ্যানেল হিস্টোরি ইনডেক্সিং। ||
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

# --- সেটআপ ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)

# --- এনভায়রনমেন্ট ভ্যারিয়েবল লোড এবং ভ্যালিডেশন ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    MONGO_URL = os.environ.get("MONGO_URL")
    AD_PAGE_URL = os.environ.get("AD_PAGE_URL")
    ADMIN_IDS = [int(i) for i in os.environ.get("ADMIN_IDS", "").split(",") if i.strip()]
    PORT = int(os.environ.get("PORT", 8080))
    DELETE_DELAY = 15 * 60
    FILE_CHANNEL_ID = int(os.environ.get("FILE_CHANNEL_ID", "0"))
    
    # ইনডেক্সিং এর জন্য ইউজার সেশন স্ট্রিং
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING")

except Exception as e:
    LOGGER.critical(f"Env config error: {e}")
    exit()

if FILE_CHANNEL_ID == 0:
    LOGGER.critical("FILE_CHANNEL_ID missing in .env. Auto-indexing will not work.")
    exit()
if not USER_SESSION_STRING:
    LOGGER.warning("USER_SESSION_STRING missing in .env. Forward-based indexing will be disabled.")

# --- ক্লায়েন্ট এবং ডাটাবেস ইনিশিয়ালাইজেশন ---
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_client = Client("UserIndexer", session_string=USER_SESSION_STRING, api_id=API_ID, api_hash=API_HASH) if USER_SESSION_STRING else None

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["MovieDB"]
movie_info_db = db["movie_info"]
files_db = db["files"]
users_db = db["users"]

web_app = Flask(__name__)
@web_app.route('/')
def health(): return "Bot is alive!"

# --- হেল্পার ফাংশন ---
def is_admin(_, __, m): return m.from_user and m.from_user.id in ADMIN_IDS
admin_filter = filters.create(is_admin)

async def delete_messages_after_delay(msgs, delay):
    await asyncio.sleep(delay)
    for m in msgs:
        try: await m.delete()
        except: pass

async def index_file(message):
    try:
        if not (message.video or message.document): return False
        caption = message.caption or ""
        title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", caption)
        year = title_match.group(2) if title_match else None
        raw_title = title_match.group(1).strip() if title_match else ' '.join(
            w for w in caption.split() if not any(s in w.lower() for s in ['480p','720p','1080p','hindi','english','bangla','bengali','dual','audio','web-dl','hdrip','bluray','webrip'])
        ).strip()
        if not raw_title: return False

        clean_title = re.sub(r'[\.\_]', ' ', raw_title).strip()
        quality = next((q for q in ["480p", "720p", "1080p", "2160p", "4k"] if q in caption.lower()), "Unknown")
        language = next((l.capitalize() for l in ["hindi","bangla","bengali","english","tamil","telugu","malayalam","kannada"] if l in caption.lower()), "Unknown")
        if language.lower() in ["bangla", "bengali"]: language = "Bangla"

        query = {"title_lower": clean_title.lower()}
        if year: query["year"] = year
        movie_doc = await movie_info_db.find_one_and_update(
            query, {"$setOnInsert": {"title": clean_title, "year": year, "title_lower": clean_title.lower()}},
            upsert=True, return_document=True
        )

        file_info = message.video or message.document
        await files_db.update_one(
            {"movie_id": movie_doc['_id'], "quality": quality, "language": language},
            {"$set": {"file_id": file_info.file_id, "chat_id": message.chat.id, "msg_id": message.id}},
            upsert=True
        )
        return True
    except Exception as e:
        LOGGER.error(f"Index error on message {message.id}: {e}")
        return False

# --- পাইরোগ্রাম হ্যান্ডলার ---

# ফাইল চ্যানেলে নতুন ফাইল এলে অটো-ইনডেক্স
@app.on_message(filters.channel & (filters.video | filters.document))
async def auto_index_handler(client, message):
    if message.chat.id == FILE_CHANNEL_ID:
        if await index_file(message):
            LOGGER.info(f"✅ Auto-Indexed: {message.caption.splitlines()[0] if message.caption else 'No Caption'}")

# অ্যাডমিন কমান্ড
@app.on_message(filters.command("stats") & admin_filter)
async def stats_command(client, message):
    total_users, total_movies, total_files = await asyncio.gather(
        users_db.count_documents({}), movie_info_db.count_documents({}), files_db.count_documents({})
    )
    await message.reply_text(
        f"📊 **Bot Stats**\n👥 ইউজার: `{total_users}`\n🎬 মুভি: `{total_movies}`\n📁 ফাইল: `{total_files}`\n📢 ফাইল চ্যানেল: `{FILE_CHANNEL_ID}`"
    )

# ফরওয়ার্ড-বেইজড ইনডেক্সিং
pending_index_requests = {}

@app.on_message(filters.command("index") & admin_filter)
async def request_index_channel(client, message):
    if not user_client:
        return await message.reply_text("❌ `USER_SESSION_STRING` সেট করা নেই। ইনডেক্সিং সম্ভব নয়।")
    pending_index_requests[message.from_user.id] = True
    await message.reply_text("📩 ইনডেক্স করার জন্য যেকোনো চ্যানেল থেকে একটি ফাইল এখানে ফরওয়ার্ড করুন।")

@app.on_message(filters.forwarded & (filters.video | filters.document) & admin_filter)
async def handle_forwarded_file_for_indexing(client, message):
    uid = message.from_user.id
    if uid not in pending_index_requests: return
    del pending_index_requests[uid]

    if not message.forward_from_chat:
        return await message.reply_text("❌ ফরওয়ার্ডটি কোনো চ্যানেল থেকে আসেনি। আবার চেষ্টা করুন।")

    channel_id = message.forward_from_chat.id
    msg = await message.reply_text(f"⏳ চ্যানেল `{channel_id}` থেকে ইনডেক্সিং শুরু হচ্ছে...")

    total, success = 0, 0
    try:
        # ইউজার ক্লায়েন্ট দিয়ে চ্যানেল হিস্টোরি পড়া হচ্ছে
        async for m in user_client.get_chat_history(channel_id):
            total += 1
            if m.video or m.document:
                if await index_file(m):
                    success += 1
            if total % 200 == 0:
                try:
                    await msg.edit_text(f"🔄 চলমান...\nস্ক্যান করা হয়েছে: `{total}` টি মেসেজ\nসফলভাবে ইনডেক্স হয়েছে: `{success}` টি ফাইল")
                except MessageNotModified: pass
        await msg.edit_text(f"✅ ইনডেক্সিং সম্পন্ন!\n\nমোট স্ক্যান: `{total}`\nসফল ইনডেক্স: `{success}`")
    except Exception as e:
        LOGGER.error(f"Indexing failed for channel {channel_id}: {e}")
        await msg.edit_text(f"⚠️ ইনডেক্সিং করার সময় একটি সমস্যা হয়েছে:\n`{e}`\n\n✅ নিশ্চিত করুন আপনার পার্সোনাল অ্যাকাউন্ট (`USER_SESSION_STRING` যার) সেই চ্যানেলের একজন সদস্য।")

# ইউজার ইন্টার‍্যাকশন
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    await users_db.update_one({"_id": user_id}, {"$set": {"name": message.from_user.first_name}}, upsert=True)

    if len(message.command) > 1:
        try:
            payload = message.command[1]
            decoded = base64.urlsafe_b64decode(payload).decode()
            action, data_id, uid = decoded.split('_')
            if user_id != int(uid): return await message.reply_text("😡 এই লিঙ্কটি আপনার জন্য নয়।")
            if action == "file":
                file_doc = await files_db.find_one({"_id": ObjectId(data_id)})
                movie_doc = await movie_info_db.find_one({"_id": file_doc['movie_id']})
                caption = f"🎬 **{movie_doc['title']} ({movie_doc.get('year', '')})**\n✨ **Quality:** {file_doc['quality']}\n🌐 **Language:** {file_doc['language']}\n\n🙏 ধন্যবাদ!"
                movie_msg = await client.copy_message(user_id, file_doc['chat_id'], file_doc['msg_id'], caption=caption)
                warn = await message.reply_text(f"⚠️ ফাইলটি {DELETE_DELAY//60} মিনিট পর স্বয়ংক্রিয়ভাবে ডিলিট হয়ে যাবে।")
                asyncio.create_task(delete_messages_after_delay([movie_msg, warn], DELETE_DELAY))
        except Exception as e:
            LOGGER.error(f"Deep link error: {e}")
            await message.reply_text("🤔 লিঙ্কটি অবৈধ অথবা এর মেয়াদ শেষ হয়ে গেছে।")
    else:
        msg = await message.reply_text(f"👋 হাই **{message.from_user.first_name}**!\nসার্চ করার জন্য একটি মুভির নাম লিখুন।")
        asyncio.create_task(delete_messages_after_delay([message, msg], 120))

@app.on_callback_query()
async def callback_handler(client, cb):
    data, uid = cb.data, cb.from_user.id
    if data.startswith("showqual_"):
        movie_id = ObjectId(data.split("_")[1])
        msg = await show_quality_options(cb.message, movie_id, is_edit=True, return_message=True)
        if msg: asyncio.create_task(delete_messages_after_delay([msg], DELETE_DELAY))
    elif data.startswith("getfile_"):
        fid = data.split("_", 1)[1]
        encoded = base64.urlsafe_b64encode(f"file_{fid}_{uid}".encode()).decode()
        url = f"{AD_PAGE_URL}?data={encoded}"
        await cb.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ ভেরিফাই করে ডাউনলোড করুন", url=url)]]))
    await cb.answer()

async def show_quality_options(msg, movie_id, is_edit=False, return_message=False):
    try:
        files = await files_db.find({"movie_id": movie_id}).sort("quality").to_list(length=None)
        if not files:
            txt = "দুঃখিত, এই মুভির কোনো ফাইল খুঁজে পাওয়া যায়নি।"
            reply = await msg.edit_text(txt) if is_edit else await msg.reply_text(txt, quote=True)
            return reply if return_message else None

        movie = await movie_info_db.find_one({"_id": movie_id})
        title = movie['title']
        year = f"({movie['year']})" if movie.get('year') else ""
        text = f"🎬 **{title} {year}**\n\n👇 পছন্দের কোয়ালিটি বেছে নিন:"
        buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"getfile_{f['_id']}")] for f in files]
        if is_edit:
            await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            return msg if return_message else None
        else:
            return await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    except MessageNotModified:
        return msg if return_message else None
    except Exception as e:
        LOGGER.error(f"show_quality_options error: {e}")
        return None

@app.on_message((filters.private | filters.group) & filters.text & ~filters.command(["start", "stats", "index"]))
async def search_handler(client, msg):
    if not msg.text or (msg.from_user and msg.from_user.is_bot): return
    query = msg.text.strip()
    cleaned = ' '.join(re.findall(r'\b[a-zA-Z0-9]+\b', query.lower()))
    if not cleaned: return

    regex = re.compile('.*'.join(cleaned.split()), re.IGNORECASE)
    to_delete = [msg]
    reply = None
    try:
        results = await movie_info_db.find({'title_lower': regex}).limit(10).to_list(length=10)
    except Exception as e:
        LOGGER.error(f"Search error: {e}")
        if msg.chat.type == ChatType.PRIVATE:
            reply = await msg.reply_text("⚠️ ডাটাবেস সংযোগে সমস্যা হয়েছে।")
            to_delete.append(reply)
        asyncio.create_task(delete_messages_after_delay(to_delete, 60))
        return

    if not results:
        if msg.chat.type == ChatType.PRIVATE:
            reply = await msg.reply_text("❌ দুঃখিত, আপনার সার্চের সাথে মিলে এমন কিছু পাওয়া যায়নি।", quote=True)
    elif len(results) == 1:
        reply = await show_quality_options(msg, results[0]['_id'], return_message=True)
    else:
        buttons = [[InlineKeyboardButton(f"🎬 {m['title']} ({m.get('year', '')})", callback_data=f"showqual_{m['_id']}")] for m in results]
        reply = await msg.reply_text("🤔 আপনি কি নিচের কোনো একটি খুঁজছেন?", reply_markup=InlineKeyboardMarkup(buttons), quote=True)

    if reply: to_delete.append(reply)
    asyncio.create_task(delete_messages_after_delay(to_delete, DELETE_DELAY))

# --- বট চালু করা ---
async def main():
    if user_client:
        await user_client.start()
        LOGGER.info("User-Indexer Client Started.")
    
    await app.start()
    LOGGER.info("Bot Client Started.")
    
    LOGGER.info("✅ GODFATHER BOT IS NOW ONLINE (v5.2)")
    await asyncio.Future() # প্রোগ্রামকে চলমান রাখে

def run_web():
    web_app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    Thread(target=run_web).start()
    asyncio.run(main())
