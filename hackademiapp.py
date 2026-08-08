import os
import telebot
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

# Обов'язкові канали для підписки
REQUIRED_CHANNELS = ["@hackslovak", "@hackslovak_blog"]

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
        bot.send_document(chat_id_target, file_stream, caption=caption, parse_mode="Markdown")
        return True
    except Exception as e:
        return False

def scheduled_backup_job():
    generate_and_send_backup(LOG_CHANNEL_ID, is_automatic=True)

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_backup_job, 'cron', hour=3, minute=0)
scheduler.start()

# ----------------- ПЕРЕВІРКА ПІДПИСОК -----------------

def check_user_subscription(user_id):
    if user_id in ADMIN_IDS:
        return True
    for channel in REQUIRED_CHANNELS:
        try:
            stat = bot.get_chat_member(channel, user_id).status
            if stat in ['left', 'kicked']:
                return False
        except Exception as e:
            print(f"Помилка перевірки підписки для {channel}: {e}")
            return False
    return True

def send_subscription_prompt(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 Канал HackSlovak", url="https://t.me/hackslovak"),
        types.InlineKeyboardButton("📝 Блог HackSlovak", url="https://t.me/hackslovak_blog"),
        types.InlineKeyboardButton("✅ Я підписався", callback_data="check_subscription")
    )
    bot.send_message(
        chat_id, 
        "👋 **Привіт!**\n\nЩоб користуватися платформою Hackademia, необхідно бути підписаним на наші канали.\n\nПідпишіться та натисніть кнопку нижче 👇", 
        reply_markup=markup, parse_mode="Markdown"
    )

# ----------------- ЛОГІКА ДОСТУПУ -----------------

def process_user_access(message, user_id, first_name, username):
    remove_markup = types.ReplyKeyboardRemove()
    try:
        response = supabase.table('users').select('*').eq('telegram_id', user_id).execute()
        if not response.data:
            supabase.table('users').insert({
                'telegram_id': user_id, 
                'first_name': first_name,
                'access_status': 'pending'
            }).execute()
            status = 'pending'
            send_email_alert(first_name, user_id)
        else:
            status = response.data[0].get('access_status', 'pending')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка БД: {e}")
        return
        
    if user_id in ADMIN_IDS or status == 'approved':
        markup = types.InlineKeyboardMarkup(row_width=1)
        web_app_btn = types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app"))
        markup.add(web_app_btn)
        bot.send_message(message.chat.id, f"Привіт, {first_name}! 👋 Я бот платформи **Hackademia** 🎓\n\n👇 Тисніть кнопку нижче, щоб розпочати роботу:", reply_markup=markup, parse_mode="Markdown")
    
    elif status == 'rejected':
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Надіслати запит повторно", callback_data="reapply_access"))
        bot.send_message(
            message.chat.id, 
            "❌ **Ваш доступ до платформи скасовано.**\n\n"
            "Щоб відновити доступ, придбайте новий курс або лекцію. "
            "Після оплати натисніть кнопку нижче, щоб надіслати запит адміністратору.", 
            reply_markup=markup, parse_mode="Markdown"
        )
    
    else:
        bot.send_message(message.chat.id, "⏳ Ваш запит на доступ надіслано головному адміністратору. Очікуйте підтвердження!")
        
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        mention = f"@{username}" if username else "Не вказано (приховано)"
        lang = getattr(message.from_user, 'language_code', "Невідомо")
        
        notification_text = (
            f"🔔 **Нова заявка на доступ!**\n\n"
            f"👤 **Ім'я:** {full_name}\n"
            f"🔗 **Юзернейм:** {mention}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"🌐 **Мова пристрою:** {lang}\n\n"
            f"👉 Зайдіть на сайт платформи (натисніть на 🔔 вгорі), щоб керувати доступом."
        )
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, notification_text, parse_mode="Markdown")
            except:
                pass

# ----------------- ОБРОБНИКИ КОМАНД І КНОПОК -----------------

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    if not check_user_subscription(user_id):
        send_subscription_prompt(message.chat.id)
        return

    process_user_access(message, user_id, first_name, username)

# Обробник кнопки "Я підписався"
@bot.callback_query_handler(func=lambda call: call.data == 'check_subscription')
def verify_sub_callback(call):
    # 1. ЗАЛІЗОБЕТОННО: Гасимо коліщатко один раз на самому початку!
    try: bot.answer_callback_query(call.id)
    except: pass
    
    user_id = call.from_user.id
    
    # 2. Перевіряємо підписку
    if check_user_subscription(user_id):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        process_user_access(call.message, user_id, call.from_user.first_name, call.from_user.username)
    else:
        # Відправляємо текст у чат (щоб не конфліктувати з answer_callback_query)
        bot.send_message(call.message.chat.id, "❌ Ви ще не підписалися на всі канали! Підпишіться та спробуйте знову.")

# Обробник кнопки "Надіслати запит повторно"
@bot.callback_query_handler(func=lambda call: call.data == 'reapply_access')
def handle_reapply(call):
    # 1. ЗАЛІЗОБЕТОННО: Гасимо коліщатко один раз на самому початку!
    try: bot.answer_callback_query(call.id)
    except: pass
    
    user_id = call.from_user.id
    
    try:
        # 2. Перевіряємо підписку
        if not check_user_subscription(user_id):
            bot.send_message(call.message.chat.id, "❌ Підпишіться на канали перед подачею запиту!")
            send_subscription_prompt(call.message.chat.id)
            return

        # 3. Оновлюємо статус в базі
        supabase.table('users').update({'access_status': 'pending'}).eq('telegram_id', user_id).execute()
        
        # 4. Міняємо старе повідомлення, щоб кнопка зникла
        try:
            bot.edit_message_text(
                "⏳ Ваш повторний запит надіслано адміністратору! Очікуйте підтвердження.", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id
            )
        except: pass
        
        # 5. Формуємо сповіщення адмінам
        last_name = call.from_user.last_name or ""
        full_name = f"{call.from_user.first_name} {last_name}".strip()
        username = call.from_user.username
        mention = f"@{username}" if username else "Не вказано"
        lang = getattr(call.from_user, 'language_code', "Невідомо")
        
        notification_text = (
            f"🔔 **Повторна заявка на доступ!**\n\n"
            f"👤 **Ім'я:** {full_name}\n"
            f"🔗 **Юзернейм:** {mention}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"🌐 **Мова:** {lang}\n\n"
            f"👉 Зайдіть на сайт платформи, щоб надати доступ."
        )
        for admin_id in ADMIN_IDS:
            try: 
                bot.send_message(admin_id, notification_text, parse_mode="Markdown")
            except: 
                pass
                
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Виникла помилка під час обробки: {e}")

@bot.message_handler(commands=['add'])
def manual_add_user(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 2:
            bot.reply_to(message, "✍️ **Використання:** `/add ID [Ім'я]`", parse_mode="Markdown")
            return
            
        target_id = int(parts[1])
        name = parts[2] if len(parts) > 2 else "Студент"
        
        resp = supabase.table('users').select('*').eq('telegram_id', target_id).execute()
        if resp.data:
            supabase.table('users').update({'access_status': 'approved', 'first_name': name}).eq('telegram_id', target_id).execute()
        else:
            supabase.table('users').insert({'telegram_id': target_id, 'first_name': name, 'access_status': 'approved'}).execute()
            
        bot.reply_to(message, f"✅ Учня `{target_id}` успішно додано та схвалено!", parse_mode="Markdown")
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app")))
            bot.send_message(target_id, "🎉 **Адміністратор надав вам доступ!**\n\nТепер ви можете користуватися платформою.", reply_markup=markup, parse_mode="Markdown")
        except:
            pass
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {e}")

@bot.message_handler(func=lambda message: message.forward_date is not None)
def handle_forwarded_message(message):
    if message.from_user.id not in ADMIN_IDS:
        return

    if message.forward_from:
        target_id = message.forward_from.id
        name = message.forward_from.first_name
        
        response = supabase.table('users').select('*').eq('telegram_id', target_id).execute()
        status = response.data[0].get('access_status', 'Немає в базі') if response.data else 'Немає в базі'
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        if status == 'approved':
            markup.add(types.InlineKeyboardButton("❌ Видалити доступ", callback_data=f"revoke_{target_id}"))
        else:
            markup.add(
                types.InlineKeyboardButton("✅ Схвалити", callback_data=f"approve_{target_id}"),
                types.InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{target_id}")
            )
            
        bot.reply_to(message, f"👤 **Профіль:** {name}\n🆔 **ID:** `{target_id}`\n📊 **Статус:** `{status}`\n\nЩо робимо?", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_access_decision(call):
    # Одразу гасимо коліщатко
    try: bot.answer_callback_query(call.id)
    except: pass

    if call.from_user.id not in ADMIN_IDS:
        bot.send_message(call.message.chat.id, "❌ У вас немає прав!")
        return
        
    try:
        action, target_user_id = call.data.split('_')
        target_user_id = int(target_user_id)

        if action == 'approve':
            supabase.table('users').update({'access_status': 'approved'}).eq('telegram_id', target_user_id).execute()
            bot.edit_message_text(text=f"🔔 Запит від ID `{target_user_id}`\n\n✅ Рішення: **СХВАЛЕНО**", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=None)
            try:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app")))
                bot.send_message(target_user_id, "🎉 **Вашу заявку схвалено!**\n\nТепер ви маєте повний доступ до платформи.", reply_markup=markup, parse_mode="Markdown")
            except: pass
                
        elif action == 'reject':
            supabase.table('users').update({'access_status': 'rejected'}).eq('telegram_id', target_user_id).execute()
            bot.edit_message_text(text=f"🔔 Запит від ID `{target_user_id}`\n\n❌ Рішення: **ВІДХИЛЕНО**", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=None)
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
    bot.send_message(message.chat.id, "👥 **Схвалені користувачі:**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('revoke_'))
def handle_revoke(call):
    # Одразу гасимо коліщатко
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
        bot.reply_to(message, f"✅ Картинку оброблено!\n\n**Пряме посилання:**\n`{direct_url}`", parse_mode="Markdown")
    except: pass

@bot.message_handler(func=lambda message: True, content_types=['text', 'document', 'audio'])
def handle_logs_and_backups(message):
    if message.from_user.id in ADMIN_IDS and not message.text.startswith('/'):
        try:
            bot.forward_message(LOG_CHANNEL_ID, message.chat.id, message.message_id)
            bot.reply_to(message, "💾 Зарезервовано в кеш-каналі!")
        except: pass

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