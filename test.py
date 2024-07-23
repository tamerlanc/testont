import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


# Функция, которая вызывается при старте
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Кликать!", callback_data='click')],
        [InlineKeyboardButton("Реферальная система", callback_data='referral')],
        [InlineKeyboardButton("Информация", callback_data='info')],
        [InlineKeyboardButton("Задания", callback_data='tasks')]  # Добавляем кнопку "Задания"
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        'Добро пожаловать в бота-кликера! Нажмите "Клик!" чтобы начать или "Реферальная система" для получения ссылки.',
        reply_markup=reply_markup
    )


# Функция для отображения заданий
async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    # Пример списка заданий, вы можете заполнить его своими заданиями
    tasks = [
        "Задание 1: Описание задания 1",
        "Задание 2: Описание задания 2",
        "Задание 3: Описание задания 3",
        # Добавьте сюда свои задания
    ]

    tasks_text = "\n".join(tasks)

    keyboard = [
        [InlineKeyboardButton("Назад", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=f"Список заданий:\n\n{tasks_text}",
        reply_markup=reply_markup
    )


# Функция для возврата в главное меню
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Кликать!", callback_data='click')],
        [InlineKeyboardButton("Реферальная система", callback_data='referral')],
        [InlineKeyboardButton("Информация", callback_data='info')],
        [InlineKeyboardButton("Задания", callback_data='tasks')]  # Добавляем кнопку "Задания"
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text='Вы вернулись в главное меню. Выберите действие:',
        reply_markup=reply_markup
    )


# Обработчик для всех callback_data
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    else:
        # Ваш существующий код для обработки других кнопок
        if query.data == 'click':
            await query.answer(text='Вы нажали "Кликать!"')
        elif query.data == 'referral':
            await query.answer(text='Система рефералов пока не реализована.')
        elif query.data == 'info':
            await query.answer(text='Информация о боте.')
        else:
            await query.answer(text='Неизвестная команда.')


def main() -> None:
    # Создаем приложение и передаем ему токен вашего бота
    application = ApplicationBuilder().token("6785201390:AAF1Lg0qdOglWLWgvQkjyHOd2ZaL5QTYNUs").build()

    # Регистрируем обработчики команд и callback'ов
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))

    # Запускаем бота
    application.run_polling()


if __name__ == '__main__':
    main()
