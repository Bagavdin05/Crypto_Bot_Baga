import ccxt
import asyncio
import aiohttp
from telegram import Bot, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler
)
from telegram.error import TelegramError
import logging
from datetime import datetime, timezone, timedelta
import html
import json
import os
import time

# Конфигурация
TELEGRAM_TOKEN = "7990034184:AAFTx--E5GE0NIPA0Yghr6KpBC80aVtSACs"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894", "1111230981"]

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("DexMexcBot")

# Глобальные переменные
SHARED_BOT = None
MEXC_FUTURES = None
DEXSCREENER_CACHE = {}
LAST_UPDATE_TIME = None

# Настройки по умолчанию
SETTINGS = {
    "THRESHOLD_PERCENT": 5.0,
    "MIN_VOLUME_USD": 100000,
    "CHECK_INTERVAL": 30,
    "MAX_RESULTS": 20,
    "AUTO_CHECK": True
}

# Состояния для ConversationHandler
SET_THRESHOLD, SET_VOLUME, SET_INTERVAL, SET_MAX_RESULTS = range(4)

def get_main_keyboard():
    """Клавиатура главного меню"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 Проверить арбитраж"), KeyboardButton("⚙️ Настройки")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("🔄 Автопроверка: " + ("ВКЛ" if SETTINGS['AUTO_CHECK'] else "ВЫКЛ"))],
        [KeyboardButton("❓ Помощь")]
    ], resize_keyboard=True)

def get_settings_keyboard():
    """Клавиатура настроек"""
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"📊 Порог: {SETTINGS['THRESHOLD_PERCENT']}%"), 
         KeyboardButton(f"💎 Объем: ${SETTINGS['MIN_VOLUME_USD']/1000:.0f}K")],
        [KeyboardButton(f"⏱ Интервал: {SETTINGS['CHECK_INTERVAL']}с"), 
         KeyboardButton(f"📈 Результаты: {SETTINGS['MAX_RESULTS']}")],
        [KeyboardButton("🔙 Главное меню")]
    ], resize_keyboard=True)

async def send_telegram_message(message: str, chat_id: str = None, reply_markup: ReplyKeyboardMarkup = None):
    global SHARED_BOT
    if not SHARED_BOT:
        SHARED_BOT = Bot(token=TELEGRAM_TOKEN)

    targets = [chat_id] if chat_id else TELEGRAM_CHAT_IDS

    for target_id in targets:
        try:
            await SHARED_BOT.send_message(
                chat_id=target_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            logger.info(f"Сообщение отправлено в чат {target_id}")
        except TelegramError as e:
            logger.error(f"Ошибка отправки в {target_id}: {e}")

async def init_mexc_futures():
    """Инициализация MEXC фьючерсов"""
    global MEXC_FUTURES
    try:
        MEXC_FUTURES = ccxt.mexc({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future'
            }
        })
        await asyncio.get_event_loop().run_in_executor(None, MEXC_FUTURES.load_markets)
        logger.info("MEXC Futures успешно инициализирован")
        return True
    except Exception as e:
        logger.error(f"Ошибка инициализации MEXC Futures: {e}")
        return False

async def fetch_dexscreener_pairs():
    """Получение пар с DEXScreener - исправленная версия"""
    try:
        # Попробуем несколько эндпоинтов DEXScreener
        urls = [
            "https://api.dexscreener.com/latest/dex/pairs?limit=100",
            "https://api.dexscreener.com/latest/dex/tokens?limit=100",
            "https://api.dexscreener.com/latest/dex/search?q=USDT&limit=100"
        ]
        
        all_pairs = []
        
        for url in urls:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=15) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            # Обрабатываем разные форматы ответов
                            if 'pairs' in data:
                                pairs = data['pairs']
                            elif 'tokens' in data:
                                # Преобразуем токены в формат пар
                                tokens = data['tokens']
                                pairs = []
                                for token in tokens:
                                    if 'pairs' in token:
                                        pairs.extend(token['pairs'])
                            else:
                                pairs = data if isinstance(data, list) else []
                            
                            # Фильтруем пары с достаточным объемом и ценой
                            filtered_pairs = [
                                pair for pair in pairs 
                                if pair and 
                                pair.get('priceUsd') and 
                                float(pair.get('priceUsd', 0)) > 0 and
                                float(pair.get('volume', {}).get('h24', 0)) >= SETTINGS['MIN_VOLUME_USD']
                            ]
                            
                            all_pairs.extend(filtered_pairs)
                            logger.info(f"Получено {len(filtered_pairs)} пар с {url}")
                            
                            # Делаем небольшую паузу между запросами
                            await asyncio.sleep(1)
                            
            except Exception as e:
                logger.warning(f"Ошибка при запросе к {url}: {e}")
                continue
        
        # Убираем дубликаты по pairAddress
        unique_pairs = {}
        for pair in all_pairs:
            pair_address = pair.get('pairAddress')
            if pair_address and pair_address not in unique_pairs:
                unique_pairs[pair_address] = pair
        
        final_pairs = list(unique_pairs.values())
        logger.info(f"Всего уникальных пар после фильтрации: {len(final_pairs)}")
        
        return final_pairs
        
    except Exception as e:
        logger.error(f"Общая ошибка получения данных с DEXScreener: {e}")
        return []

async def fetch_mexc_futures_prices():
    """Получение цен фьючерсов с MEXC"""
    try:
        if not MEXC_FUTURES:
            if not await init_mexc_futures():
                return {}

        # Получаем только USDT пары
        symbols = [symbol for symbol in MEXC_FUTURES.symbols if symbol.endswith('/USDT:USDT')]
        prices = {}
        
        # Ограничиваем количество для производительности
        symbols = symbols[:50]
        
        for symbol in symbols:
            try:
                ticker = await asyncio.get_event_loop().run_in_executor(
                    None, MEXC_FUTURES.fetch_ticker, symbol
                )
                if ticker and ticker.get('last'):
                    base_currency = symbol.replace('/USDT:USDT', '').replace('/', '')
                    prices[base_currency] = {
                        'price': float(ticker['last']),
                        'volume': float(ticker.get('baseVolume', 0)) * float(ticker['last']),
                        'symbol': symbol
                    }
            except Exception as e:
                logger.debug(f"Ошибка получения цены для {symbol}: {e}")
                continue

        logger.info(f"Получено {len(prices)} цен фьючерсов с MEXC")
        return prices
    except Exception as e:
        logger.error(f"Ошибка получения цен MEXC Futures: {e}")
        return {}

def normalize_symbol(symbol):
    """Нормализация символа для сравнения"""
    if not symbol:
        return ""
    
    # Убираем лишние символы и приводим к верхнему регистру
    symbol = symbol.upper().replace('-', '').replace('_', '').replace(' ', '')
    
    # Убираем распространенные суффиксы
    for suffix in ['W', 'V2', 'V3', 'TOKEN', 'COIN']:
        if symbol.endswith(suffix):
            symbol = symbol[:-len(suffix)]
    
    return symbol

def find_price_differences(dex_pairs, mexc_prices):
    """Поиск разницы цен между DEX и MEXC Futures"""
    opportunities = []
    
    for dex_pair in dex_pairs:
        try:
            dex_price = float(dex_pair.get('priceUsd', 0))
            base_token = dex_pair.get('baseToken', {})
            base_symbol = base_token.get('symbol', '')
            
            if not dex_price or dex_price <= 0:
                continue
            
            # Нормализуем символ для поиска
            normalized_symbol = normalize_symbol(base_symbol)
            
            # Ищем соответствующий фьючерс на MEXC
            matched_symbol = None
            for mexc_symbol in mexc_prices.keys():
                if normalize_symbol(mexc_symbol) == normalized_symbol:
                    matched_symbol = mexc_symbol
                    break
            
            if matched_symbol and matched_symbol in mexc_prices:
                mexc_data = mexc_prices[matched_symbol]
                mexc_price = mexc_data['price']
                
                if mexc_price <= 0:
                    continue
                
                # Рассчитываем разницу в процентах
                price_diff = ((mexc_price - dex_price) / dex_price) * 100
                abs_diff = abs(price_diff)
                
                if abs_diff >= SETTINGS['THRESHOLD_PERCENT']:
                    dex_volume = float(dex_pair.get('volume', {}).get('h24', 0))
                    mexc_volume = mexc_data['volume']
                    
                    opportunities.append({
                        'symbol': base_symbol,
                        'normalized_symbol': normalized_symbol,
                        'dex_price': dex_price,
                        'mexc_price': mexc_price,
                        'price_diff': price_diff,
                        'abs_diff': abs_diff,
                        'dex_volume': dex_volume,
                        'mexc_volume': mexc_volume,
                        'dex_url': dex_pair.get('url', f"https://dexscreener.com/{dex_pair.get('chainId', 'ethereum')}/{dex_pair.get('pairAddress', '')}"),
                        'mexc_symbol': mexc_data['symbol'],
                        'mexc_url': f"https://futures.mexc.com/exchange/{matched_symbol}_USDT"
                    })
                    
        except Exception as e:
            logger.debug(f"Ошибка обработки пары {dex_pair.get('pairAddress')}: {e}")
            continue
    
    # Сортируем по абсолютной разнице (по убыванию)
    opportunities.sort(key=lambda x: x['abs_diff'], reverse=True)
    return opportunities[:SETTINGS['MAX_RESULTS']]

async def check_price_differences():
    """Основная функция проверки разницы цен"""
    logger.info("Запуск проверки разницы цен DEX vs MEXC Futures")
    
    try:
        # Получаем данные с DEXScreener
        dex_pairs = await fetch_dexscreener_pairs()
        if not dex_pairs:
            logger.warning("Не удалось получить данные с DEXScreener")
            await send_telegram_message(
                "❌ <b>Не удалось получить данные с DEXScreener</b>\n\n"
                "Проверьте:\n"
                "• Доступ к интернету\n"
                "• Работоспособность DEXScreener API\n"
                "• Настройки бота",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Получаем цены фьючерсов с MEXC
        mexc_prices = await fetch_mexc_futures_prices()
        if not mexc_prices:
            logger.warning("Не удалось получить цены с MEXC Futures")
            await send_telegram_message(
                "❌ <b>Не удалось получить цены с MEXC Futures</b>\n\n"
                "Проверьте:\n"
                "• Доступ к MEXC\n"
                "• Соединение с биржей\n"
                "• Настройки API",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Находим различия в ценах
        opportunities = find_price_differences(dex_pairs, mexc_prices)
        
        if opportunities:
            await send_opportunities_message(opportunities)
        else:
            logger.info("Арбитражных возможностей не найдено")
            await send_telegram_message(
                "ℹ️ <b>Арбитражные возможности не найдены</b>\n\n"
                f"Порог: {SETTINGS['THRESHOLD_PERCENT']}%\n"
                f"Минимальный объем: ${SETTINGS['MIN_VOLUME_USD']:,.0f}\n"
                "Попробуйте уменьшить порог или увеличить интервал проверки.",
                reply_markup=get_main_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Ошибка в check_price_differences: {e}")
        await send_telegram_message(
            f"❌ <b>Произошла ошибка при проверке:</b>\n{str(e)}",
            reply_markup=get_main_keyboard()
        )

async def send_opportunities_message(opportunities):
    """Отправка сообщения с арбитражными возможностями"""
    utc_plus_3 = timezone(timedelta(hours=3))
    current_time = datetime.now(utc_plus_3).strftime('%H:%M:%S')
    
    message = f"🔔 <b>АРБИТРАЖ DEX vs MEXC FUTURES</b>\n\n"
    message += f"⏰ <i>Обновлено: {current_time}</i>\n"
    message += f"📊 <i>Найдено возможностей: {len(opportunities)}</i>\n\n"
    
    for i, opp in enumerate(opportunities, 1):
        symbol = html.escape(opp['symbol'])
        price_diff = opp['price_diff']
        abs_diff = opp['abs_diff']
        
        # Определяем направление арбитража
        if price_diff > 0:
            direction = "🟢 DEX → MEXC"
            action = "Купить на DEX, продать на MEXC"
            emoji = "📈"
        else:
            direction = "🔴 MEXC → DEX" 
            action = "Купить на MEXC, продать на DEX"
            emoji = "📉"
        
        # Форматируем объемы
        def format_volume(vol):
            if vol >= 1_000_000:
                return f"${vol/1_000_000:.1f}M"
            elif vol >= 1_000:
                return f"${vol/1_000:.1f}K"
            return f"${vol:.0f}"
        
        dex_volume = format_volume(opp['dex_volume'])
        mexc_volume = format_volume(opp['mexc_volume'])
        
        # Форматируем цены
        def format_price(price):
            if price >= 1:
                return f"${price:.4f}"
            elif price >= 0.01:
                return f"${price:.6f}"
            else:
                return f"${price:.8f}"
        
        dex_price = format_price(opp['dex_price'])
        mexc_price = format_price(opp['mexc_price'])
        
        message += (
            f"{emoji} <b>{i}. {symbol}</b>\n"
            f"▫️ <b>Разница:</b> <code>{abs_diff:.2f}%</code>\n"
            f"▫️ <b>Направление:</b> {direction}\n"
            f"▫️ <b>Действие:</b> {action}\n\n"
            
            f"🔄 <b>DEX Screener:</b>\n"
            f"   💰 Цена: {dex_price}\n"
            f"   📊 Объем: {dex_volume}\n"
            f"   🔗 <a href='{opp['dex_url']}'>Торговать</a>\n\n"
            
            f"🏛️ <b>MEXC Futures:</b>\n"
            f"   💰 Цена: {mexc_price}\n"
            f"   📊 Объем: {mexc_volume}\n"
            f"   🔗 <a href='{opp['mexc_url']}'>Торговать</a>\n"
            f"{'─' * 30}\n\n"
        )
    
    message += f"⚡ <i>Порог срабатывания: {SETTINGS['THRESHOLD_PERCENT']}%</i>\n"
    message += f"💎 <i>Минимальный объем: ${SETTINGS['MIN_VOLUME_USD']:,.0f}</i>"
    
    await send_telegram_message(message, reply_markup=get_main_keyboard())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 <b>DEX vs MEXC Futures Arbitrage Bot</b>\n\n"
        "Бот отслеживает разницу цен между DEX (через DEXScreener) и фьючерсами на MEXC.\n\n"
        "Используйте кнопки ниже для управления ботом:",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    text = update.message.text

    if text == "🔍 Проверить арбитраж":
        await update.message.reply_text("⏳ Проверяю арбитражные возможности...", reply_markup=get_main_keyboard())
        await check_price_differences()

    elif text == "⚙️ Настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки бота</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SET_THRESHOLD

    elif text == "📊 Статус бота":
        status = "✅ Активен" if MEXC_FUTURES else "❌ Ошибка MEXC"
        status_text = (
            "🤖 <b>Статус бота:</b>\n\n"
            f"▫️ MEXC Futures: {status}\n"
            f"▫️ DEXScreener: ✅ Активен\n"
            f"▫️ Последняя проверка: {LAST_UPDATE_TIME or 'Нет данных'}\n\n"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"▫️ Порог: {SETTINGS['THRESHOLD_PERCENT']}%\n"
            f"▫️ Мин. объем: ${SETTINGS['MIN_VOLUME_USD']:,.0f}\n"
            f"▫️ Интервал: {SETTINGS['CHECK_INTERVAL']} сек\n"
            f"▫️ Макс. результатов: {SETTINGS['MAX_RESULTS']}\n"
            f"▫️ Автопроверка: {'ВКЛ' if SETTINGS['AUTO_CHECK'] else 'ВЫКЛ'}"
        )
        await update.message.reply_text(status_text, parse_mode="HTML", reply_markup=get_main_keyboard())

    elif text.startswith("🔄 Автопроверка:"):
        SETTINGS['AUTO_CHECK'] = not SETTINGS['AUTO_CHECK']
        status = "ВКЛ" if SETTINGS['AUTO_CHECK'] else "ВЫКЛ"
        await update.message.reply_text(
            f"✅ Автопроверка {status}",
            reply_markup=get_main_keyboard()
        )

    elif text == "❓ Помощь":
        help_text = (
            "🤖 <b>DEX vs MEXC Futures Arbitrage Bot</b>\n\n"
            "🔍 <b>Проверить арбитраж</b> - запускает проверку разницы цен\n"
            "⚙️ <b>Настройки</b> - настройки параметров бота\n"
            "📊 <b>Статус бота</b> - показывает текущее состояние\n"
            "🔄 <b>Автопроверка</b> - вкл/выкл автоматическую проверку\n\n"
            "<b>Как работает:</b>\n"
            "1. Бот получает данные с DEXScreener\n"
            "2. Сравнивает с ценами фьючерсов на MEXC\n"
            "3. Находит разницы больше установленного порога\n"
            "4. Показывает направления арбитража\n\n"
            "<b>Рекомендации:</b>\n"
            "• Начинайте с порога 5-10%\n"
            "• Учитывайте комиссии и риски\n"
            "• Проверяйте ликвидность перед торговлей"
        )
        await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=get_main_keyboard())

    else:
        await update.message.reply_text(
            "Неизвестная команда. Используйте кнопки меню.",
            reply_markup=get_main_keyboard()
        )

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка меню настроек"""
    text = update.message.text

    if text == "🔙 Главное меню":
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    elif text.startswith("📊 Порог:"):
        context.user_data['setting'] = 'THRESHOLD_PERCENT'
        await update.message.reply_text(
            f"Введите новое значение для порога арбитража (текущее: {SETTINGS['THRESHOLD_PERCENT']}%):"
        )
        return SET_THRESHOLD

    elif text.startswith("💎 Объем:"):
        context.user_data['setting'] = 'MIN_VOLUME_USD'
        await update.message.reply_text(
            f"Введите новое значение для минимального объема (текущее: ${SETTINGS['MIN_VOLUME_USD']:,.0f}):"
        )
        return SET_VOLUME

    elif text.startswith("⏱ Интервал:"):
        context.user_data['setting'] = 'CHECK_INTERVAL'
        await update.message.reply_text(
            f"Введите новое значение для интервала проверки (текущее: {SETTINGS['CHECK_INTERVAL']} сек):"
        )
        return SET_INTERVAL

    elif text.startswith("📈 Результаты:"):
        context.user_data['setting'] = 'MAX_RESULTS'
        await update.message.reply_text(
            f"Введите новое значение для максимального количества результатов (текущее: {SETTINGS['MAX_RESULTS']}):"
        )
        return SET_MAX_RESULTS

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_settings_keyboard()
    )
    return SET_THRESHOLD

async def handle_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода порога"""
    text = update.message.text
    setting = context.user_data.get('setting')

    try:
        if setting == 'THRESHOLD_PERCENT':
            value = float(text)
            if value <= 0:
                await update.message.reply_text("❌ Порог должен быть положительным числом")
                return SET_THRESHOLD
            
            SETTINGS['THRESHOLD_PERCENT'] = value
            await update.message.reply_text(
                f"✅ Порог арбитража установлен: {value}%",
                reply_markup=get_settings_keyboard()
            )
            return SET_THRESHOLD

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите число.",
            reply_markup=get_settings_keyboard()
        )
        return SET_THRESHOLD

async def handle_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода объема"""
    text = update.message.text
    setting = context.user_data.get('setting')

    try:
        if setting == 'MIN_VOLUME_USD':
            value = float(text)
            if value <= 0:
                await update.message.reply_text("❌ Объем должен быть положительным числом")
                return SET_VOLUME
            
            SETTINGS['MIN_VOLUME_USD'] = value
            await update.message.reply_text(
                f"✅ Минимальный объем установлен: ${value:,.0f}",
                reply_markup=get_settings_keyboard()
            )
            return SET_VOLUME

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите число.",
            reply_markup=get_settings_keyboard()
        )
        return SET_VOLUME

async def handle_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода интервала"""
    text = update.message.text
    setting = context.user_data.get('setting')

    try:
        if setting == 'CHECK_INTERVAL':
            value = int(text)
            if value < 10:
                await update.message.reply_text("❌ Интервал должен быть не менее 10 секунд")
                return SET_INTERVAL
            
            SETTINGS['CHECK_INTERVAL'] = value
            await update.message.reply_text(
                f"✅ Интервал проверки установлен: {value} сек",
                reply_markup=get_settings_keyboard()
            )
            return SET_INTERVAL

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите целое число.",
            reply_markup=get_settings_keyboard()
        )
        return SET_INTERVAL

async def handle_max_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода максимального количества результатов"""
    text = update.message.text
    setting = context.user_data.get('setting')

    try:
        if setting == 'MAX_RESULTS':
            value = int(text)
            if value <= 0 or value > 50:
                await update.message.reply_text("❌ Количество результатов должно быть от 1 до 50")
                return SET_MAX_RESULTS
            
            SETTINGS['MAX_RESULTS'] = value
            await update.message.reply_text(
                f"✅ Максимальное количество результатов установлено: {value}",
                reply_markup=get_settings_keyboard()
            )
            return SET_MAX_RESULTS

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите целое число.",
            reply_markup=get_settings_keyboard()
        )
        return SET_MAX_RESULTS

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога"""
    await update.message.reply_text(
        "Операция отменена.",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

async def auto_check():
    """Автоматическая проверка арбитражных возможностей"""
    while True:
        try:
            if SETTINGS['AUTO_CHECK']:
                global LAST_UPDATE_TIME
                LAST_UPDATE_TIME = datetime.now().strftime('%H:%M:%S')
                await check_price_differences()
            await asyncio.sleep(SETTINGS['CHECK_INTERVAL'])
        except Exception as e:
            logger.error(f"Ошибка в auto_check: {e}")
            await asyncio.sleep(60)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)

    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )

def main():
    """Основная функция запуска бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Conversation handler для настроек
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        ],
        states={
            SET_THRESHOLD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_threshold)
            ],
            SET_VOLUME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_volume)
            ],
            SET_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_interval)
            ],
            SET_MAX_RESULTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_max_results)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    # Запускаем автоматическую проверку в фоне
    loop = asyncio.get_event_loop()
    loop.create_task(auto_check())

    logger.info("Бот запущен")
    application.run_polling()

if __name__ == '__main__':
    main()
