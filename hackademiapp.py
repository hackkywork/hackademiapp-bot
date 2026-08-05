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
ADMIN_ID = 597686904  # Твій Telegram ID
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
        
        bot.send_document(
            chat_id=chat_id_target,
            document=file_stream,
            caption=caption,
            parse_mode="Markdown"
        )
        return True
    except Exception as e:
        error_msg = f"Помилка створення бекапу: {str(e)}"
        print(error_msg)
        try:
            bot.send_message(ADMIN_ID, f"❌ Технічна помилка бекапу:\n`{str(e)}`", parse_mode="Markdown")
        except:
            pass
        return False

# Функція, яку викликатиме планувальник щодня
def scheduled_backup_job():
    print("⏳ Запуск автоматичного планового бекапу...")
    generate_and_send_backup(LOG_CHANNEL_ID, is_automatic=True)

# Налаштування фонового планувальника (APScheduler)
scheduler = BackgroundScheduler()
# Запускати щодня о 03:00 ночі
scheduler.add_job(scheduled_backup_job, 'cron', hour=3, minute=0)
scheduler.start()

# 1. Сповіщення про запуск
try:
    bot.send_message(ADMIN_ID, "🚀 Бот успішно запущено з активним автобекапером (щодня о 03:00)!")
except Exception as e:
    print("Не вдалося надіслати сповіщення:", e)

# 2. Реакція на команду /start та перевірка доступу
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Видаляємо стару клавіатуру, якщо була
    remove_markup = types.ReplyKeyboardRemove()
    temp_msg = bot.send_message(message.chat.id, "🔄 Перевіряю доступ...", reply_markup=remove_markup)
    bot.delete_message(message.chat.id, temp_msg.message_id)

    # Шукаємо юзера в Supabase
    response = supabase.table('users').select('*').eq('telegram_id', user_id).execute()
    
    if not response.data:
        # Новий юзер -> записуємо як pending
        supabase.table('users').insert({
            'telegram_id': user_id, 
            'first_name': first_name,
            'access_status': 'pending'
        }).execute()
        status = 'pending'
    else:
        status = response.data[0].get('access_status', 'pending')
        
    # Якщо це адмін або схвалений учень
    if user_id == ADMIN_ID or status == 'approved':
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
        # Статус 'pending'
        bot.send_message(message.chat.id, "⏳ Ваш запит на доступ надіслано головному адміністратору. Очікуйте підтвердження!")
        
        # Відправляємо запит адміну
        admin_markup = types.InlineKeyboardMarkup(row_width=2)
        btn_approve = types.InlineKeyboardButton("✅ Схвалити", callback_data=f"approve_{user_id}")
        btn_reject = types.InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{user_id}")
        admin_markup.add(btn_approve, btn_reject)
        
        mention = f"@{username}" if username else f"[{first_name}](tg://user?id={user_id})"
        
        bot.send_message(
            ADMIN_ID,
            f"🔔 **Новий запит на доступ!**\n\n"
            f"👤 Користувач: {mention}\n"
            f"🆔 ID: `{user_id}`\n\n"
            f"Надати доступ?",
            reply_markup=admin_markup,
            parse_mode="Markdown"
        )

# 2.1 Обробка кнопок адміна (Схвалити/Відхилити)
@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_access_decision(call):
    try:
        # ОБОВ'ЯЗКОВО: кажемо Телеграму, що кнопку натиснуто, щоб вона не зависала
        bot.answer_callback_query(call.id) 
        
        action, target_user_id = call.data.split('_')
        target_user_id = int(target_user_id)

        if action == 'approve':
            supabase.table('users').update({'access_status': 'approved'}).eq('telegram_id', target_user_id).execute()
            bot.edit_message_text(f"{call.message.text}\n\n✅ **СХВАЛЕНО**", chat_id=call.message.chat.id, message_id=call.message.message_id)
            
            try:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🚀 Відкрити платформу", web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app")))
                bot.send_message(target_user_id, "🎉 **Вашу заявку схвалено!**\n\nТепер ви маєте повний доступ до платформи.", reply_markup=markup, parse_mode="Markdown")
            except Exception as e:
                print("Не вдалося надіслати повідомлення учню:", e)
                
        elif action == 'reject':
            supabase.table('users').update({'access_status': 'rejected'}).eq('telegram_id', target_user_id).execute()
            bot.edit_message_text(f"{call.message.text}\n\n❌ **ВІДХИЛЕНО**", chat_id=call.message.chat.id, message_id=call.message.message_id)
            
            try:
                bot.send_message(target_user_id, "❌ Адміністратор відхилив вашу заявку на доступ.")
            except:
                pass
    except Exception as e:
        print("Помилка в обробці кнопки:", e)
        bot.answer_callback_query(call.id, "Виникла помилка!", show_alert=True)

# 2.5 КОМАНДА: /users (Керування доступом)
@bot.message_handler(commands=['users'])
def manage_users(message):
    if message.from_user.id != ADMIN_ID:
        return

    # Беремо всіх, у кого статус 'approved'
    response = supabase.table('users').select('*').eq('access_status', 'approved').execute()
    approved_users = response.data

    if not approved_users:
        bot.reply_to(message, "👻 Список порожній. Ще ніхто не має доступу.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for u in approved_users:
        name = u.get('first_name', 'Unknown')
        uid = u.get('telegram_id')
        # Не виводимо тебе самого в список на видалення
        if uid != ADMIN_ID:
            btn = types.InlineKeyboardButton(f"❌ Забрати доступ: {name}", callback_data=f"revoke_{uid}")
            markup.add(btn)

    bot.send_message(
        message.chat.id, 
        "👥 **Схвалені користувачі:**\n\nНатисніть кнопку під повідомленням, щоб назавжди забрати доступ у відповідного учня.", 
        reply_markup=markup, 
        parse_mode="Markdown"
    )

# Обробка кнопки "Забрати доступ"
@bot.callback_query_handler(func=lambda call: call.data.startswith('revoke_'))
def handle_revoke(call):
    try:
        target_id = int(call.data.split('_')[1])
        
        # Забираємо доступ у базі
        supabase.table('users').update({'access_status': 'rejected'}).eq('telegram_id', target_id).execute()
        bot.answer_callback_query(call.id, "✅ Доступ успішно скасовано!", show_alert=True)
        
        # Перемальовуємо клавіатуру, щоб ця кнопка зникла зі списку
        markup = call.message.reply_markup
        new_keyboard = [row for row in markup.keyboard if row[0].callback_data != call.data]
        new_markup = types.InlineKeyboardMarkup()
        for row in new_keyboard:
            new_markup.add(*row)
            
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=new_markup)
        
        # Сповіщаємо учня
        try:
            bot.send_message(target_id, "❌ Адміністратор скасував ваш доступ до платформи.")
        except:
            pass
            
    except Exception as e:
        print("Помилка видалення доступу:", e)
        bot.answer_callback_query(call.id, "Помилка бази даних", show_alert=True)

# 3. КОМАНДА: /backup (ручний запуск)
@bot.message_handler(commands=['backup'])
def handle_database_backup(message):
    if message.from_user.id != ADMIN_ID:
        return

    bot.reply_to(message, "⏳ Формую ручний бекап бази даних...")
    success = generate_and_send_backup(LOG_CHANNEL_ID, is_automatic=False)
    
    if success:
        bot.reply_to(message, "✅ Успішно! Файл бекапу відправлено у ваш кеш-канал.")
    else:
        bot.reply_to(message, "❌ Помилка при створенні бекапу.")

# 4. Обробка картинок
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        direct_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        
        bot.forward_message(LOG_CHANNEL_ID, message.chat.id, message.message_id)
        bot.reply_to(message, f"✅ Картинку оброблено!\n\n**Пряме посилання:**\n`{direct_url}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {e}")

# 5. Логування
@bot.message_handler(func=lambda message: True, content_types=['text', 'document', 'audio'])
def handle_logs_and_backups(message):
    if message.from_user.id == ADMIN_ID and not message.text.startswith('/'):
        try:
            bot.forward_message(LOG_CHANNEL_ID, message.chat.id, message.message_id)
            bot.reply_to(message, "💾 Зарезервовано в кеш-каналі!")
        except Exception as e:
            print("Помилка пересилання:", e)

if __name__ == '__main__':
    keep_alive()  # <--- ЦЕЙ РЯДОК ОБОВ'ЯЗКОВИЙ! Він запускає сервер
    
    print("Бот запущено і слухає події (планувальник активний)...")
    try:
        bot.infinity_polling()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()