import os
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants for conversation states
(
    PURCHASE_PRICE,
    CURRENCY,
    MANUFACTURE_DATE,
    ENGINE_VOLUME,
    HORSEPOWER,
    IMPORTER_TYPE
) = range(6)

class CustomsCalculator:
    """Class to handle customs calculations"""
    
    def __init__(self):
        # Exchange rates (these would normally come from an API)
        self.exchange_rates = {
            'USD': 90.0,  # условные курсы для примера
            'CNY': 12.5,
            'KRW': 0.07
        }
        
        # Customs duty rates for cars 3-5 years old based on engine volume
        self.duty_rates_3_5_years = {
            (0, 1.0): 2.5,
            (1.0, 1.5): 2.7,
            (1.5, 2.0): 3.0,
            (2.0, 3.0): 3.5,
            (3.0, 5.0): 4.8
        }
        
        # Fixed recycling fees for cars 3-5 years old
        self.recycling_fee_3_5_years_up_to_160hp = 5200
        
        # Recycling fee multipliers for cars 3-5 years old with >160 hp
        self.recycling_fee_multipliers_3_5_years = {
            (0, 1.0): 1.0,
            (1.0, 1.5): 1.2,
            (1.5, 2.0): 1.5,
            (2.0, 3.0): 2.0,
            (3.0, 5.0): 3.0
        }
        
        # Horsepower multipliers for cars 3-5 years old with >160 hp
        self.hp_multipliers_3_5_years = {
            (160, 200): 1.2,
            (200, 250): 1.5,
            (250, 300): 2.0,
            (300, 500): 3.0
        }

    def get_recycling_fee_1_3_years(self, hp):
        """Calculate recycling fee for cars 1-3 years old based on horsepower"""
        if hp <= 160:
            # Standard rate for up to 160 hp
            return 20000  # примерная ставка
        else:
            # Higher rate for over 160 hp
            base_fee = 20000
            # Additional fee based on horsepower
            extra_fee = (hp - 160) * 50  # примерный расчет
            return base_fee + min(extra_fee, 50000)  # ограничение сверху

    def get_duty_rate_3_5_years(self, engine_volume):
        """Get duty rate for cars 3-5 years old based on engine volume"""
        for (min_vol, max_vol), rate in self.duty_rates_3_5_years.items():
            if min_vol < engine_volume <= max_vol:
                return rate
        return 4.8  # максимальная ставка для объемов >3.0L

    def get_recycling_fee_3_5_years(self, engine_volume, hp):
        """Calculate recycling fee for cars 3-5 years old"""
        if hp <= 160:
            return self.recycling_fee_3_5_years_up_to_160hp
        else:
            # Calculate multiplier based on engine volume
            vol_multiplier = 1.0
            for (min_vol, max_vol), mult in self.recycling_fee_multipliers_3_5_years.items():
                if min_vol < engine_volume <= max_vol:
                    vol_multiplier = mult
                    break
            
            # Calculate multiplier based on horsepower
            hp_multiplier = 1.0
            for (min_hp, max_hp), mult in self.hp_multipliers_3_5_years.items():
                if min_hp <= hp < max_hp:
                    hp_multiplier = mult
                    break
            if hp >= 500:  # если лошадей больше 500
                hp_multiplier = 5.0
            
            # Base fee for cars over 160 hp
            base_fee = 15000  # примерная базовая ставка для автомобилей >160 л.с.
            return int(base_fee * vol_multiplier * hp_multiplier)

    def calculate_customs(self, purchase_price, currency, manufacture_date, engine_volume, hp, importer_type):
        """
        Calculate customs duties based on the provided parameters
        """
        # Convert purchase price to RUB
        rub_price = purchase_price * self.exchange_rates.get(currency, 1)
        
        # Calculate vehicle age
        today = date.today()
        manufacture_date_obj = datetime.strptime(manufacture_date, "%Y-%m-%d").date()
        age = today.year - manufacture_date_obj.year - ((today.month, today.day) < (manufacture_date_obj.month, manufacture_date_obj.day))
        
        # Determine calculation method based on age
        if 1 <= age <= 3:
            # For cars 1-3 years old: 48% of invoice + recycling fee
            customs_duty = rub_price * 0.48
            recycling_fee = self.get_recycling_fee_1_3_years(hp)
        elif 3 < age <= 5:
            # For cars 3-5 years old: fixed duty based on engine volume + recycling fee
            duty_rate = self.get_duty_rate_3_5_years(engine_volume)
            customs_duty = duty_rate * engine_volume * 1000  # примерный расчет
            recycling_fee = self.get_recycling_fee_3_5_years(engine_volume, hp)
        else:
            # For cars older than 5 years or newer than 1 year
            if age < 1:
                # Cars less than 1 year old
                customs_duty = rub_price * 0.50
                recycling_fee = self.get_recycling_fee_1_3_years(hp)
            else:
                # Cars older than 5 years - higher rates
                customs_duty = rub_price * 0.55
                recycling_fee = self.get_recycling_fee_3_5_years(engine_volume, hp)
        
        total = customs_duty + recycling_fee
        
        return {
            'purchase_price': purchase_price,
            'currency': currency,
            'vehicle_age': age,
            'engine_volume': engine_volume,
            'horsepower': hp,
            'importer_type': importer_type,
            'customs_duty': round(customs_duty),
            'recycling_fee': round(recycling_fee),
            'total_payable': round(total)
        }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    keyboard = [
        [KeyboardButton("Рассчитать таможню")],
        [KeyboardButton("Информация о боте")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "Добро пожаловать в бот для расчета таможенных пошлин на легковые автомобили!\n\n"
        "Для начала расчета нажмите кнопку 'Рассчитать таможню'.\n\n"
        "Бот запросит следующую информацию:\n"
        "- Стоимость покупки автомобиля\n"
        "- Валюту стоимости\n"
        "- Дату производства автомобиля\n"
        "- Объем двигателя\n"
        "- Количество лошадиных сил\n"
        "- Тип импортера (физическое или юридическое лицо)",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

async def calculate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the calculation conversation"""
    if update.message.text == "Рассчитать таможню":
        await update.message.reply_text(
            "Введите стоимость покупки автомобиля (инвойс) в числовом формате.\n"
            "Например: 15000"
        )
        return PURCHASE_PRICE
    
    elif update.message.text == "Информация о боте":
        await update.message.reply_text(
            "Этот бот рассчитывает таможенные пошлины для легковых автомобилей для личного пользования.\n\n"
            "Для автомобилей возрастом 1-3 года расчет производится от стоимости покупки (инвойса): "
            "48% от инвойса + утилизационный сбор в зависимости от количества лошадиных сил.\n\n"
            "Для автомобилей возрастом 3-5 лет применяется фиксированная таможня, "
            "зависящая от объема двигателя, плюс утилизационный сбор."
        )
        return ConversationHandler.END

async def get_purchase_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get purchase price from user"""
    try:
        price = float(update.message.text.replace(',', '.'))
        context.user_data['purchase_price'] = price
        await update.message.reply_text(
            "Выберите валюту стоимости автомобиля:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("USD ($)", callback_data="currency_USD"),
                 InlineKeyboardButton("CNY (¥)", callback_data="currency_CNY")],
                [InlineKeyboardButton("KRW (₩)", callback_data="currency_KRW")]
            ])
        )
        return CURRENCY
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректную стоимость в числовом формате.")
        return PURCHASE_PRICE

async def get_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get currency from inline keyboard"""
    query = update.callback_query
    await query.answer()
    
    currency = query.data.split('_')[1]
    context.user_data['currency'] = currency
    
    await query.edit_message_text(
        f"Валюта: {currency}\n\n"
        "Введите дату производства автомобиля в формате ГГГГ-ММ-ДД.\n"
        "Например: 2022-05-15"
    )
    return MANUFACTURE_DATE

async def get_manufacture_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get manufacture date from user"""
    try:
        date_obj = datetime.strptime(update.message.text, "%Y-%m-%d")
        context.user_data['manufacture_date'] = update.message.text
        await update.message.reply_text(
            "Введите объем двигателя в литрах.\n"
            "Например: 2.0"
        )
        return ENGINE_VOLUME
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректную дату в формате ГГГГ-ММ-ДД.")
        return MANUFACTURE_DATE

async def get_engine_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get engine volume from user"""
    try:
        volume = float(update.message.text.replace(',', '.'))
        context.user_data['engine_volume'] = volume
        await update.message.reply_text(
            "Введите количество лошадиных сил.\n"
            "Например: 150"
        )
        return HORSEPOWER
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректный объем двигателя в числовом формате.")
        return ENGINE_VOLUME

async def get_horsepower(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get horsepower from user"""
    try:
        hp = int(update.message.text)
        context.user_data['horsepower'] = hp
        await update.message.reply_text(
            "Выберите тип импортера:",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("Физическое лицо")],
                [KeyboardButton("Юридическое лицо")]
            ], resize_keyboard=True, one_time_keyboard=True)
        )
        return IMPORTER_TYPE
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное количество лошадиных сил в числовом формате.")
        return HORSEPOWER

async def get_importer_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get importer type from user"""
    importer_type = update.message.text
    if importer_type in ["Физическое лицо", "Юридическое лицо"]:
        context.user_data['importer_type'] = importer_type
        
        # Perform calculation
        calculator = CustomsCalculator()
        result = calculator.calculate_customs(
            purchase_price=context.user_data['purchase_price'],
            currency=context.user_data['currency'],
            manufacture_date=context.user_data['manufacture_date'],
            engine_volume=context.user_data['engine_volume'],
            hp=context.user_data['horsepower'],
            importer_type=importer_type
        )
        
        # Format and send results
        response = (
            f"Результаты расчета таможни:\n"
            f"────────────────────────────\n"
            f"Стоимость покупки: {result['purchase_price']:,.2f} {result['currency']}\n"
            f"Возраст автомобиля: {result['vehicle_age']} лет\n"
            f"Объем двигателя: {result['engine_volume']}L\n"
            f"Лошадиных сил: {result['horsepower']} HP\n"
            f"Тип импортера: {result['importer_type']}\n"
            f"────────────────────────────\n"
            f"Таможенная пошлина: {result['customs_duty']:,} RUB\n"
            f"Утилизационный сбор: {result['recycling_fee']:,} RUB\n"
            f"────────────────────────────\n"
            f"ВСЕГО К ОПЛАТЕ: {result['total_payable']:,} RUB\n"
            f"────────────────────────────"
        )
        
        await update.message.reply_text(response)
        
        # Return to main menu
        keyboard = [
            [KeyboardButton("Рассчитать таможню")],
            [KeyboardButton("Информация о боте")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "Расчет завершен! Вы можете начать новый расчет или получить информацию о боте.",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, выберите тип импортера из предложенных вариантов.")
        return IMPORTER_TYPE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    await update.message.reply_text(
        "Операция отменена. Нажмите /start для начала работы с ботом."
    )
    return ConversationHandler.END

def main():
    """Run the bot"""
    # Create the Application and pass it your bot's token
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    application = Application.builder().token(TOKEN).build()

    # Create conversation handler with the states
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            PURCHASE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_purchase_price)],
            CURRENCY: [CallbackQueryHandler(get_currency)],
            MANUFACTURE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_manufacture_date)],
            ENGINE_VOLUME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_engine_volume)],
            HORSEPOWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_horsepower)],
            IMPORTER_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_importer_type)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, calculate_start))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == '__main__':
    main()