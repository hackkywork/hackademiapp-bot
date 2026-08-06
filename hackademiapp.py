import os
import telebot
from keep_alive import keep_alive
from telebot import types
import json
from datetime import datetime
import io
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler

# Налаштування Telegram
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [597686904, 5604755902]  # Обидва твої акаунти є адмінами!
LOG_CHANNEL_ID = -1001240560482  # Кеш-канал

# Налаштування Supabase
SUPABASE_URL = "https://vysoirkwthldlidayhfy.supabase.co"
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

bot = telebot.TeleBot(TOKEN)

# Універсальна функція для створення бекапу
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
        print(f"Помилка створення бекапу: {e}")
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, f"❌ Технічна помилка бекапу:\n`{str(e)}`", parse_mode="Markdown")
            except:
                pass
        return False

# Функція, яку викликатиме планувальник щодня
def scheduled_backup_job():
    print("⏳ Запуск автоматичного планового бекапу...")
    generate_and_send_backup(LOG_CHANNEL_ID, is_automatic=True)

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_backup_job, 'cron', hour=3, minute=0)
scheduler.start()

# 1. Сповіщення про запуск (всім адмінам)
for admin_id in ADMIN_IDS:
    try:
        bot.send_message(admin_id, "🚀 Бот успішно запущено з оновленою системою фейсконтролю!")
    except:
        pass

# 2. Реакція на команду /start та перевірка доступу
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    remove_markup = types.ReplyKeyboardRemove()
    temp_msg = bot.send_message(message.chat.id, "🔄 Перевіряю доступ...", reply_markup=remove_markup)
    bot.delete_message(message.chat.id, temp_msg.message_id)

    # Шукаємо юзера в Supabase
    try:
        response = supabase.table('users').select('*').eq('telegram_id', user_id).execute()
        if not response.data:
            supabase.table('users').insert({
                'telegram_id': user_id, 
                'first_name': first_name,
                'access_status': 'pending'
            }).execute()
            status = 'pending'
        else:
            status = response.data[0].get('access_status', 'pending')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка БД: {e}")
        return
        
    if user_id in ADMIN_IDS or status == 'approved':
        markup = types.InlineKeyboardMarkup(row_width=1)
        web_app_btn = types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app"))
        markup.add(web_app_btn)

        bot.send_message(
            message.chat.id, 
            f"Привіт, {first_name}! 👋 Я бот платформи **Hackademia** 🎓\n\n👇 Тисніть кнопку нижче, щоб розпочати роботу:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    elif status == 'rejected':
        bot.send_message(message.chat.id, "❌ Доступ до платформи закрито адміністратором.")
    else:
        bot.send_message(message.chat.id, "⏳ Ваш запит на доступ надіслано головному адміністратору. Очікуйте підтвердження!")
        
        admin_markup = types.InlineKeyboardMarkup(row_width=2)
        admin_markup.add(
            types.InlineKeyboardButton("✅ Схвалити", callback_data=f"approve_{user_id}"),
            types.InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{user_id}")
        )
        mention = f"@{username}" if username else f"[{first_name}](tg://user?id={user_id})"
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    f"🔔 **Новий запит на доступ!**\n\n👤 Користувач: {mention}\n🆔 ID: `{user_id}`\n\nНадати доступ?",
                    reply_markup=admin_markup,
                    parse_mode="Markdown"
                )
            except:
                pass

# 2.1 Обробка кнопок адміна (Схвалити/Відхилити)
@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_access_decision(call):
    try:
        bot.answer_callback_query(call.id, "Обробляю...") 
        
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ У вас немає прав!", show_alert=True)
            return
        
        action, target_user_id = call.data.split('_')
        target_user_id = int(target_user_id)

        if action == 'approve':
            supabase.table('users').update({'access_status': 'approved'}).eq('telegram_id', target_user_id).execute()
            
            # ТІЛЬКИ ОДНЕ РЕДАГУВАННЯ
            bot.edit_message_text(
                text=f"🔔 Запит від ID `{target_user_id}`\n\n✅ Рішення: **СХВАЛЕНО**", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id,
                parse_mode="Markdown",
                reply_markup=None
            )
            
            try:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app")))
                bot.send_message(target_user_id, "🎉 **Вашу заявку схвалено!**\n\nТепер ви маєте повний доступ до платформи.", reply_markup=markup, parse_mode="Markdown")
            except Exception as e:
                print("Помилка відправки учню:", e)
                
        elif action == 'reject':
            supabase.table('users').update({'access_status': 'rejected'}).eq('telegram_id', target_user_id).execute()
            
            # ТІЛЬКИ ОДНЕ РЕДАГУВАННЯ
            bot.edit_message_text(
                text=f"🔔 Запит від ID `{target_user_id}`\n\n❌ Рішення: **ВІДХИЛЕНО**", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id,
                parse_mode="Markdown",
                reply_markup=None
            )
            
            try:
                bot.send_message(target_user_id, "❌ Адміністратор відхилив вашу заявку на доступ.")
            except:
                pass
    except Exception as e:
        print(f"CRITICAL ERROR in handle_access_decision: {e}")

# 2.5 КОМАНДА: /users (Керування доступом)
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

# 2.6 Обробка кнопки "Забрати доступ"
@bot.callback_query_handler(func=lambda call: call.data.startswith('revoke_'))
def handle_revoke(call):
    try:
        if call.from_user.id not in ADMIN_IDS:
            return

        bot.answer_callback_query(call.id, "Видаляю доступ...")
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
        print(f"Помилка видалення: {e}")

# 3. КОМАНДА: /backup
@bot.message_handler(commands=['backup'])
def handle_database_backup(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    bot.reply_to(message, "⏳ Формую ручний бекап...")
    if generate_and_send_backup(LOG_CHANNEL_ID, is_automatic=False):
        bot.reply_to(message, "✅ Успішно!")
    else:
        bot.reply_to(message, "❌ Помилка.")

# 4. Обробка картинок
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        direct_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        bot.forward_message(LOG_CHANNEL_ID, message.chat.id, message.message_id)
        bot.reply_to(message, f"✅ Картинку оброблено!\n\n**Пряме посилання:**\n`{direct_url}`", parse_mode="Markdown")
    except:
        pass

# 5. Логування
@bot.message_handler(func=lambda message: True, content_types=['text', 'document', 'audio'])
def handle_logs_and_backups(message):
    if message.from_user.id in ADMIN_IDS and not message.text.startswith('/'):
        try:
            bot.forward_message(LOG_CHANNEL_ID, message.chat.id, message.message_id)
            bot.reply_to(message, "💾 Зарезервовано в кеш-каналі!")
        except:
            pass

# 6. Заглушка для старих кнопок
@bot.callback_query_handler(func=lambda call: True)
def catch_all_callbacks(call):
    try:
        bot.answer_callback_query(call.id, "⚠️ Ця кнопка застаріла! Напишіть боту /start", show_alert=True)
    except:
        pass

if __name__ == '__main__':
    keep_alive()
    print("Бот запущено і слухає події...")
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()