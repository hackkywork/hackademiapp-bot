import os
import telebot
import re
from keep_alive import keep_alive
from telebot import types
import json
from datetime import datetime
import io
import smtplib
from email.mime.text import MIMEText
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler

# Налаштування Telegram
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [597686904, 5604755902]  # Адміни
LOG_CHANNEL_ID = -1001240560482  # Кеш-канал

# Налаштування Пошти
GMAIL_ACCOUNT = "hackslovak@gmail.com"
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')

# Налаштування Supabase
SUPABASE_URL = "https://vysoirkwthldlidayhfy.supabase.co"
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

bot = telebot.TeleBot(TOKEN)

# ----------------- ФУНКЦІЇ -----------------

def send_email_alert(user_name, user_id):
    if not GMAIL_PASSWORD:
        return
    try:
        msg = MIMEText(f"Новий користувач чекає на доступ до платформи Hackademia!\n\nІм'я: {user_name}\nID: {user_id}\n\nЗайдіть у Telegram-бот або панель адміністратора на сайті, щоб підтвердити заявку.")
        msg['Subject'] = '🔔 Нова заявка в Hackademia'
        msg['From'] = GMAIL_ACCOUNT
        msg['To'] = GMAIL_ACCOUNT

        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(GMAIL_ACCOUNT, GMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Помилка відправки email: {e}")

def generate_and_send_backup(chat_id_target, is_automatic=False):
    try:
        courses = supabase.table('courses').select('*').execute().data
        modules = supabase.table('modules').select('*').execute().data
        tasks = supabase.table('tasks').select('*').execute().data
        
        backup_type_label = "🤖 Автоматичний щоденний бекап" if is_automatic else "📦 Ручний бекап"
        
        backup_data = {
            "type": backup_type_label,
            "export_date": datetime.now().isoformat(),
            "courses": courses,
            "modules": modules,
            "tasks": tasks
        }
        
        json_string = json.dumps(backup_data, indent=2, ensure_ascii=False)
        current_time_str = datetime.now().strftime('%Y-%m-%d_%H-%M')
        file_stream = io.BytesIO(json_string.encode('utf-8'))
        file_stream.name = f"hackademia_backup_{current_time_str}.json"
        
        caption = f"{backup_type_label}\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        bot.send_document(chat_id_target, file_stream, caption=caption, parse_mode="HTML")
        return True
    except Exception as e:
        return False

def scheduled_backup_job():
    generate_and_send_backup(LOG_CHANNEL_ID, is_automatic=True)

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_backup_job, 'cron', hour=3, minute=0)
scheduler.start()

# ----------------- ЛОГІКА ДОСТУПУ -----------------

def process_user_access(message, user_id, first_name, username):
    remove_markup = types.ReplyKeyboardRemove()
    try:
        response = supabase.table('users').select('*').eq('telegram_id', user_id).execute()
        if not response.data:
            supabase.table('users').insert({
                'telegram_id': user_id, 
                'first_name': first_name,
                'username': username,
                'access_status': 'pending'
            }).execute()
            status = 'pending'
            send_email_alert(first_name, user_id)
        else:
            supabase.table('users').update({'username': username}).eq('telegram_id', user_id).execute()
            status = response.data[0].get('access_status', 'pending')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка БД: {e}")
        return
        
    if user_id in ADMIN_IDS or status == 'approved':
        markup = types.InlineKeyboardMarkup(row_width=1)
        web_app_btn = types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app/app"))
        markup.add(web_app_btn)
        bot.send_message(message.chat.id, f"Привіт, {first_name}! 👋 Я бот платформи <b>Hackademia</b> 🎓\n\n👇 Тисніть кнопку нижче, щоб розпочати роботу:", reply_markup=markup, parse_mode="HTML")
    
    elif status == 'rejected':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Надіслати запит повторно", callback_data="reapply_access"))
        bot.send_message(
            message.chat.id, 
            "❌ <b>Ваш доступ до платформи скасовано.</b>\n\n"
            "Щоб відновити доступ, придбайте новий курс або лекцію. "
            "Після оплати натисніть кнопку нижче, щоб надіслати запит адміністратору.", 
            reply_markup=markup, parse_mode="HTML"
        )
    
    else:
        bot.send_message(message.chat.id, "⏳ Ваш запит на доступ надіслано головному адміністратору. Очікуйте підтвердження!")
        
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        mention = f"@{username}" if username else "Не вказано (приховано)"
        lang = getattr(message.from_user, 'language_code', "Невідомо")
        
        notification_text = (
            f"🔔 <b>Нова заявка на доступ!</b>\n\n"
            f"👤 <b>Ім'я:</b> {full_name}\n"
            f"🔗 <b>Юзернейм:</b> {mention}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"🌐 <b>Мова пристрою:</b> {lang}\n\n"
            f"👉 Зайдіть на сайт платформи (натисніть на 🔔 вгорі), щоб керувати доступом."
        )
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, notification_text, parse_mode="HTML")
            except:
                pass

def get_support_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton("📚 Підібрати навчання"),
        types.KeyboardButton("👨‍💻 Зв'язатися з менеджером")
    )
    return markup

# ----------------- ОБРОБНИКИ КОМАНД І КНОПОК -----------------

@bot.message_handler(commands=['start', 'support'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    if message.text == '/start support' or message.text == '/support':
        username_str = f"@{username}" if username else "Не вказано (приховано)"
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        
        admin_msg = (
            f"🔥 <b>НОВИЙ ЛІД У БОТІ! (Щойно зайшов з сайту)</b>\n\n"
            f"<i>Людина відкрила бота через віджет підтримки. Вона ще нічого не написала, але ви вже маєте її контакт:</i>\n\n"
            f"👤 <b>Учень:</b> {full_name}\n"
            f"🔗 <b>Юзернейм:</b> {username_str}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n\n"
            f"💬 <i>(Якщо вона обере курс або напише питання, ви отримаєте додаткове сповіщення з текстом)</i>"
        )
        for admin in ADMIN_IDS:
            try: bot.send_message(admin, admin_msg, parse_mode="HTML")
            except: pass
            
        bot.send_message(
            message.chat.id, 
            "💬 Вітаємо в службі підтримки Hackademia! \n\nВиберіть тему з меню нижче або просто напишіть своє запитання сюди.",
            reply_markup=get_support_menu()
        )
        process_user_access(message, user_id, first_name, username)
        return

    if message.text.startswith('/start pin_'):
        bot.send_message(
            message.chat.id, 
            "💬 Вітаємо в службі підтримки Hackademia! \n\nВиберіть тему з меню нижче або просто напишіть своє запитання сюди.",
            reply_markup=get_support_menu()
        )
        process_user_access(message, user_id, first_name, username)
        return

    process_user_access(message, user_id, first_name, username)

# --- ВОРОНКА ПІДБОРУ НАВЧАННЯ ---
@bot.message_handler(func=lambda message: message.text in ["📚 Підібрати навчання", "👨‍💻 Зв'язатися з менеджером", "📘 Дізнатися ціни", "🎓 Рівні та формати"])
def handle_support_menu(message):
    if message.text in ["📚 Підібрати навчання", "📘 Дізнатися ціни", "🎓 Рівні та формати"]:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Рівень A1", callback_data="lvl_A1"),
            types.InlineKeyboardButton("Рівень A2", callback_data="lvl_A2"),
            types.InlineKeyboardButton("Рівень B1", callback_data="lvl_B1"),
            types.InlineKeyboardButton("Рівень B2", callback_data="lvl_B2")
        )
        bot.send_message(
            message.chat.id,
            "Для того, щоб підібрати для вас найкращі умови, скажіть, <b>який рівень словацької мови вас цікавить?</b>",
            reply_markup=markup,
            parse_mode="HTML"
        )
    elif message.text == "👨‍💻 Зв'язатися з менеджером":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Написати менеджеру 📝", url="https://t.me/xackademia"))
        bot.send_message(
            message.chat.id,
            "Натисніть кнопку нижче, щоб перейти в особистий чат з адміністратором платформи:",
            reply_markup=markup
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('lvl_'))
def handle_level_selection(call):
    print(f"👉 Отримано клік рівня: {call.data}")
    try: 
        bot.answer_callback_query(call.id, text="Завантажую...")
    except Exception as e: 
        print(f"⚠️ Помилка зняття спінера (lvl): {e}")
    
    level = call.data.split('_')[1] 
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👥 Групові", callback_data=f"fmt_{level}_group"),
        types.InlineKeyboardButton("🎯 Індивідуальні", callback_data=f"fmt_{level}_ind")
    )
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_levels"))
    
    try:
        bot.edit_message_text(
            f"Ви обрали <b>Рівень {level}</b>.\n\nЯкий формат занять вам підходить найбільше?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup
        )
        print("✅ Повідомлення рівня успішно змінено.")
    except Exception as e:
        print(f"❌ Помилка редагування (lvl): {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_levels')
def handle_back_to_levels(call):
    print(f"👉 Отримано клік 'Назад': {call.data}")
    try: 
        bot.answer_callback_query(call.id)
    except Exception as e: 
        print(f"⚠️ Помилка зняття спінера (back): {e}")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Рівень A1", callback_data="lvl_A1"),
        types.InlineKeyboardButton("Рівень A2", callback_data="lvl_A2"),
        types.InlineKeyboardButton("Рівень B1", callback_data="lvl_B1"),
        types.InlineKeyboardButton("Рівень B2", callback_data="lvl_B2")
    )
    try:
        bot.edit_message_text(
            "Для того, щоб підібрати для вас найкращі умови, скажіть, <b>який рівень словацької мови вас цікавить?</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        print(f"❌ Помилка редагування (back): {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('fmt_'))
def handle_format_selection(call):
    print(f"👉 Отримано клік формату: {call.data}")
    try: 
        bot.answer_callback_query(call.id, text="Заявку прийнято!")
    except Exception as e: 
        print(f"⚠️ Помилка зняття спінера (fmt): {e}")
    
    parts = call.data.split('_')
    level = parts[1]
    format_type = "Групові заняття" if parts[2] == "group" else "Індивідуальні заняття"
    
    first_name = call.from_user.first_name or ""
    last_name = call.from_user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    username = f"@{call.from_user.username}" if call.from_user.username else "Не вказано (приховано)"
    
    admin_msg = (
        f"🔥 <b>НОВИЙ ГАРЯЧИЙ ЛІД!</b>\n\n"
        f"👤 <b>Учень:</b> {full_name}\n"
        f"🔗 <b>Юзернейм:</b> {username}\n"
        f"📊 <b>Цікавить рівень:</b> {level}\n"
        f"🏫 <b>Формат:</b> {format_type}\n\n"
        f"🆔 ID: {call.from_user.id}\n\n"
        f"💬 <i>Щоб відповісти клієнту прямо тут, зробіть Reply (Відповісти) на це повідомлення.</i>"
    )
    
    for admin_id in ADMIN_IDS:
        try: bot.send_message(admin_id, admin_msg, parse_mode="HTML")
        except: pass
        
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👨‍💻 Написати менеджеру зараз", url="https://t.me/xackademia"))
    
    try:
        bot.edit_message_text(
            f"✅ <b>Вашу заявку успішно прийнято!</b>\n\n"
            f"Ви обрали:\n"
            f"Курс: <b>Рівень {level}</b>\n"
            f"Формат: <b>{format_type}</b>\n\n"
            f"Наш менеджер зв'яжеться з вами найближчим часом, щоб надати актуальну інформацію щодо цін, розкладу та відповісти на всі питання.\n\n"
            f"Якщо не хочете чекати, можете написати нам напряму 👇",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        print(f"❌ Помилка редагування (fmt): {e}")
# --- КІНЕЦЬ БЛОКУ ВОРОНКИ ---

@bot.callback_query_handler(func=lambda call: call.data == 'reapply_access')
def handle_reapply(call):
    print(f"👉 Отримано клік 'Повторний запит': {call.data}")
    try: bot.answer_callback_query(call.id)
    except: pass
    
    user_id = call.from_user.id
    try:
        supabase.table('users').update({'access_status': 'pending'}).eq('telegram_id', user_id).execute()
        
        try:
            bot.edit_message_text(
                "⏳ Ваш повторний запит надіслано адміністратору! Очікуйте підтвердження.", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id
            )
        except: pass
        
        last_name = call.from_user.last_name or ""
        full_name = f"{call.from_user.first_name} {last_name}".strip()
        username = call.from_user.username
        mention = f"@{username}" if username else "Не вказано"
        lang = getattr(call.from_user, 'language_code', "Невідомо")
        
        notification_text = (
            f"🔔 <b>Повторна заявка на доступ!</b>\n\n"
            f"👤 <b>Ім'я:</b> {full_name}\n"
            f"🔗 <b>Юзернейм:</b> {mention}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"🌐 <b>Мова:</b> {lang}\n\n"
            f"👉 Зайдіть на сайт платформи, щоб надати доступ."
        )
        for admin_id in ADMIN_IDS:
            try: bot.send_message(admin_id, notification_text, parse_mode="HTML")
            except: pass
                
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Виникла помилка під час обробки: {e}")

@bot.message_handler(commands=['add'])
def manual_add_user(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 2:
            bot.reply_to(message, "✍️ <b>Використання:</b> <code>/add ID [Ім'я]</code>", parse_mode="HTML")
            return
            
        target_id = int(parts[1])
        name = parts[2] if len(parts) > 2 else "Студент"
        
        resp = supabase.table('users').select('*').eq('telegram_id', target_id).execute()
        if resp.data:
            supabase.table('users').update({'access_status': 'approved', 'first_name': name, 'needs_course_assignment': True}).eq('telegram_id', target_id).execute()
        else:
            supabase.table('users').insert({'telegram_id': target_id, 'first_name': name, 'access_status': 'approved', 'needs_course_assignment': True}).execute()
            
        bot.reply_to(message, f"✅ Учня <code>{target_id}</code> успішно додано! На сайті з'явиться нагадування про вибір курсу.", parse_mode="HTML")
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app")))
            bot.send_message(target_id, "🎉 <b>Адміністратор надав вам доступ!</b>\n\nТепер ви можете користуватися платформою.", reply_markup=markup, parse_mode="HTML")
        except:
            pass
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_access_decision(call):
    try: bot.answer_callback_query(call.id)
    except: pass

    if call.from_user.id not in ADMIN_IDS:
        bot.send_message(call.message.chat.id, "❌ У вас немає прав!")
        return
        
    try:
        action, target_user_id = call.data.split('_')
        target_user_id = int(target_user_id)

        if action == 'approve':
            supabase.table('users').update({'access_status': 'approved', 'needs_course_assignment': True}).eq('telegram_id', target_user_id).execute()
            bot.edit_message_text(text=f"🔔 Запит від ID <code>{target_user_id}</code>\n\n✅ Рішення: <b>СХВАЛЕНО</b>\n(На сайті з'явиться нагадування про курси)", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=None)
            try:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app")))
                bot.send_message(target_user_id, "🎉 <b>Вашу заявку схвалено!</b>\n\nТепер ви маєте повний доступ до платформи.", reply_markup=markup, parse_mode="HTML")
            except: pass
                
        elif action == 'reject':
            supabase.table('users').update({'access_status': 'rejected'}).eq('telegram_id', target_user_id).execute()
            bot.edit_message_text(text=f"🔔 Запит від ID <code>{target_user_id}</code>\n\n❌ Рішення: <b>ВІДХИЛЕНО</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=None)
            try: 
                bot.send_message(target_user_id, "❌ Адміністратор відхилив вашу заявку на доступ.")
            except: pass
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Помилка: {e}")

@bot.message_handler(commands=['users'])
def manage_users(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    response = supabase.table('users').select('*').eq('access_status', 'approved').execute()
    approved_users = response.data
    if not approved_users:
        bot.reply_to(message, "👻 Список порожній.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for u in approved_users:
        name = u.get('first_name', 'Unknown')
        uid = u.get('telegram_id')
        if uid not in ADMIN_IDS:
            markup.add(types.InlineKeyboardButton(f"❌ Забрати доступ: {name}", callback_data=f"revoke_{uid}"))
    bot.send_message(message.chat.id, "👥 <b>Схвалені користувачі:</b>", reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('revoke_'))
def handle_revoke(call):
    try: bot.answer_callback_query(call.id)
    except: pass

    if call.from_user.id not in ADMIN_IDS:
        bot.send_message(call.message.chat.id, "❌ Немає прав!")
        return
        
    try:
        target_id = int(call.data.split('_')[1])
        supabase.table('users').update({'access_status': 'rejected'}).eq('telegram_id', target_id).execute()
        
        markup = call.message.reply_markup
        new_keyboard = [row for row in markup.keyboard if row[0].callback_data != call.data]
        new_markup = types.InlineKeyboardMarkup()
        for row in new_keyboard:
            new_markup.add(*row)
            
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=new_markup)
        bot.send_message(target_id, "❌ Адміністратор скасував ваш доступ до платформи.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Помилка: {e}")

@bot.message_handler(commands=['backup'])
def handle_database_backup(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    bot.reply_to(message, "⏳ Формую ручний бекап...")
    if generate_and_send_backup(LOG_CHANNEL_ID, is_automatic=False):
        bot.reply_to(message, "✅ Успішно!")
    else:
        bot.reply_to(message, "❌ Помилка.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        direct_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        bot.forward_message(LOG_CHANNEL_ID, message.chat.id, message.message_id)
        bot.reply_to(message, f"✅ Картинку оброблено!\n\n<b>Пряме посилання:</b>\n<code>{direct_url}</code>", parse_mode="HTML")
    except: pass

# ОБРОБКА ВІДПОВІДЕЙ АДМІНА ЧЕРЕЗ БОТА
@bot.message_handler(func=lambda message: message.reply_to_message is not None and message.from_user.id in ADMIN_IDS, content_types=['text', 'photo', 'document', 'audio', 'voice', 'video'])
def handle_admin_reply(message):
    original_text = message.reply_to_message.text or message.reply_to_message.caption
    
    if not original_text or "ID:" not in original_text:
        return

    try:
        # Регекс: бере і цифри (Telegram), і букви (UUID Google)
        user_id_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}|\d{7,15})', original_text)
        if not user_id_match:
            bot.reply_to(message, "❌ Не зміг розпізнати ID учня в цій заявці.")
            return
            
        target_id = user_id_match.group(1).strip()
        
        # Перевіряємо, чи це повідомлення саме з віджета на сайті
        is_from_website = "ПОВІДОМЛЕННЯ З САЙТУ" in original_text or "НОВЕ ПИТАННЯ З САЙТУ" in original_text
        telegram_sent = False
        
        # 1. Спроба відправити в Telegram напряму (якщо ID складається з цифр)
        if target_id.isdigit():
            target_user_id = int(target_id)
            try:
                if message.content_type == 'text':
                    bot.send_message(target_user_id, f"👨‍💻 <b>Відповідь від менеджера:</b>\n\n{message.text}", parse_mode="HTML")
                else:
                    bot.send_message(target_user_id, "👨‍💻 <b>Відповідь від менеджера:</b>", parse_mode="HTML")
                    bot.copy_message(target_user_id, message.chat.id, message.message_id)
                telegram_sent = True
            except Exception as e:
                if not is_from_website:
                    bot.reply_to(message, "❌ Користувач ще не натискав /start у боті. Telegram забороняє писати йому першим.")
                    return
        
        # 2. Якщо це заявка з сайту — ЗАВЖДИ дублюємо у віджет (Supabase) БЕЗ Email
        if is_from_website:
            if message.content_type != 'text':
                bot.reply_to(message, "⚠️ Для користувачів на сайті підтримується тільки текстова відповідь.")
                return

            admin_resp = supabase.table('users').select('id').eq('telegram_id', message.from_user.id).execute()
            if not admin_resp.data:
                bot.reply_to(message, "❌ Ваш адмінський акаунт не знайдено в базі платформи.")
                return
            admin_uuid = admin_resp.data[0]['id']
            
            # Шукаємо учня в базі
            if target_id.isdigit():
                user_resp = supabase.table('users').select('id').eq('telegram_id', int(target_id)).execute()
            else:
                user_resp = supabase.table('users').select('id').eq('id', target_id).execute()

            if user_resp.data:
                real_user_uuid = user_resp.data[0]['id']
                
                # Відправляємо у віджет на сайт
                supabase.table('messages').insert({
                    'user_id': real_user_uuid,
                    'sender_id': admin_uuid,
                    'text': message.text,
                    'is_read': False
                }).execute()
                
                bot.reply_to(message, "✅ Відповідь успішно доставлена клієнту у віджет на сайті!")
            else:
                bot.reply_to(message, "❌ Користувача не знайдено в базі сайту.")
        else:
            if telegram_sent:
                bot.reply_to(message, "✅ Відповідь успішно надіслана учню в Telegram!")
    except Exception as e:
        bot.reply_to(message, f"❌ Критична помилка обробки: {e}")

@bot.message_handler(func=lambda message: True, content_types=['text', 'document', 'audio', 'photo', 'video'])
def handle_all_other_messages(message):
    if message.from_user.id in ADMIN_IDS:
        if message.content_type == 'text' and message.text.startswith('/'):
            return 
        try:
            bot.forward_message(LOG_CHANNEL_ID, message.chat.id, message.message_id)
            bot.reply_to(message, "💾 Зарезервовано в кеш-каналі!")
        except: pass
        
    else:
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        username = f"@{message.from_user.username}" if message.from_user.username else "Не вказано"
        user_id = message.from_user.id
        
        text = message.text if message.content_type == 'text' else f"📁 Надіслав медіафайл ({message.content_type})"

        notification_text = (
            f"📩 <b>НОВЕ ПОВІДОМЛЕННЯ ВІД УЧНЯ (ЧЕРЕЗ БОТА)</b>\n\n"
            f"👤 <b>Учень:</b> {full_name}\n"
            f"🔗 <b>Юзернейм:</b> {username}\n"
            f"🆔 ID: {user_id}\n\n"
            f"💬 <b>Текст:</b>\n{text}\n\n"
            f"💬 <i>Щоб відповісти клієнту прямо тут, зробіть Reply (Відповісти) на це повідомлення.</i>"
        )

        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, notification_text, parse_mode="HTML")
                if message.content_type != 'text':
                     bot.forward_message(admin_id, message.chat.id, message.message_id)
            except:
                pass
        
        bot.reply_to(message, "✅ Ваше повідомлення успішно надіслано в службу підтримки. Менеджер незабаром вам відповість!")

# Універсальний обробник
@bot.callback_query_handler(func=lambda call: True)
def catch_all_callbacks(call):
    try: bot.answer_callback_query(call.id)
    except: pass

if __name__ == '__main__':
    keep_alive()
    try:
        bot.remove_webhook()
        print("Вебхук успішно видалено. Переходимо на Polling...")
    except: pass

    print("Бот запущено і слухає події...")
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=15)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()