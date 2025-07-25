# =====================================================================================
# ||                  GODFATHER MOVIE BOT (Final Stable Fixed Version)              ||
# =====================================================================================

import os, re, base64, logging, asyncio
from dotenv import load_dotenv
from threading import Thread
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from pymongo import MongoClient
from bson.objectid import ObjectId

# --- লোড কনফিগ ---
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
except Exception as e:
    LOGGER.critical(f"Configuration error: {e}"); exit()

# --- ক্লায়েন্ট ও ডেটাবেজ ---
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["MovieDB"]
movie_info_db = db["movie_info"]
files_db = db["files"]
users_db = db["users"]
channels_db = db["channels"]

# --- Flask ওয়েব অ্যাপ ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Bot is alive!"

# === হেল্পার ===
def is_admin(user_id): return user_id in ADMIN_IDS

async def delete_messages_after_delay(messages, delay):
    await asyncio.sleep(delay)
    for msg in messages:
        try: await msg.delete()
        except Exception as e: LOGGER.warning(f"Delete failed: {e}")

# === ✅ Movie Save Handler ===
@app.on_message(filters.channel & (filters.video | filters.document))
async def save_movie_quality(client, message):
    if not channels_db.find_one({"_id": message.chat.id}): return
    caption = message.caption or ""
    match = re.search(r"(.+?)\s*\(?(\d{4})\)?", caption)
    if not match: LOGGER.warning(f"Can't parse title from {message.id}"); return
    title, year = re.sub(r'[\._]', ' ', match.group(1).strip()), match.group(2)
    search_title = f"{title.lower()} {year}"
    quality = next((q for q in ["480p", "720p", "1080p", "2160p", "4k"] if q in caption.lower()), "Unknown")
    language = next((l for l in ["Hindi", "Bangla", "English", "Tamil", "Telugu"] if l.lower() in caption.lower()), "Unknown")

    movie_doc = movie_info_db.find_one_and_update(
        {"search_title": search_title},
        {"$setOnInsert": {"title": title, "year": year, "search_title": search_title}},
        upsert=True, return_document=True
    )
    files_db.update_one(
        {"movie_id": movie_doc["_id"], "quality": quality, "language": language},
        {"$set": {"file_id": message.video.file_id if message.video else message.document.file_id, "chat_id": message.chat.id, "msg_id": message.id}},
        upsert=True
    )
    LOGGER.info(f"✅ Saved: {title} ({year}) [{quality} - {language}]")

# === ✅ Start Command ===
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    users_db.update_one({"_id": user_id}, {"$set": {"name": message.from_user.first_name}}, upsert=True)

    if len(message.command) > 1:
        try:
            payload = message.command[1]
            decoded = base64.urlsafe_b64decode(payload).decode()
            action, file_id, uid = decoded.split("_")
            if int(uid) != user_id: return await message.reply("😡 Verification failed.")
            if action == "file":
                file_doc = files_db.find_one({"_id": ObjectId(file_id)})
                if not file_doc: return await message.reply("❌ File not found.")
                movie_doc = movie_info_db.find_one({"_id": file_doc["movie_id"]})
                caption = f"🎬 **{movie_doc['title']} ({movie_doc['year']})**\n✨ **Quality:** {file_doc['quality']}\n🌐 **Language:** {file_doc['language']}\n\n🙏 Thank you!"
                movie_msg = await client.copy_message(user_id, file_doc["chat_id"], file_doc["msg_id"], caption=caption)
                warn_msg = await message.reply(f"⏳ File will auto-delete in {DELETE_DELAY // 60} minutes.")
                asyncio.create_task(delete_messages_after_delay([movie_msg, warn_msg], DELETE_DELAY))
        except Exception as e:
            LOGGER.error(f"Deep link error: {e}")
            await message.reply("🤔 Invalid or expired link.")
    else:
        await message.reply(f"👋 Hello **{message.from_user.first_name}**! Search a movie by typing name...")

# === ✅ Admin Stats Command ===
@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats_command(client, message):
    await message.reply_text(
        f"📊 **Stats**\n\n👤 Users: `{users_db.count_documents({})}`\n"
        f"🎬 Movies: `{movie_info_db.count_documents({})}`\n📁 Files: `{files_db.count_documents({})}`"
    )

# === ✅ Callback Handler ===
@app.on_callback_query()
async def callback_handler(client, cq):
    data, user_id = cq.data, cq.from_user.id
    if data.startswith("showqual_"):
        movie_id = ObjectId(data.split("_")[1])
        await show_quality_options(cq.message, movie_id, is_edit=True)
    elif data.startswith("getfile_"):
        file_id = data.split("_")[1]
        encoded = base64.urlsafe_b64encode(f"file_{file_id}_{user_id}".encode()).decode()
        await cq.message.edit_reply_markup(InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Verify & Download", url=f"{AD_PAGE_URL}?data={encoded}")]]
        ))
    await cq.answer()

async def show_quality_options(message, movie_id, is_edit=False):
    movie = movie_info_db.find_one({"_id": movie_id})
    files = list(files_db.find({"movie_id": movie_id}))
    if not files: return await message.reply("❌ No files found.")
    buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"getfile_{f['_id']}")] for f in files]
    text = f"🎬 **{movie['title']} ({movie['year']})**\n\nSelect a quality:"
    try:
        if is_edit: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        else: await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e: LOGGER.error(f"Quality options error: {e}")

# === ✅ Smart Search ===
@app.on_message((filters.private | filters.group) & filters.text)
async def smart_search_handler(client, message):
    if message.from_user.is_bot: return
    query = message.text.strip()
    results = []

    try:
        results = list(movie_info_db.aggregate([
            {
                "$search": {
                    "index": "default",
                    "autocomplete": {
                        "query": query,
                        "path": "search_title",
                        "fuzzy": {"maxEdits": 2}
                    }
                }
            },
            {"$limit": 5}
        ]))
    except Exception as e:
        LOGGER.warning(f"$search failed: {e}")
        results = list(movie_info_db.find(
            {"search_title": {"$regex": re.escape(query), "$options": "i"}}
        ).limit(5))

    if not results:
        if message.chat.type == ChatType.PRIVATE:
            await message.reply_text("❌ **Movie not found!**")
        return

    if len(results) == 1 and results[0]["title"].lower() == query.lower():
        await show_quality_options(message, results[0]["_id"])
    else:
        buttons = [[InlineKeyboardButton(f"🎬 {m['title']} ({m['year']})", callback_data=f"showqual_{m['_id']}")] for m in results]
        await message.reply_text("🤔 Did you mean one of these?", reply_markup=InlineKeyboardMarkup(buttons))

# === ✅ বট চালু ও Flask চালু ===
def run_web(): web_app.run(host="0.0.0.0", port=PORT)
if __name__ == "__main__":
    Thread(target=run_web).start()
    LOGGER.info("Starting The Don..."); app.run()
