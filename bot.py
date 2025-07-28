# =====================================================================================
# ||      GODFATHER MOVIE BOT (v5.1 - Final Hotfix Edition)                        ||
# ||---------------------------------------------------------------------------------||
# || এই সংস্করণে Pyrogram ফিল্টার সম্পর্কিত TypeError এরর সমাধান করা হয়েছে।         ||
# || ৩টি বিজ্ঞাপন স্লট সহ একটি শক্তিশালী অ্যাডমিন প্যানেল রয়েছে।                      ||
# || Secret Key ও ডিফল্ট অ্যাড কোড বট স্বয়ংক্রিয়ভাবে পরিচালনা করে।                   ||
# =====================================================================================

import os
import re
import math
import base64
import logging
import asyncio
import secrets
from dotenv import load_dotenv
from threading import Thread
from flask import Flask, request, render_template_string, session, redirect, url_for, flash
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType
from pyrogram.errors import MessageNotModified
from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId

# --- পরিবেশ সেটআপ ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger(__name__)

# --- কনফিগারেশন লোড ---
try:
    API_ID = int(os.environ.get("API_ID"))
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    MONGO_URL = os.environ.get("MONGO_URL")
    BOT_PUBLIC_URL = os.environ.get("BOT_PUBLIC_URL")
    BOT_USERNAME = os.environ.get("BOT_USERNAME")
    FILE_CHANNEL_ID = int(os.environ.get("FILE_CHANNEL_ID"))
    ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(',') if id.strip()]
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
    PORT = int(os.environ.get("PORT", 8080))
    DELETE_DELAY = 15 * 60
    SEARCH_PAGE_SIZE = 8
except (ValueError, TypeError, AttributeError) as e:
    LOGGER.critical(f"Configuration error in environment variables: {e}")
    exit()

if not all([BOT_PUBLIC_URL, BOT_USERNAME, ADMIN_PASSWORD, FILE_CHANNEL_ID]):
    LOGGER.critical("CRITICAL: Ensure required environment variables are set.")
    exit()

# --- ক্লায়েন্ট, ডাটাবেস ও ওয়েব অ্যাপ ---
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["MovieDB_v5"]
movie_info_db, files_db, users_db, settings_db = db["movie_info"], db["files"], db["users"], db["settings"]
web_app = Flask(__name__)

# ===================================================================
# ||          WEB APP (Verification & Multi-Ad Admin Panel)        ||
# ===================================================================

async def get_all_ad_codes():
    ad_codes = {}
    default_text = "<p>এই বিজ্ঞাপন স্লটটি অ্যাডমিন প্যানেল থেকে সেট করুন।</p>"
    for i in range(1, 4):
        slot_id = f"ad_slot_{i}"
        ad_doc = await settings_db.find_one({"_id": slot_id})
        ad_codes[slot_id] = ad_doc['value'] if ad_doc else default_text
    return ad_codes

async def update_ad_codes(form_data):
    for i in range(1, 4):
        slot_id = f"ad_slot_{i}"
        await settings_db.update_one({"_id": slot_id}, {"$set": {"value": form_data.get(slot_id, "")}}, upsert=True)

async def initialize_app_secrets():
    secret_doc = await settings_db.find_one({"_id": "flask_secret_key"})
    if secret_doc:
        web_app.secret_key = secret_doc['value']
    else:
        new_secret = secrets.token_hex(24)
        await settings_db.insert_one({"_id": "flask_secret_key", "value": new_secret})
        web_app.secret_key = new_secret
    LOGGER.info("Flask Secret Key initialized successfully.")

# --- HTML Templates ---
VERIFY_PAGE_TEMPLATE = """<!DOCTYPE html><html lang="bn"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Verification Required</title><style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;display:flex;flex-direction:column;align-items:center;background-color:#f0f2f5;margin:0;padding:20px;box-sizing:border-box}h1,p{text-align:center}.ad-container-top{width:100%;margin-bottom:20px;text-align:center}.container{background:white;padding:20px 40px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.1);max-width:500px;width:100%;text-align:center}h1{color:#1c1e21}p{color:#606770}.timer{font-size:2em;font-weight:700;color:#007bff;margin:20px 0}.button{background-color:#ccc;color:#fff;padding:15px 30px;border:none;border-radius:8px;font-size:1.1em;cursor:not-allowed;text-decoration:none;display:inline-block}.button.enabled{background-color:#28a745;cursor:pointer}.ad-container-bottom{width:100%;margin-top:20px;text-align:center}</style></head><body><div class="ad-container-top">{{ ad_slot_1|safe }}</div><div class="container"><h1>অনুগ্রহ করে যাচাই করুন</h1><p>আপনার ফাইলটি কিছুক্ষণের মধ্যেই প্রস্তুত হয়ে যাবে।</p><div class="ad-container-middle">{{ ad_slot_2|safe }}</div><p>টাইমার শেষ হওয়ার জন্য অপেক্ষা করুন।</p><div id="timer" class="timer">10</div><a id="download-btn" href="#" class="button">লিঙ্ক তৈরি হচ্ছে...</a></div><div class="ad-container-bottom">{{ ad_slot_3|safe }}</div><script>const timerElement=document.getElementById("timer"),downloadBtn=document.getElementById("download-btn"),encodedData="{{ encoded_data }}",botUsername="{{ bot_username }}";let countdown=10;const interval=setInterval(()=>{countdown--,timerElement.textContent=countdown,countdown<=0&&(clearInterval(interval),timerElement.style.display="none",downloadBtn.href=`https://t.me/${botUsername}?start=${encodedData}`,downloadBtn.textContent="ফাইল পেতে এখানে ক্লিক করুন",downloadBtn.classList.add("enabled"))},1e3)</script></body></html>"""
ADMIN_PANEL_TEMPLATE = """<!DOCTYPE html><html lang="bn"><head><meta charset="UTF-8"><title>অ্যাডমিন প্যানেল</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>body{font-family:sans-serif;background:#f4f4f4;margin:20px}h1,h2{text-align:center;color:#333}.container{max-width:900px;margin:auto;background:white;padding:20px;border-radius:8px;box-shadow:0 0 10px rgba(0,0,0,.1)}.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:15px;text-align:center;margin-bottom:30px}.stat-box{background:#e9ecef;padding:20px;border-radius:5px}.stat-box h3{margin:0 0 10px}.ad-form-grid{display:grid;grid-template-columns:1fr;gap:20px}label{font-weight:700;margin-bottom:5px;display:block}textarea{width:100%;height:150px;padding:10px;border:1px solid #ddd;border-radius:4px;box-sizing:border-box;font-family:monospace;font-size:14px}button{background:#007bff;color:#fff;padding:12px 20px;border:none;border-radius:4px;cursor:pointer;width:100%;font-size:16px;margin-top:10px}button:hover{background:#0056b3}.logout,h1{margin-bottom:20px}.logout{text-align:right}.message{padding:15px;margin-bottom:20px;border-radius:4px;text-align:center}.success{background:#d4edda;color:#155724}.error{background:#f8d7da;color:#721c24}</style></head><body><div class="container">{% if session.get('logged_in') %}<div class="logout"><a href="{{ url_for('logout') }}">লগআউট</a></div><h1>গডফাদার বট - অ্যাডমিন প্যানেল</h1>{% with messages=get_flashed_messages(with_categories=true) %}{% if messages %}{% for category,message in messages %}<div class="message {{ category }}">{{ message }}</div>{% endfor %}{% endif %}{% endwith %}<h2>বটের পরিসংখ্যান</h2><div class="stats-grid"><div class="stat-box"><h3>মোট ব্যবহারকারী</h3><p>{{ stats.users }}</p></div><div class="stat-box"><h3>মোট মুভি</h3><p>{{ stats.movies }}</p></div><div class="stat-box"><h3>মোট ফাইল</h3><p>{{ stats.files }}</p></div></div><h2>বিজ্ঞাপন কোড আপডেট করুন</h2><form method="post" action="{{ url_for('admin_panel') }}"><div class="ad-form-grid"><div class="ad-slot"><label for="ad_slot_1">বিজ্ঞাপন স্লট ১ (পেজের উপরে)</label><textarea id="ad_slot_1" name="ad_slot_1">{{ ad_codes.ad_slot_1 }}</textarea></div><div class="ad-slot"><label for="ad_slot_2">বিজ্ঞাপন স্লট ২ (টাইমারের পাশে)</label><textarea id="ad_slot_2" name="ad_slot_2">{{ ad_codes.ad_slot_2 }}</textarea></div><div class="ad-slot"><label for="ad_slot_3">বিজ্ঞাপন স্লট ৩ (পেজের নিচে)</label><textarea id="ad_slot_3" name="ad_slot_3">{{ ad_codes.ad_slot_3 }}</textarea></div></div><button type="submit">সকল বিজ্ঞাপন সেভ করুন</button></form>{% else %}<h1>অ্যাডমিন লগইন</h1>{% if error %}<p class="message error">{{ error }}</p>{% endif %}<form method="post" action="{{ url_for('admin_panel') }}"><label for="password">পাসওয়ার্ড:</label><input type="password" id="password" name="password" required style="width:100%;padding:10px;margin-bottom:20px;border:1px solid #ddd;border-radius:4px;box-sizing:border-box"><button type="submit">লগইন</button></form>{% endif %}</div></body></html>"""

# --- Flask Routes ---
@web_app.route('/')
def health_check(): return "Bot is alive and running!"

@web_app.route('/verify')
async def verify_user():
    encoded_data = request.args.get('data')
    if not encoded_data: return "Error: No data provided.", 400
    ad_codes = await get_all_ad_codes()
    return render_template_string(VERIFY_PAGE_TEMPLATE, **ad_codes, encoded_data=encoded_data, bot_username=BOT_USERNAME)

@web_app.route('/admin', methods=['GET', 'POST'])
async def admin_panel():
    error = None
    if request.method == 'POST':
        if 'password' in request.form:
            if request.form['password'] == ADMIN_PASSWORD:
                session['logged_in'] = True
                return redirect(url_for('admin_panel'))
            else: error = 'ভুল পাসওয়ার্ড। আবার চেষ্টা করুন।'
        elif 'ad_slot_1' in request.form and session.get('logged_in'):
            await update_ad_codes(request.form)
            flash('বিজ্ঞাপন কোড সফলভাবে আপডেট করা হয়েছে!', 'success')
            return redirect(url_for('admin_panel'))
    
    if session.get('logged_in'):
        stats_task = asyncio.gather(users_db.count_documents({}), movie_info_db.count_documents({}), files_db.count_documents({}))
        ad_codes = await get_all_ad_codes()
        total_users, total_movies, total_files = await stats_task
        stats = {'users': total_users, 'movies': total_movies, 'files': total_files}
        return render_template_string(ADMIN_PANEL_TEMPLATE, stats=stats, ad_codes=ad_codes)
    
    return render_template_string(ADMIN_PANEL_TEMPLATE, error=error)

@web_app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('admin_panel'))

# ========= 📄 হেল্পার ও ইনডেক্সিং হ্যান্ডলার ========= #
def is_admin(_, __, message): return message.from_user and message.from_user.id in ADMIN_IDS
admin_filter = filters.create(is_admin)

async def delete_messages_after_delay(messages, delay):
    await asyncio.sleep(delay)
    for msg in messages:
        try:
            if msg: await msg.delete()
        except Exception: pass

@app.on_message(filters.channel & (filters.video | filters.document) & filters.chat(FILE_CHANNEL_ID))
async def save_movie_handler(client, message):
    caption = message.caption or ""
    title_match = re.search(r"(.+?)\s*\(?(\d{4})\)?", caption, re.IGNORECASE)
    year = title_match.group(2) if title_match else None
    raw_title = title_match.group(1).strip() if title_match else ' '.join(caption.split('(')[0].split('[')[0].split())
    if not raw_title: LOGGER.warning(f"Could not parse title from: '{caption}'"); return
    
    clean_title = re.sub(r'[\.\_]', ' ', raw_title).strip()
    quality = next((q for q in ["480p","720p","1080p","2160p","4k"] if q in caption.lower()), "Unknown")
    lang_map = {"bangla": "Bangla", "bengali": "Bangla", "hindi": "Hindi", "english": "English"}
    language = next((lang_map[key] for key in lang_map if key in caption.lower()), "Unknown")
    
    query = {"title_lower": clean_title.lower()}
    if year: query["year"] = year
    movie_doc = await movie_info_db.find_one_and_update(query, {"$setOnInsert": {"title": clean_title, "year": year, "title_lower": clean_title.lower()}}, upsert=True, return_document=True)
    
    file_info = message.video or message.document
    await files_db.update_one({"movie_id": movie_doc['_id'], "quality": quality, "language": language}, {"$set": {"file_id": file_info.file_id, "chat_id": message.chat.id, "msg_id": message.id}}, upsert=True)
    LOGGER.info(f"✅ Indexed: {clean_title} ({year or 'N/A'}) [{quality} - {language}]")

# ========= 👮 অ্যাডমিন ও স্টার্ট কমান্ড ========= #
@app.on_message(filters.command("stats") & admin_filter)
async def stats_command(client, message):
    total_users, total_movies, total_files = await asyncio.gather(users_db.count_documents({}), movie_info_db.count_documents({}), files_db.count_documents({}))
    await message.reply_text(f"📊 **Bot Stats**\n\n👥 Users: `{total_users}`\n🎬 Movies: `{total_movies}`\n📁 Files: `{total_files}`\n\n📢 **Admin Panel:** {BOT_PUBLIC_URL}/admin")

@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    await users_db.update_one({"_id": user_id}, {"$set": {"name": message.from_user.first_name}}, upsert=True)
    if len(message.command) > 1:
        try:
            payload = message.command[1]
            decoded_data = base64.urlsafe_b64decode(payload).decode()
            action, data_id, verified_user_id_str = decoded_data.split('_')
            if user_id != int(verified_user_id_str): return await message.reply_text("😡 এই লিঙ্কটি আপনার জন্য নয়।")
            if action == "file":
                file_doc = await files_db.find_one({"_id": ObjectId(data_id)})
                if file_doc:
                    movie_doc = await movie_info_db.find_one({"_id": file_doc['movie_id']})
                    final_caption = (f"🎬 **{movie_doc.get('title','N/A')} ({movie_doc.get('year','N/A')})**\n"
                                     f"✨ **Quality:** {file_doc.get('quality','N/A')} | 🌐 **Language:** {file_doc.get('language','N/A')}\n\n"
                                     f"🙏 Thank you for using our bot!")
                    movie_msg = await client.copy_message(user_id, file_doc['chat_id'], file_doc['msg_id'], caption=final_caption)
                    warning_msg = await message.reply_text(f"❗ ফাইলটি **{DELETE_DELAY//60} মিনিট** পর অটো-ডিলিট হয়ে যাবে।", quote=True)
                    asyncio.create_task(delete_messages_after_delay([movie_msg, warning_msg], DELETE_DELAY))
        except Exception as e:
            LOGGER.error(f"Deep link error: {e}"); await message.reply_text("🤔 লিঙ্কটি সম্ভবত inválid বা মেয়াদোত্তীর্ণ।")
    else:
        reply_msg = await message.reply_text(f"👋 Hello, **{message.from_user.first_name}**!\nSend me a movie or series name to search.")
        asyncio.create_task(delete_messages_after_delay([message, reply_msg], 120))

# ========= 📞 কলব্যাক এবং পেজিনেশন ========= #
def build_search_markup(results, query, page, total):
    buttons = [[InlineKeyboardButton(f"🎬 {m.get('title','N/A')} ({m.get('year','N/A')})", callback_data=f"qual_{m['_id']}")] for m in results]
    if total > SEARCH_PAGE_SIZE:
        nav = []
        total_pages = math.ceil(total / SEARCH_PAGE_SIZE)
        if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"nav_{page-1}_{query}"))
        nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
        if (page + 1) * SEARCH_PAGE_SIZE < total: nav.append(InlineKeyboardButton("➡️", callback_data=f"nav_{page+1}_{query}"))
        buttons.append(nav)
    return InlineKeyboardMarkup(buttons)

@app.on_callback_query()
async def callback_handler(client, cb):
    data, user_id = cb.data, cb.from_user.id
    try:
        if data == "noop": await cb.answer(); return
        if data.startswith("qual_"):
            msg = await show_quality_options(cb.message, ObjectId(data.split("_", 1)[1]), is_edit=True, return_message=True)
            if msg: asyncio.create_task(delete_messages_after_delay([msg], DELETE_DELAY))
        elif data.startswith("file_"):
            encoded = base64.urlsafe_b64encode(f'file_{data.split("_",1)[1]}_{user_id}'.encode()).decode()
            url = f"{BOT_PUBLIC_URL}/verify?data={encoded}"
            await cb.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ ভেরিফাই করে ডাউনলোড করুন", url=url)]]))
        elif data.startswith("nav_"):
            _, page, query = data.split("_", 2)
            page = int(page)
            regex = re.compile('.*'.join(query.split()), re.IGNORECASE)
            total = await movie_info_db.count_documents({'title_lower': regex})
            results = await movie_info_db.find({'title_lower': regex}).skip(page * SEARCH_PAGE_SIZE).limit(SEARCH_PAGE_SIZE).to_list(length=SEARCH_PAGE_SIZE)
            if results: await cb.message.edit_text("🤔 আপনি কি এগুলোর মধ্যে কোনো একটি খুঁজছেন?", reply_markup=build_search_markup(results, query, page, total))
    except MessageNotModified: pass
    except Exception as e:
        LOGGER.error(f"Callback error: {e}"); await cb.answer("কিছু একটা সমস্যা হয়েছে।", show_alert=True)
    finally: await cb.answer()

async def show_quality_options(message, movie_id, is_edit=False, return_message=False):
    try:
        files = await files_db.find({"movie_id": movie_id}).sort("quality").to_list(length=None)
        movie = await movie_info_db.find_one({"_id": movie_id})
        if not files or not movie:
            text = "দুঃখিত, এই মুভির জন্য কোনো ফাইল বা তথ্য পাওয়া যায়নি।"
            return await (message.edit_text(text) if is_edit else message.reply_text(text)) if return_message else None
        text = f"🎬 **{movie.get('title','N/A')} ({movie.get('year','N/A')})**\n\n👇 আপনার পছন্দের কোয়ালিটি বেছে নিন:"
        buttons = [[InlineKeyboardButton(f"✨ {f['quality']} | 🌐 {f['language']}", callback_data=f"file_{f['_id']}")] for f in files]
        markup = InlineKeyboardMarkup(buttons)
        reply_msg = await message.edit_text(text, reply_markup=markup) if is_edit else await message.reply_text(text, reply_markup=markup, quote=True)
        return reply_msg if return_message else None
    except MessageNotModified: return message if return_message else None
    except Exception as e: LOGGER.error(f"Show quality options error: {e}"); return None

# ========= 🔎 চূড়ান্ত সার্চ হ্যান্ডলার (এরর ফিক্সড) ========= #
@app.on_message(
    (filters.private | filters.group) &
    filters.text &
    ~filters.command &
    filters.create(lambda _, __, msg: not msg.from_user.is_bot if msg.from_user else True)
)
async def search_handler(client, message):
    query = ' '.join(re.findall(r'\b[a-zA-Z0-9]+\b', message.text.lower()))
    if not query: return
    regex = re.compile('.*'.join(query.split()), re.IGNORECASE)
    messages_to_delete = [message]
    reply_msg = None
    try:
        total = await movie_info_db.count_documents({'title_lower': regex})
        LOGGER.info(f"Search for '{query}' in chat {message.chat.id} found {total} results.")
        if total == 0:
            if message.chat.type == ChatType.PRIVATE:
                reply_msg = await message.reply_text("❌ **মুভিটি খুঁজে পাওয়া যায়নি!**\n\nঅনুগ্রহ করে নামের বানানটি পরীক্ষা করুন।", quote=True)
        elif total == 1:
            movie = await movie_info_db.find_one({'title_lower': regex})
            reply_msg = await show_quality_options(message, movie['_id'], return_message=True)
        else:
            results = await movie_info_db.find({'title_lower': regex}).limit(SEARCH_PAGE_SIZE).to_list(length=SEARCH_PAGE_SIZE)
            markup = build_search_markup(results, query, 0, total)
            reply_msg = await message.reply_text("🤔 আপনি কি এগুলোর মধ্যে কোনো একটি খুঁজছেন?", reply_markup=markup, quote=True)
        if reply_msg: messages_to_delete.append(reply_msg)
    except Exception as e:
        LOGGER.error(f"Search error: {e}")
        if message.chat.type == ChatType.PRIVATE:
            reply_msg = await message.reply_text("⚠️ ডাটাবেস সমস্যার কারণে সার্চ করা সম্ভব হচ্ছে না।")
            if reply_msg: messages_to_delete.append(reply_msg)
    finally:
        if messages_to_delete: asyncio.create_task(delete_messages_after_delay(messages_to_delete, DELETE_DELAY))

# ========= ▶️ বট এবং ওয়েব সার্ভার চালু করা ========= #
async def main():
    await initialize_app_secrets()
    web_thread = Thread(target=lambda: web_app.run(host='0.0.0.0', port=PORT))
    web_thread.daemon = True
    web_thread.start()
    LOGGER.info("Web server started on a separate thread.")
    
    LOGGER.info("The Don is waking up... (v5.1 - Final Hotfix Edition)")
    await app.start()
    LOGGER.info("Bot has started successfully.")
    await asyncio.Event().wait() # Keep the bot running indefinitely

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.info("The Don is resting...")
