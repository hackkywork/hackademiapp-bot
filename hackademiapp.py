import os
import telebot
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
SUPABASE_URL = "https://vysoirkwthlidihayhfy.supabase.co"
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
        print(f"Помилка створення бекапу: {e}")
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

# 2. Реакція на команду /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    remove_markup = types.ReplyKeyboardRemove()
    temp_msg = bot.send_message(message.chat.id, "🔄 Оновлюю меню...", reply_markup=remove_markup)
    bot.delete_message(message.chat.id, temp_msg.message_id)

    markup = types.InlineKeyboardMarkup(row_width=1)
    
    web_app_btn = types.InlineKeyboardButton(
        "🚀 Відкрити платформу", 
        web_app=types.WebAppInfo(url="https://hackademia-web.vercel.app") 
    )
    
    markup.add(web_app_btn)

    bot.send_message(
        message.chat.id, 
        "Привіт! 👋 Я бот платформи **Hackademia** 🎓\n\n"
        "Тут ви можете керувати курсами, створювати тижні та додавати завдання для студентів.\n\n"
        "👇 Тисніть кнопку нижче, щоб розпочати роботу:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

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
    print("Бот запущено і слухає події (планувальник активний)...")
    try:
        bot.infinity_polling()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()