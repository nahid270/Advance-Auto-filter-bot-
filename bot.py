# =====================================================================================
# ||                  GODFATHER MOVIE BOT (Advanced Features Version)                ||
# ||---------------------------------------------------------------------------------||
# || গ্রুপ সাপোর্ট, অটো-ডিলিট এবং উন্নত ক্যাপশন সহ চূড়ান্ত সংস্করণ।                     ||
# =====================================================================================

import os
import re
import base64
import logging
import asyncio # অটো-ডিলিটের জন্য asyncio ইম্পোর্ট করা হয়েছে
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
    DELETE_DELAY = 15 * 60 # ১৫ মিনিট (সেকেন্ডে)
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

async def delete_messages_after_delay(messages_to_delete, delay):
    """নির্দিষ্ট সময় পর মেসেজগুলো ডিলিট করার জন্য একটি হেল্পার ফাংশন।"""
    await asyncio.sleep(delay)
    for msg in messages_to_delete:
        try:
            await msg.delete()
        except (MessageNotModified, MessageIdInvalid):
            LOGGER.warning(f"Message {msg.id} could not be deleted (might be already gone).")
        except Exception as e:
            LOGGER.error(f"Error deleting message {msg.id}: {e}")

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
                # উন্নত ক্যাপশন তৈরি
                final_caption = (
                    f"🎬 **{movie['title']} ({movie['year']})**\n"
                    f"🌐 **Language:** {movie['language']}\n\n"
                    f"🙏 Thank you for using our bot!"
                )
                
                # মুভি ফাইল পাঠানো
                movie_msg = await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=movie['chat_id'],
                    message_id=movie['msg_id'],
                    caption=final_caption
                )
                
                # সতর্কবার্তা পাঠানো
                warning_msg = await message.reply_text(
                    f"❗ **Important:** This file will be automatically deleted in **{DELETE_DELAY // 60} minutes** to save space.",
                    quote=True
                )
                
                # ব্যাকগ্রাউন্ডে ডিলিট টাস্ক চালু করা
                asyncio.create_task(delete_messages_after_delay([movie_msg, warning_msg], DELETE_DELAY))
            else:
                await message.reply_text("❌ Sorry, the movie could not be found. It might have been removed.")
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

# ... (অন্যান্য অ্যাডমিন কমান্ডগুলো এখানে async await সহ যোগ করতে পারেন)

# ========= 🔎 মুভি সার্চ (প্রাইভেট এবং গ্রুপ) ========= #
@app.on_message((filters.private | filters.group) & filters.text & ~filters.command())
async def search_movie(client, message):
    query = message.text.strip()
    result = movies.find_one({"title": {"$regex": query, "$options": "i"}})
    
    if result:
        movie_id = str(result['_id'])
        user_id = message.from_user.id
        encoded_data = base64.urlsafe_b64encode(f'{movie_id}-{user_id}'.encode()).decode()
        verification_url = f"{AD_PAGE_URL}?data={encoded_data}"
        
        # বাটনের লেখা পরিবর্তন করা হয়েছে
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ডাউনলোড নাও", url=verification_url)]])
        
        await message.reply_text(
            f"🎬 **{result['title']} ({result['year']})**\n"
            f"🌐 **Language:** {result['language']}\n\n"
            "➡️ মুভিটি পেতে নিচের বাটনে ক্লিক করে ভেরিফাই করুন।",
            reply_markup=btn,
            disable_web_page_preview=True,
            quote=True
        )
    # গ্রুপে মুভি না পাওয়া গেলে কোনো রিপ্লাই দেবে না, শুধু প্রাইভেট চ্যাটে দেবে
    elif message.chat.type == filters.ChatType.PRIVATE:
        await message.reply_text("❌ **Movie Not Found!**\n\nPlease check the spelling or try another name.")

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
