# =====================================================================================
# ||                  GODFATHER MOVIE BOT (Smart Search & Suggestions)               ||
# ||---------------------------------------------------------------------------------||
# || স্মার্ট সার্চ, সাজেশন সিস্টেম, গ্রুপ সাপোর্ট, অটো-ডিলিট সহ চূড়ান্ত সংস্করণ।      ||
# =====================================================================================

import os
import re
import base64
import logging
import asyncio
from dotenv import load_dotenv
from threading import Thread

# --- ওয়েব সার্ভার ও বট লাইব্রেরি ---
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified, MessageIdInvalid
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
    BOT_USERNAME = os.environ.get("BOT_USERNAME")
    DELETE_DELAY = 15 * 60
except (ValueError, TypeError) as e:
    LOGGER.critical(f"Configuration error: {e}")
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
def health_check(): return "Bot is alive!"

# ========= 📄 হেল্পার ফাংশন ========= #
def is_admin(user_id): return user_id in ADMIN_IDS

async def delete_messages_after_delay(messages, delay):
    await asyncio.sleep(delay)
    for msg in messages:
        try: await msg.delete()
        except Exception as e: LOGGER.warning(f"Could not delete message {msg.id}: {e}")

# ... (save_movie, start_handler, এবং অ্যাডমিন কমান্ডের কোড অপরিবর্তিত থাকবে) ...
# ========= 📢 চ্যানেল থেকে স্বয়ংক্রিয় মুভি সেভ ========= #
@app.on_message(filters.channel & (filters.video | filters.document))
async def save_movie(client, message):
    if not channels.find_one({"_id": message.chat.id}): return
    text_to_parse = message.caption or ""
    title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", text_to_parse)
    if not title_match:
        LOGGER.warning(f"Could not parse title from message {message.id} in channel {message.chat.id}")
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
        LOGGER.info(f"✅ Movie Saved: {title} ({year}) from channel {message.chat.id}")

# ========= 🎬 স্টার্ট কমান্ড এবং ভেরিফিকেশন হ্যান্ডলার ========= #
@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
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
                return await message.reply_text("😡 **Verification Failed!** This link was not generated for you.")

            movie = movies.find_one({"_id": ObjectId(movie_id_str)})
            if movie:
                final_caption = (f"🎬 **{movie['title']} ({movie['year']})**\n"
                                 f"🌐 **Language:** {movie['language']}\n\n"
                                 f"🙏 Thank you for using our bot!")
                movie_msg = await client.copy_message(chat_id=user_id, from_chat_id=movie['chat_id'], message_id=movie['msg_id'], caption=final_caption)
                warning_msg = await message.reply_text(f"❗ **Important:** This file will be automatically deleted in **{DELETE_DELAY // 60} minutes**.", quote=True)
                asyncio.create_task(delete_messages_after_delay([movie_msg, warning_msg], DELETE_DELAY))
            else:
                await message.reply_text("❌ Sorry, the movie could not be found.")
        except Exception as e:
            LOGGER.error(f"Deep link error for user {user_id}: {e}")
            await message.reply_text("🤔 Invalid or expired verification link.")
    else:
        await message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\n\nI am a movie search bot. Just send me the name of the movie you want to find.")

# ========= 🛠️ অ্যাডমিন কমান্ডস ========= #
@app.on_message(filters.command("stats") & filters.create(lambda _, __, m: is_admin(m.from_user.id)))
async def stats_command(_, message):
    total_users = users.count_documents({})
    total_movies = movies.count_documents({})
    total_channels = channels.count_documents({})
    await message.reply_text(f"📊 **Bot Statistics**\n\n👥 Total Users: `{total_users}`\n🎬 Total Movies: `{total_movies}`\n📢 Authorized Channels: `{total_channels}`")

# ... (অন্যান্য অ্যাডমিন কমান্ডগুলো অপরিবর্তিত) ...


# ========= 🔎 স্মার্ট সার্চ এবং সাজেশন সিস্টেম (সম্পূর্ণ নতুন) ========= #
@app.on_message((filters.private | filters.group) & filters.text & ~filters.command())
async def smart_search_movie(client, message):
    query = message.text.strip()
    
    # Atlas Search ব্যবহার করে কোয়েরি চালানো
    pipeline = [
        {
            '$search': {
                'index': 'default', # আমরা যে ইনডেক্সটি তৈরি করেছি
                'autocomplete': {
                    'query': query,
                    'path': 'title',
                    'fuzzy': { 'maxEdits': 2, 'prefixLength': 3 }
                }
            }
        },
        { '$limit': 5 } # সর্বোচ্চ ৫টি সাজেশন দেখানো হবে
    ]
    results = list(movies.aggregate(pipeline))

    if not results:
        if message.chat.type == filters.ChatType.PRIVATE:
            await message.reply_text("❌ **Movie Not Found!**\n\nPlease check your spelling or try a different name.")
        return

    # যদি একটি মাত্র ফলাফল পাওয়া যায় এবং সেটি হুবহু মিলে যায়
    if len(results) == 1 and results[0]['title'].lower() == query.lower():
        movie = results[0]
        movie_id = str(movie['_id'])
        user_id = message.from_user.id
        encoded_data = base64.urlsafe_b64encode(f'get_{movie_id}-{user_id}'.encode()).decode()
        # এখানে 'get_' প্রিফিক্স ব্যবহার করা হয়েছে যাতে সাধারণ স্টার্ট কমান্ডের সাথে কনফ্লিক্ট না হয়
        verification_url = f"https://t.me/{BOT_USERNAME}?start={encoded_data}"
        
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ডাউনলোড নাও", url=verification_url)]])
        await message.reply_text(
            f"🎬 **{movie['title']} ({movie['year']})**\n"
            f"🌐 **Language:** {movie['language']}\n\n"
            "➡️ মুভিটি পেতে নিচের বাটনে ক্লিক করুন।",
            reply_markup=btn,
            disable_web_page_preview=True,
            quote=True
        )
    else:
        # একাধিক ফলাফল বা ভুল বানানের জন্য সাজেশন দেখানো
        buttons = []
        for movie in results:
            movie_id = str(movie['_id'])
            # কলব্যাক ডেটায় মুভির আইডি পাঠানো হচ্ছে
            buttons.append([InlineKeyboardButton(f"🎬 {movie['title']} ({movie['year']})", callback_data=f"suggest_{movie_id}")])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_text("🤔 Did you mean one of these?", reply_markup=reply_markup, quote=True)

# ========= 👆 সাজেশন বাটনের জন্য কলব্যাক হ্যান্ডলার (নতুন) ========= #
@app.on_callback_query(filters.regex(r"^suggest_"))
async def suggestion_callback(client, callback_query):
    movie_id = callback_query.data.split("_")[1]
    movie = movies.find_one({"_id": ObjectId(movie_id)})

    if not movie:
        await callback_query.answer("Sorry, this movie is no longer available.", show_alert=True)
        return

    # আগের মেসেজটি এডিট করে ডাউনলোড বাটন দেখানো হচ্ছে
    user_id = callback_query.from_user.id
    encoded_data = base64.urlsafe_b64encode(f'get_{movie_id}-{user_id}'.encode()).decode()
    verification_url = f"https://t.me/{BOT_USERNAME}?start={encoded_data}"
    
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ডাউনলোড নাও", url=verification_url)]])
    await callback_query.message.edit_text(
        f"🎬 **{movie['title']} ({movie['year']})**\n"
        f"🌐 **Language:** {movie['language']}\n\n"
        "➡️ মুভিটি পেতে নিচের বাটনে ক্লিক করুন।",
        reply_markup=btn,
        disable_web_page_preview=True
    )
    await callback_query.answer()


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
