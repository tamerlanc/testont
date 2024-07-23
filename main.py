import logging
import os
import random
import sqlite3
from datetime import datetime
from idlelib import query

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import BadRequest
from telegram import InputMediaPhoto


# Регистрация адаптеров для SQLite
def adapt_datetime(ts):
    return ts.isoformat()


def convert_datetime(s):
    return datetime.fromisoformat(s.decode())


sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)

# Настройка логирования
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger = logging.getLogger('my_logger')
logger.setLevel(logging.INFO)
logger.addHandler(console_handler)

# Подключение к базе данных
conn = sqlite3.connect('user_scores.db', check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES)
cursor = conn.cursor()

# Попытка добавления новых столбцов
try:
    cursor.execute('ALTER TABLE user_scores ADD COLUMN referral_link TEXT')
    cursor.execute('ALTER TABLE user_scores ADD COLUMN referred_by INTEGER')
    cursor.execute('ALTER TABLE user_scores ADD COLUMN last_bonus_time timestamp')  # добавляем столбец для времени последнего бонуса
    conn.commit()
except sqlite3.OperationalError as e:
    logging.info(f"Column already exists or other operational error: {e}")

DATABASE_PATH = 'user_scores.db'

if not os.path.exists(DATABASE_PATH):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    # Создание таблицы, если она не существует
    cursor.execute('''
        CREATE TABLE user_scores (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            score INTEGER,
            daily_points INTEGER,
            last_update TEXT,
            referral_link TEXT,
            referred_by TEXT
        )
    ''')
    conn.commit()
else:
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()


# Создание таблицы для хранения информации о выполненных заданиях
cursor.execute('''CREATE TABLE IF NOT EXISTS completed_tasks (
                  user_id INTEGER,
                  task_id TEXT,
                  PRIMARY KEY (user_id, task_id))''')
conn.commit()


# Множество для хранения пользователей, которые подписались на канал
subscribed_users = set()
banned_users = set()  # Множество для хранения забаненных пользователей

ADMIN_IDS = {1426392317, 7341905089, 599241896}  # Замените на реальные user_id администраторов


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    referred_by = context.args[0] if context.args else None

    try:
        chat_member = await context.bot.get_chat_member(chat_id='@penisont', user_id=user_id)
    except BadRequest as e:
        logging.error(f"Error while checking chat member: {e}")
        await update.message.reply_text("Произошла ошибка при проверке вашего статуса подписки. Попробуйте позже.")
        return

    if chat_member and chat_member.status in ['member', 'administrator', 'creator']:
        subscribed_users.add(user_id)

        cursor.execute('SELECT * FROM user_scores WHERE user_id = ?', (user_id,))
        user_data = cursor.fetchone()

        if user_data is None:
            cursor.execute(
                'INSERT INTO user_scores (user_id, name, score, daily_points, last_update, referral_link, referred_by) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (user_id, update.effective_user.first_name, 0, 0, datetime.now(), '', referred_by))
            conn.commit()

        # Ensure the user does not get a bonus for referring themselves
        if referred_by and int(referred_by) != user_id:
            cursor.execute('SELECT * FROM user_scores WHERE user_id = ? AND referred_by = ?', (user_id, referred_by))
            referral_exists = cursor.fetchone()

            if not referral_exists:
                cursor.execute('UPDATE user_scores SET referred_by = ? WHERE user_id = ?', (referred_by, user_id))
                cursor.execute('SELECT * FROM user_scores WHERE user_id = ?', (referred_by,))
                referrer_data = cursor.fetchone()
                if referrer_data:
                    cursor.execute('UPDATE user_scores SET score = score + 500 WHERE user_id = ?', (referred_by,))
                    conn.commit()
                    referrer_chat_id = referred_by
                    await context.bot.send_message(chat_id=referrer_chat_id,
                                                   text="Вам начислено 500 $LIST за приглашенного пользователя!")

        keyboard = [
            [InlineKeyboardButton("Кликать!", callback_data='click')],
            [InlineKeyboardButton("🏆Реферальная система", callback_data='referral')],
            [InlineKeyboardButton("ℹ️Информация", callback_data='info')],
            [InlineKeyboardButton("💸Ежедневный бонус", callback_data='daily_bonus')],
            [InlineKeyboardButton("📝Задания", callback_data='tasks')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            'Добро пожаловать в бота-кликера! Нажмите "Клик!" чтобы начать или "Реферальная система" для получения ссылки.',
            reply_markup=reply_markup)
    else:
        keyboard = [[InlineKeyboardButton("Подписаться на канал", url='https://t.me/penisont')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Для использования бота необходимо подписаться на канал!',
                                        reply_markup=reply_markup)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.first_name

    if query.data == 'daily_bonus':
        await handle_daily_bonus(update, context)
        return

    if user_id in banned_users:
        await query.answer("Вы забанены и не можете использовать бота.")
        return

    if user_id not in subscribed_users:
        await query.answer("Пожалуйста, подпишитесь на канал, чтобы продолжить использование бота.")
        return

    cursor.execute('SELECT * FROM user_scores WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        last_update = user_data[4]
        if isinstance(last_update, str):
            last_update = datetime.fromisoformat(last_update)
        if last_update.date() != datetime.now().date():
            cursor.execute('UPDATE user_scores SET daily_points = 0, last_update = ? WHERE user_id = ?',
                           (datetime.now(), user_id))
            conn.commit()
            user_data = (user_data[0], user_data[1], user_data[2], 0, datetime.now())
    else:
        cursor.execute(
            'INSERT INTO user_scores (user_id, name, score, daily_points, last_update) VALUES (?, ?, ?, ?, ?)',
            (user_id, user_name, 0, 0, datetime.now()))
        conn.commit()
        user_data = (user_id, user_name, 0, 0, datetime.now())

    if user_data[3] >= 10:
        await query.answer("Вы достигли дневного лимита в 10 $LIST.")
        return

    points = round(random.uniform(0.1, 0.3), 2)
    if user_data[3] + points > 10:
        points = 10 - user_data[3]

    new_score = user_data[2] + points
    new_daily_points = user_data[3] + points
    cursor.execute('UPDATE user_scores SET score = ?, daily_points = ?, last_update = ? WHERE user_id = ?',
                   (new_score, new_daily_points, datetime.now(), user_id))
    conn.commit()

    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Клик!", callback_data='click')],
        [InlineKeyboardButton("Назад", callback_data='back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=f"Вы заработали {points:.2f} $LIST! У вас всего {new_score:.2f} $LIST.",
                                  reply_markup=reply_markup)


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Канал", url='https://t.me/penisont')],
        [InlineKeyboardButton("Поддержка", url='https://t.me/wolf')],
        [InlineKeyboardButton("Назад", callback_data='back')]  # Добавляем кнопку "Назад"
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text='Информация о боте:\n\nЭтот бот позволяет зарабатывать $LIST, выполняя простые действия.',
        reply_markup=reply_markup)


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    referral_link = f"https://t.me/testontbot?start={user_id}"
    cursor.execute('UPDATE user_scores SET referral_link = ? WHERE user_id = ?', (referral_link, user_id))
    conn.commit()

    cursor.execute('SELECT score FROM user_scores WHERE user_id = ?', (user_id,))
    score = cursor.fetchone()[0]

    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Назад", callback_data='back')],
        # Добавьте здесь другие кнопки, если они есть
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text=f"Ваша реферальная ссылка: {referral_link}\nУ вас: {score:.2f} $LIST",
        reply_markup=reply_markup
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cursor.execute('SELECT * FROM user_scores ORDER BY score DESC LIMIT 10')
    top_users = cursor.fetchall()

    if not top_users:
        await update.message.reply_text("Еще никто не зарабатывал $LIST.")
        return

    leaderboard_text = "Топ 10 пользователей:\n"
    for i, user_data in enumerate(top_users, start=1):
        leaderboard_text += f"{i}. {user_data[1]} - {user_data[2]:.2f} $LIST\n"

    await update.message.reply_text(leaderboard_text)


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Подписаться на спонсора", url='https://t.me/penisont'),
         InlineKeyboardButton("Проверить", callback_data='check_subscription_@penisont')],
        [InlineKeyboardButton("Подписаться на спонсора", url='https://t.me/tasktestepta'),
         InlineKeyboardButton("Проверить", callback_data='check_subscription_@tasktestepta')],
        [InlineKeyboardButton("Назад", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text='Выберите задачу:',
        reply_markup=reply_markup)


async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    channel_username = query.data.split('_')[2]
    task_id = f'subscribe_{channel_username}'

    # Проверка, выполнял ли пользователь задание ранее
    cursor.execute('SELECT * FROM completed_tasks WHERE user_id = ? AND task_id = ?', (user_id, task_id))
    task_completed = cursor.fetchone()

    if task_completed:
        await query.answer("Вы уже выполнили это задание ранее.")
        return

    try:
        chat_member = await context.bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        if chat_member and chat_member.status in ['member', 'administrator', 'creator']:
            cursor.execute('UPDATE user_scores SET score = score + 100 WHERE user_id = ?', (user_id,))
            cursor.execute('INSERT INTO completed_tasks (user_id, task_id) VALUES (?, ?)', (user_id, task_id))
            conn.commit()
            await query.answer("Вы подписаны на канал! Вам начислено 100 $LIST.")
        else:
            await query.answer("Вы не подписаны на канал.")
    except BadRequest as e:
        logging.error(f"Error while checking chat member: {e}")
        await query.answer("Произошла ошибка при проверке вашего статуса подписки.")


async def handle_daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    cursor.execute('SELECT last_bonus_time, score FROM user_scores WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result:
        last_bonus_time, score = result
        if last_bonus_time is None or (datetime.now() - last_bonus_time).days >= 1:
            new_score = score + 100
            cursor.execute('UPDATE user_scores SET score = ?, last_bonus_time = ? WHERE user_id = ?',
                           (new_score, datetime.now(), user_id))
            conn.commit()
            await query.answer("Вы получили ежедневный бонус в размере 100 $LIST!", show_alert=True)
        else:
            await query.answer("Вы уже получили ежедневный бонус. Попробуйте снова через 24 часа.", show_alert=True)
    else:
        await query.answer("Произошла ошибка. Пожалуйста, попробуйте позже.", show_alert=True)


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    keyboard = [
        [InlineKeyboardButton("Добавить $LIST", callback_data='admin_add')],
        [InlineKeyboardButton("Убавить $LIST", callback_data='admin_remove')],
        [InlineKeyboardButton("Забанить пользователя", callback_data='admin_ban')],
        [InlineKeyboardButton("Разбанить пользователя", callback_data='admin_unban')],
        [InlineKeyboardButton("Просмотреть баланс пользователя", callback_data='admin_check_balance')],
        [InlineKeyboardButton("Сбросить дневной лимит нажатий пользователя", callback_data='admin_reset_daily_limit')],
        [InlineKeyboardButton("Рассылка сообщений", callback_data='admin_broadcast_instruction')],
        [InlineKeyboardButton("Отправить сообщение пользователю", callback_data='admin_message_instruction')],
        [InlineKeyboardButton("Назад", callback_data='back')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)


async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Кликать!", callback_data='click')],
        [InlineKeyboardButton("🏆Реферальная система", callback_data='referral')],
        [InlineKeyboardButton("ℹ️Информация", callback_data='info')],
        [InlineKeyboardButton("💸Ежедневный бонус", callback_data='daily_bonus')],
        [InlineKeyboardButton("📝Задания", callback_data='tasks')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text='Вы вернулись в главное меню. Выберите действие:',
        reply_markup=reply_markup
    )


async def admin_message_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    await query.edit_message_text("Чтобы отправить сообщение пользователю, введите команду /message <user_id> <сообщение>")


async def admin_broadcast_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    await query.edit_message_text("Чтобы сделать рассылку сообщений, введите команду /broadcast <сообщение>")


async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    message = ' '.join(context.args)
    if not message:
        await update.message.reply_text("Пожалуйста, введите сообщение для рассылки.")
        return

    cursor.execute('SELECT user_id FROM user_scores')
    users = cursor.fetchall()

    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=message)
            logging.info(f"Message sent to {user[0]}")
        except Exception as e:
            logging.error(f"Error sending message to {user[0]}: {e}")

    await update.message.reply_text("Сообщение отправлено всем пользователям.")


async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        user_id = int(context.args[0])
        message = ' '.join(context.args[1:])
    except (IndexError, ValueError):
        await update.message.reply_text("Используйте правильный формат: /message <user_id> <сообщение>")
        return

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        await update.message.reply_text(f"Сообщение отправлено пользователю {user_id}.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")


async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    await query.edit_message_text("Введите команду в формате /add <user_id> <amount>")


async def admin_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    await query.edit_message_text("Введите команду в формате /remove <user_id> <amount>")


async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    await query.edit_message_text("Введите команду в формате /ban <user_id>")


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    await query.edit_message_text("Введите команду в формате /unban <user_id>")


async def admin_check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    await query.edit_message_text("Введите команду в формате /check_balance <user_id>")


async def admin_reset_daily_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("У вас нет прав администратора.")
        return

    await query.answer()
    await query.edit_message_text("Введите команду в формате /reset_daily_limit <user_id>")


async def add_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Используйте правильный формат: /add <user_id> <amount>")
        return

    cursor.execute('UPDATE user_scores SET score = score + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    await update.message.reply_text(f"Пользователю {user_id} добавлено {amount:.2f} $LIST.")


async def remove_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Используйте правильный формат: /remove <user_id> <amount>")
        return

    cursor.execute('UPDATE user_scores SET score = score - ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    await update.message.reply_text(f"У пользователя {user_id} убавлено {amount:.2f} $LIST.")


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Используйте правильный формат: /ban <user_id>")
        return

    banned_users.add(user_id)
    await update.message.reply_text(f"Пользователь {user_id} забанен.")


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Используйте правильный формат: /unban <user_id>")
        return

    banned_users.discard(user_id)
    await update.message.reply_text(f"Пользователь {user_id} разбанен.")


async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Используйте правильный формат: /check_balance <user_id>")
        return

    cursor.execute('SELECT score FROM user_scores WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()
    if user_data is None:
        await update.message.reply_text("Пользователь не найден.")
        return

    await update.message.reply_text(f"Баланс пользователя {user_id}: {user_data[0]:.2f} $LIST")


async def reset_daily_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        user_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Используйте правильный формат: /reset_daily_limit <user_id>")
        return

    cursor.execute('UPDATE user_scores SET daily_points = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    await update.message.reply_text(f"Дневной лимит нажатий для пользователя {user_id} сброшен.")


def main() -> None:
    application = ApplicationBuilder().token("6785201390:AAF1Lg0qdOglWLWgvQkjyHOd2ZaL5QTYNUs").build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button, pattern='click'))
    application.add_handler(CallbackQueryHandler(info, pattern='info'))
    application.add_handler(CallbackQueryHandler(referral, pattern='referral'))
    application.add_handler(CallbackQueryHandler(tasks, pattern='tasks'))
    application.add_handler(CallbackQueryHandler(handle_daily_bonus, pattern='daily_bonus'))
    application.add_handler(CallbackQueryHandler(back_to_main_menu, pattern='back'))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CallbackQueryHandler(tasks, pattern='tasks'))
    application.add_handler(CommandHandler("admin", admin_menu))
    application.add_handler(CallbackQueryHandler(admin_add, pattern='admin_add'))
    application.add_handler(CallbackQueryHandler(admin_remove, pattern='admin_remove'))
    application.add_handler(CallbackQueryHandler(admin_ban, pattern='admin_ban'))
    application.add_handler(CallbackQueryHandler(admin_unban, pattern='admin_unban'))
    application.add_handler(CallbackQueryHandler(admin_check_balance, pattern='admin_check_balance'))
    application.add_handler(CallbackQueryHandler(admin_reset_daily_limit, pattern='admin_reset_daily_limit'))
    application.add_handler(CommandHandler("add", add_points))
    application.add_handler(CommandHandler("remove", remove_points))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("check_balance", check_balance))
    application.add_handler(CommandHandler("reset_daily_limit", reset_daily_limit))
    application.add_handler(CommandHandler("broadcast", broadcast_message))
    application.add_handler(CommandHandler("message", send_message))
    application.add_handler(CallbackQueryHandler(admin_message_instruction, pattern='admin_message_instruction'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_instruction, pattern='admin_broadcast_instruction'))
    application.add_handler(CallbackQueryHandler(check_subscription, pattern=r'check_subscription_.*'))

    application.run_polling()

if __name__ == '__main__':
    main()


