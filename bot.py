import os
import logging
import asyncio
import aiohttp
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants for conversation states
(
    START_CHOICE,
    PURCHASE_PRICE,
    CURRENCY,
    MANUFACTURE_DATE,
    ENGINE_VOLUME,
    HORSEPOWER,
    IMPORTER_TYPE
) = range(7)

class CustomsCalculator:
    """Class to handle customs calculations based on actual rates"""
    
    def __init__(self, exchange_rates=None):
        # Exchange rates (будут обновляться автоматически)
        self.exchange_rates = exchange_rates or {
            'USD': 77.0,     # 1 Доллар США = 77 российских рублей (по умолчанию)
            'CNY': 11.0,     # 1 Китайский Юань = 11 российских рублей (по умолчанию)
            'EUR': 91.0,     # 1 Евро = 91 российский рубль (по умолчанию)
            'KRW': 0.052     # 1 Корейская вона = 0,052 российский рубль (по умолчанию)
        }
        
        # Таможенная пошлина для авто 3-5 лет (физические лица) в евро за 1 см³
        self.duty_rates_3_5_years = [
            (0, 1000, 1.5),      # до 1000 см³
            (1000, 1500, 1.7),   # 1000-1500 см³
            (1500, 1800, 2.5),   # 1500-1800 см³
            (1800, 2300, 2.7),   # 1800-2300 см³
            (2300, 3000, 3.0),   # 2300-3000 см³
            (3000, float('inf'), 3.6)  # свыше 3000 см³
        ]
        
        # Утилизационный сбор 2026 года (в рублях)
        self.recycling_fee_2026 = {
            '1.0-2.0': {
                (160, 190): (900000, 1492800),      # 160 <= hp < 190
                (190, 220): (952000, 1584000),      # 190 <= hp < 220
                (220, 250): (1010400, 1677600),     # 220 <= hp < 250
                (250, 280): (1142400, 1838400),     # 250 <= hp < 280
                (280, 310): (1291200, 2011200),     # 280 <= hp < 310
                (310, 340): (1459200, 2203200),     # 310 <= hp < 340
            },
            '2.0-3.0': {
                (160, 190): (2306800, 3456000),     # 160 <= hp < 190
                (190, 220): (2364000, 3501600),     # 190 <= hp < 220
                (220, 250): (2402400, 3552000),     # 220 <= hp < 250
                (250, 280): (2520000, 3660000),     # 250 <= hp < 280
                (280, 310): (2620800, 3770400),     # 280 <= hp < 310
                (310, 340): (2726400, 3873600),     # 310 <= hp < 340
                (340, 370): (2834400, 3981600),     # 340 <= hp < 370
                (370, 400): (2949600, 4094400),     # 370 <= hp < 400
                (400, 500): (3448800, 4572000),     # 400 <= hp < 500
                (500, float('inf')): (3448800, 4572000),  # hp >= 500
            }
        }
    
    def update_exchange_rates(self, new_rates):
        """Update exchange rates"""
        self.exchange_rates.update(new_rates)
    
    def calculate_age(self, manufacture_date):
        """Точно вычисляет возраст автомобиля в годах и месяцах на текущую дату"""
        today = date.today()
        
        # Рассчитываем полное количество месяцев разницы
        total_months = (today.year - manufacture_date.year) * 12 + (today.month - manufacture_date.month)
        
        # Учитываем дни: если текущий день месяца меньше дня производства, вычитаем 1 месяц
        if today.day < manufacture_date.day:
            total_months -= 1
        
        # Возраст в полных годах
        years = total_months // 12
        
        # Остаточные месяцы
        months = total_months % 12
        
        # Возраст в полных годах для расчетов (округляем вниз)
        age_years = years
        
        # Учитываем, что если возраст 0 лет, но есть месяцы - это все равно возраст 0 лет
        # Для расчета пошлин важны полные годы
        return age_years, months
    
    def get_duty_for_3_5_years(self, engine_volume_cm3):
        """Calculate duty for cars 3-5 years old in euros"""
        for min_vol, max_vol, rate in self.duty_rates_3_5_years:
            if min_vol < engine_volume_cm3 <= max_vol:
                return engine_volume_cm3 * rate
        return engine_volume_cm3 * 3.6
    
    def get_recycling_fee(self, engine_volume_l, hp, age_years):
        """Get recycling fee based on volume, HP and age with special cases"""
        engine_volume_float = float(engine_volume_l)
        
        # ОСОБЫЕ СЛУЧАИ (льготные тарифы)
        if engine_volume_float <= 3.0 and hp <= 160:  # <= 160 л.с. ВКЛЮЧИТЕЛЬНО
            if age_years < 3:  # возраст 0-2 года (3 не включительно)
                return 3400
            elif 3 <= age_years <= 5:  # возраст 3-5 лет (ВКЛЮЧИТЕЛЬНО)
                return 5200
        
        # Определяем категорию объема
        volume_category = None
        
        if engine_volume_float <= 2.0:  # 1.0 <= volume <= 2.0
            volume_category = '1.0-2.0'
        else:  # 2.0 < volume <= 3.0
            volume_category = '2.0-3.0'
        
        # Выбираем таблицу тарифов
        fee_table = self.recycling_fee_2026.get(volume_category, {})
        
        if not fee_table:
            # Если категории нет, используем базовую ставку
            logger.warning(f"Не найдена таблица тарифов для категории: {volume_category}")
            if age_years <= 3:
                return 20000
            else:
                return 30000
        
        # Ищем подходящий диапазон лошадиных сил
        target_range = None
        fee_values = None
        
        for hp_range in sorted(fee_table.keys()):
            min_hp, max_hp = hp_range
            # Важно: нижняя граница ВКЛЮЧИТЕЛЬНО, верхняя НЕ включительно
            if min_hp <= hp < max_hp:
                target_range = hp_range
                fee_values = fee_table[hp_range]
                break
        
        # Если не нашли диапазон, берем максимальный доступный
        if target_range is None:
            sorted_ranges = sorted(fee_table.keys(), key=lambda x: x[0])
            if sorted_ranges:
                target_range = sorted_ranges[-1]
                fee_values = fee_table[target_range]
            else:
                if age_years <= 3:
                    return 20000
                else:
                    return 30000
        
        # Получаем значение утильсбора в зависимости от возраста
        if age_years <= 3:  # 0-3 года (3 включительно)
            return fee_values[0]  # 0-3 года
        else:  # старше 3 лет
            return fee_values[1]  # старше 3 лет
    
    def calculate_customs(self, purchase_price, currency, manufacture_date_str, engine_volume, hp, importer_type):
        """
        Calculate customs duties based on the provided parameters
        """
        # Convert purchase price to RUB
        rub_price = purchase_price * self.exchange_rates.get(currency, 1)
        
        # Calculate vehicle age (точный расчет)
        today = date.today()
        try:
            manufacture_date_obj = datetime.strptime(manufacture_date_str, "%Y-%m-%d").date()
        except ValueError:
            # Если дата в другом формате, попробуем преобразовать
            try:
                manufacture_date_obj = datetime.strptime(manufacture_date_str, "%d.%m.%Y").date()
            except ValueError:
                # По умолчанию используем сегодняшнюю дату
                manufacture_date_obj = today
        
        # Вычисляем точный возраст
        age_years, age_months = self.calculate_age(manufacture_date_obj)
        
        # Convert engine volume to cm³ for calculations
        engine_volume_cm3 = engine_volume * 1000
        
        # Получаем утилизационный сбор
        recycling_fee = self.get_recycling_fee(engine_volume, hp, age_years)
        
        # Determine calculation method based on age
        if age_years < 1:
            # Для автомобилей младше 1 года - 48% от стоимости + утильсбор
            customs_duty = rub_price * 0.48
            duty_type = "48% от инвойса"
            
        elif 1 <= age_years <= 3:
            # Для автомобилей 1-3 года - 48% от стоимости + утильсбор
            customs_duty = rub_price * 0.48
            duty_type = "48% от инвойса"
            
        elif 3 < age_years <= 5:
            # Для автомобилей 3-5 лет - фиксированная пошлина в евро + утильсбор
            duty_euro = self.get_duty_for_3_5_years(engine_volume_cm3)
            customs_duty = duty_euro * self.exchange_rates['EUR']
            duty_type = f"Фиксированная пошлина: {duty_euro:,.0f} EUR"
            
        else:
            # Для автомобилей старше 5 лет - 48% от стоимости + утильсбор
            customs_duty = rub_price * 0.48
            duty_type = "48% от инвойса (старше 5 лет)"
        
        total = customs_duty + recycling_fee
        
        return {
            'purchase_price': purchase_price,
            'currency': currency,
            'vehicle_age_years': age_years,
            'vehicle_age_months': age_months,
            'engine_volume': engine_volume,
            'horsepower': hp,
            'importer_type': importer_type,
            'customs_duty': round(customs_duty),
            'recycling_fee': recycling_fee,  # уже в рублях
            'total_payable': round(total),
            'duty_type': duty_type,
            'rub_price': round(rub_price),
            'manufacture_date': manufacture_date_obj.strftime("%d.%m.%Y")
        }

async def update_exchange_rates(context: ContextTypes.DEFAULT_TYPE):
    """Update exchange rates from external source"""
    try:
        calculator = context.bot_data.get('calculator')
        if not calculator:
            return
        
        # Используем API Центрального Банка России для USD и EUR
        # Используем API exchangerate-api.com или аналогичные для CNY и KRW
        async with aiohttp.ClientSession() as session:
            # Получаем курсы ЦБ РФ
            url_cbr = 'https://www.cbr-xml-daily.ru/daily_json.js'
            async with session.get(url_cbr, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    usd_rate = data['Valute']['USD']['Value']
                    eur_rate = data['Valute']['EUR']['Value']
                    
                    # Обновляем курсы
                    calculator.update_exchange_rates({
                        'USD': round(usd_rate, 2),
                        'EUR': round(eur_rate, 2)
                    })
                    
                    logger.info(f"Курсы обновлены: USD={usd_rate:.2f}, EUR={eur_rate:.2f}")
        
        # Для CNY и KRW используем другой источник (например, открытый API)
        try:
            # Используем API с фиксированными курсами для CNY и KRW
            # В реальном приложении нужно использовать актуальный API
            # Например: https://api.exchangerate-api.com/v4/latest/RUB
            url_exchange = 'https://api.exchangerate-api.com/v4/latest/USD'
            async with session.get(url_exchange, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    # Получаем курсы через USD
                    usd_to_cny = data['rates']['CNY']
                    usd_to_krw = data['rates']['KRW']
                    
                    # Рассчитываем курсы валют к рублю через USD
                    usd_rub = calculator.exchange_rates['USD']
                    cny_rub = round(usd_rub / usd_to_cny, 4)
                    krw_rub = round(usd_rub / usd_to_krw, 6)
                    
                    calculator.update_exchange_rates({
                        'CNY': cny_rub,
                        'KRW': krw_rub
                    })
                    
                    logger.info(f"Курсы обновлены: CNY={cny_rub}, KRW={krw_rub}")
        except Exception as e:
            logger.warning(f"Не удалось обновить курсы CNY/KRW: {e}")
            # Используем фиксированные значения как запасной вариант
            calculator.update_exchange_rates({
                'CNY': 11.0,
                'KRW': 0.052
            })
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении курсов валют: {e}")
        # Используем значения по умолчанию в случае ошибки
        calculator = context.bot_data.get('calculator')
        if calculator:
            calculator.update_exchange_rates({
                'USD': 77.0,
                'CNY': 11.0,
                'EUR': 91.0,
                'KRW': 0.052
            })

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    keyboard = [
        [KeyboardButton("Рассчитать таможню")],
        [KeyboardButton("Информация о боте")],
        [KeyboardButton("Текущие курсы валют")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🚗 Добро пожаловать в бот для расчета таможенных пошлин на легковые автомобили!\n\n"
        "Для начала расчета нажмите кнопку 'Рассчитать таможню'.\n\n"
        "📋 Бот запросит следующую информацию:\n"
        "• Стоимость покупки автомобиля\n"
        "• Валюту стоимости\n"
        "• Дату производства автомобиля\n"
        "• Объем двигателя в литрах\n"
        "• Количество лошадиных сил\n"
        "• Тип импортера",
        reply_markup=reply_markup
    )
    
    return START_CHOICE

async def handle_start_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle choice from start menu"""
    text = update.message.text
    
    if text == "Рассчитать таможню":
        await update.message.reply_text(
            "💰 Введите стоимость покупки автомобиля (инвойс) в числовом формате.\n"
            "Пример: 15000 или 15000.50"
        )
        return PURCHASE_PRICE
    
    elif text == "Информация о боте":
        info_text = (
            "📊 Этот бот рассчитывает таможенные пошлины для легковых автомобилей для личного пользования.\n\n"
            "📈 Методика расчета:\n"
            "• До 1 года: 48% от стоимости инвойса + утилизационный сбор\n"
            "• 1-3 года: 48% от стоимости инвойса + утилизационный сбор\n"
            "• 3-5 лет: фиксированная пошлина в евро (зависит от объема) + утилизационный сбор\n"
            "• Старше 5 лет: 48% от стоимости инвойса + утилизационный сбор\n\n"
            "♻️ Утилизационный сбор (2026 год):\n"
            "• Льготные тарифы:\n"
            "  - До 3.0л и до 160 л.с. (включительно), возраст 0-3 года: 3,400 руб\n"
            "  - До 3.0л и до 160 л.с. (включительно), возраст 3-5 лет: 5,200 руб\n"
            "• Таблица ставок (2026 год):\n"
            "  - 1.0-2.0 литра: от 900,000 до 2,203,200 руб\n"
            "  - 2.0-3.0 литра: от 2,306,800 до 4,572,000 руб\n\n"
            "📅 Возраст автомобиля рассчитывается точно на текущую дату.\n"
            "💱 Курсы валют обновляются автоматически из внешних источников.\n\n"
            "📊 Диапазоны мощностей:\n"
            "• 160-190 л.с. (160 включительно, 190 не включительно)\n"
            "• 190-220 л.с. (190 включительно, 220 не включительно)\n"
            "• 220-250 л.с. (220 включительно, 250 не включительно)\n"
            "• 250-280 л.с. (250 включительно, 280 не включительно)\n"
            "• 280-310 л.с. (280 включительно, 310 не включительно)\n"
            "• 310-340 л.с. (310 включительно, 340 не включительно)\n"
            "• 340-370 л.с. (340 включительно, 370 не включительно)\n"
            "• 370-400 л.с. (370 включительно, 400 не включительно)\n"
            "• 400-500 л.с. (400 включительно, 500 не включительно)\n"
            "• Свыше 500 л.с. (500 включительно)"
        )
        
        await update.message.reply_text(info_text)
        
        # Возвращаемся в меню
        keyboard = [
            [KeyboardButton("Рассчитать таможню")],
            [KeyboardButton("Информация о боте")],
            [KeyboardButton("Текущие курсы валют")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Что вы хотите сделать?", reply_markup=reply_markup)
        return START_CHOICE
    
    elif text == "Текущие курсы валют":
        calculator = context.bot_data.get('calculator')
        if calculator:
            rates = calculator.exchange_rates
            rates_text = (
                "💱 ТЕКУЩИЕ КУРСЫ ВАЛЮТ (автоматическое обновление):\n"
                "═══════════════════════════════\n"
                f"🇺🇸 1 USD (Доллар США) = {rates['USD']:.2f} RUB\n"
                f"🇪🇺 1 EUR (Евро) = {rates['EUR']:.2f} RUB\n"
                f"🇨🇳 1 CNY (Китайский Юань) = {rates['CNY']:.2f} RUB\n"
                f"🇰🇷 1 KRW (Корейская Вона) = {rates['KRW']:.6f} RUB\n"
                "═══════════════════════════════\n"
                "*Курсы обновляются автоматически каждый час*\n"
                "Последнее обновление: сегодня"
            )
        else:
            rates_text = "Калькулятор курсов валют не инициализирован."
        
        await update.message.reply_text(rates_text)
        
        keyboard = [
            [KeyboardButton("Рассчитать таможню")],
            [KeyboardButton("Информация о боте")],
            [KeyboardButton("Текущие курсы валют")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Что вы хотите сделать?", reply_markup=reply_markup)
        return START_CHOICE
    
    else:
        await update.message.reply_text("Пожалуйста, используйте кнопки для навигации.")
        return START_CHOICE

async def get_purchase_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get purchase price from user"""
    try:
        price = float(update.message.text.replace(',', '.'))
        if price <= 0:
            await update.message.reply_text("❌ Стоимость должна быть положительным числом. Попробуйте снова.")
            return PURCHASE_PRICE
            
        context.user_data['purchase_price'] = price
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("USD ($)", callback_data="currency_USD"),
             InlineKeyboardButton("EUR (€)", callback_data="currency_EUR")],
            [InlineKeyboardButton("CNY (¥)", callback_data="currency_CNY"),
             InlineKeyboardButton("KRW (₩)", callback_data="currency_KRW")]
        ])
        
        await update.message.reply_text(
            "💱 Выберите валюту стоимости автомобиля:",
            reply_markup=keyboard
        )
        return CURRENCY
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректную стоимость в числовом формате (например: 15000).")
        return PURCHASE_PRICE

async def get_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get currency from inline keyboard"""
    query = update.callback_query
    await query.answer()
    
    currency = query.data.split('_')[1]
    context.user_data['currency'] = currency
    
    await query.edit_message_text(
        f"✅ Валюта: {currency}\n\n"
        "📅 Введите дату производства автомобиля в формате ГГГГ-ММ-ДД.\n"
        "Пример: 2022-05-15 или 15.05.2022"
    )
    return MANUFACTURE_DATE

async def get_manufacture_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get manufacture date from user"""
    date_text = update.message.text
    today = date.today()
    
    try:
        # Пробуем разные форматы даты
        try:
            date_obj = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            date_obj = datetime.strptime(date_text, "%d.%m.%Y").date()
        
        # Проверяем, что дата не в будущем
        if date_obj > today:
            await update.message.reply_text(
                "❌ Дата производства не может быть в будущем. Введите корректную дату.\n"
                "Пример: 2022-05-15 или 15.05.2022"
            )
            return MANUFACTURE_DATE
        
        # Проверяем, что дата не слишком старая (например, старше 50 лет)
        if date_obj.year < today.year - 50:
            await update.message.reply_text(
                "❌ Дата производства слишком старая. Введите корректную дату.\n"
                "Пример: 2022-05-15 или 15.05.2022"
            )
            return MANUFACTURE_DATE
            
        context.user_data['manufacture_date'] = date_text
        await update.message.reply_text(
            "⚙️ Введите объем двигателя в литрах.\n"
            "Пример: 1.4 или 2.0"
        )
        return ENGINE_VOLUME
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите корректную дату в формате:\n"
            "• ГГГГ-ММ-ДД (например: 2022-05-15)\n"
            "• ДД.ММ.ГГГГ (например: 15.05.2022)"
        )
        return MANUFACTURE_DATE

async def get_engine_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get engine volume from user"""
    try:
        volume = float(update.message.text.replace(',', '.'))
        if volume <= 0 or volume > 10:
            await update.message.reply_text("❌ Объем двигателя должен быть положительным числом и не более 10 литров. Попробуйте снова.")
            return ENGINE_VOLUME
            
        context.user_data['engine_volume'] = volume
        await update.message.reply_text(
            "🐎 Введите количество лошадиных сил (мощность).\n"
            "Пример: 150 или 245\n\n"
            "⚠️ Внимание: используется таблица 2026 года!"
        )
        return HORSEPOWER
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректный объем двигателя в числовом формате (например: 2.0).")
        return ENGINE_VOLUME

async def get_horsepower(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get horsepower from user"""
    try:
        hp = int(update.message.text)
        if hp <= 0 or hp > 2000:
            await update.message.reply_text("❌ Количество лошадиных сил должно быть положительным числом и не более 2000. Попробуйте снова.")
            return HORSEPOWER
            
        context.user_data['horsepower'] = hp
        
        keyboard = [
            [KeyboardButton("Физическое лицо")],
            [KeyboardButton("Юридическое лицо")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "👤 Выберите тип импортера:",
            reply_markup=reply_markup
        )
        return IMPORTER_TYPE
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректное количество лошадиных сил в числовом формате (например: 150).")
        return HORSEPOWER

async def get_importer_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get importer type from user"""
    text = update.message.text
    
    if text in ["Физическое лицо", "Юридическое лицо"]:
        context.user_data['importer_type'] = text
        
        # Выполняем расчет
        try:
            calculator = context.bot_data.get('calculator')
            if not calculator:
                await update.message.reply_text("❌ Ошибка: калькулятор не инициализирован. Попробуйте позже.")
                return START_CHOICE
            
            result = calculator.calculate_customs(
                purchase_price=context.user_data['purchase_price'],
                currency=context.user_data['currency'],
                manufacture_date_str=context.user_data['manufacture_date'],
                engine_volume=context.user_data['engine_volume'],
                hp=context.user_data['horsepower'],
                importer_type=text
            )
            
            # Определяем тип утильсбора для информационного сообщения
            recycling_fee_type = "по таблице 2026 года"
            if result['engine_volume'] <= 3.0 and result['horsepower'] <= 160:
                if result['vehicle_age_years'] < 3:
                    recycling_fee_type = "льготный (0-3 года, до 160 л.с.)"
                elif 3 <= result['vehicle_age_years'] <= 5:
                    recycling_fee_type = "льготный (3-5 лет, до 160 л.с.)"
            
            # Форматируем и отправляем результаты
            response = (
                f"📊 РЕЗУЛЬТАТЫ РАСЧЕТА ТАМОЖНИ\n"
                f"═══════════════════════════════\n"
                f"💰 Стоимость покупки: {result['purchase_price']:,.2f} {result['currency']}\n"
                f"   (≈ {result['rub_price']:,} RUB)\n"
                f"📅 Дата производства: {result['manufacture_date']}\n"
                f"📅 Возраст автомобиля: {result['vehicle_age_years']} лет {result['vehicle_age_months']} месяцев\n"
                f"⚙️ Объем двигателя: {result['engine_volume']} л ({result['engine_volume']*1000:.0f} см³)\n"
                f"🐎 Мощность: {result['horsepower']} л.с.\n"
                f"👤 Тип импортера: {result['importer_type']}\n"
                f"═══════════════════════════════\n"
                f"📝 Тип расчета: {result['duty_type']}\n"
                f"📝 Таможенная пошлина: {result['customs_duty']:,} RUB\n"
                f"♻️ Утилизационный сбор ({recycling_fee_type}): {result['recycling_fee']:,} RUB\n"
                f"═══════════════════════════════\n"
                f"💵 ВСЕГО К ОПЛАТЕ: {result['total_payable']:,} RUB\n"
                f"═══════════════════════════════\n\n"
                f"*Расчет выполнен для физических лиц на 2026 год.\n"
                f"Курс EUR = {calculator.exchange_rates['EUR']:.2f} RUB\n"
                f"Курс USD = {calculator.exchange_rates['USD']:.2f} RUB"
            )
            
            await update.message.reply_text(response)
            
        except Exception as e:
            logger.error(f"Ошибка расчета: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Произошла ошибка при расчете. Пожалуйста, проверьте введенные данные:\n"
                "• Объем двигателя должен быть от 0.1 до 10 литров\n"
                "• Мощность должна быть от 1 до 2000 л.с.\n"
                "• Дата производства не должна быть в будущем\n"
                "• Стоимость должна быть положительной"
            )
        
        # Возвращаемся в главное меню
        keyboard = [
            [KeyboardButton("Рассчитать таможню")],
            [KeyboardButton("Информация о боте")],
            [KeyboardButton("Текущие курсы валют")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "✅ Расчет завершен! Вы можете начать новый расчет или получить информацию о боте.",
            reply_markup=reply_markup
        )
        
        return START_CHOICE
    else:
        keyboard = [
            [KeyboardButton("Физическое лицо")],
            [KeyboardButton("Юридическое лицо")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "❌ Пожалуйста, выберите тип импортера из предложенных вариантов.",
            reply_markup=reply_markup
        )
        return IMPORTER_TYPE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    keyboard = [
        [KeyboardButton("Рассчитать таможню")],
        [KeyboardButton("Информация о боте")],
        [KeyboardButton("Текущие курсы валют")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "❌ Операция отменена. Что вы хотите сделать?",
        reply_markup=reply_markup
    )
    return START_CHOICE

async def post_init(application: Application):
    """Initialize after bot starts"""
    # Create calculator instance
    calculator = CustomsCalculator()
    application.bot_data['calculator'] = calculator
    
    # Update exchange rates immediately
    await update_exchange_rates(application)
    
    # Schedule regular updates every hour
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(update_exchange_rates, interval=3600, first=3600)  # Every hour

def main():
    """Run the bot"""
    # ВАЖНО: Замените токен на свой реальный токен!
    TOKEN = ""
    
    if not TOKEN or TOKEN == "ВАШ_ТОКЕН_БОТА":
        logger.error("❌ Токен бота не настроен! Замените TOKEN на реальный токен.")
        return
    
    # Create application with job queue
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # Create conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            START_CHOICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_start_choice)
            ],
            PURCHASE_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_purchase_price)
            ],
            CURRENCY: [
                CallbackQueryHandler(get_currency)
            ],
            MANUFACTURE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_manufacture_date)
            ],
            ENGINE_VOLUME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_engine_volume)
            ],
            HORSEPOWER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_horsepower)
            ],
            IMPORTER_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_importer_type)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('help', start))
    application.add_handler(CommandHandler('rates', handle_start_choice))

    # Run the bot
    logger.info("🤖 Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Install required packages: pip install aiohttp python-telegram-bot
    main()
