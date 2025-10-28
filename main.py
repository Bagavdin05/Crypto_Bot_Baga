import ccxt
import asyncio
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
import aiohttp
from typing import Dict, List, Optional

# Конфигурация
TELEGRAM_TOKEN = "7990034184:AAFTx--E5GE0NIPA0Yghr6KpBC80aVtSACs"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894", "1111230981"]

# Конфигурация DEX-CEX арбитража
DEFAULT_DEX_CEX_SETTINGS = {
    "THRESHOLD_PERCENT": 2.0,
    "MAX_THRESHOLD_PERCENT": 20.0,
    "CHECK_INTERVAL": 30,
    "MIN_VOLUME_USD": 10000,
    "MIN_ENTRY_AMOUNT_USDT": 10,
    "MAX_ENTRY_AMOUNT_USDT": 500,
    "MIN_NET_PROFIT_USDT": 5,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True
}

# Состояния для ConversationHandler
SETTINGS_MENU, DEX_CEX_SETTINGS, SETTING_VALUE = range(3)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("DexCexArbBot")

# Глобальные переменные
SHARED_BOT = None
SETTINGS = {"DEX_CEX": DEFAULT_DEX_CEX_SETTINGS.copy()}
MEXC_EXCHANGE = None

# Глобальные переменные для отслеживания позиций
open_positions = {}
position_history = {}
sent_opportunities = {}

# Reply-клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📈 Актуальные связки")], 
        [KeyboardButton("🔧 Настройки")],
        [KeyboardButton("📊 Открытые позиции"), KeyboardButton("📋 История сделок")],
        [KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)

def get_settings_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔄 DEX-CEX Арбитраж")],
        [KeyboardButton("🔄 Сброс настроек")],
        [KeyboardButton("🔙 Главное меню")]
    ], resize_keyboard=True)

def get_dex_cex_settings_keyboard():
    dex_cex = SETTINGS['DEX_CEX']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {dex_cex['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {dex_cex['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {dex_cex['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${dex_cex['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Мин. сумма: ${dex_cex['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${dex_cex['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Прибыль: ${dex_cex['MIN_NET_PROFIT_USDT']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if dex_cex['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"Сходимость: {dex_cex['PRICE_CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if dex_cex['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)

# Загрузка и сохранение настроек
def load_settings():
    try:
        if os.path.exists('settings.json'):
            with open('settings.json', 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки настроек: {e}")
    return {"DEX_CEX": DEFAULT_DEX_CEX_SETTINGS.copy()}

def save_settings(settings):
    try:
        with open('settings.json', 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")

SETTINGS = load_settings()

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

# Инициализация MEXC
async def init_mexc():
    global MEXC_EXCHANGE
    try:
        MEXC_EXCHANGE = ccxt.mexc({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap"
            }
        })
        await asyncio.get_event_loop().run_in_executor(None, MEXC_EXCHANGE.load_markets)
        logger.info("MEXC фьючерсы успешно загружены")
        return True
    except Exception as e:
        logger.error(f"Ошибка инициализации MEXC: {e}")
        return False

# Получение данных с DexScreener
async def get_dex_screener_data():
    """Получает данные о топ токенах с DexScreener"""
    url = "https://api.dexscreener.com/latest/dex/tokens/your_tokens_here"  # Будет обновлено
    
    # Временные данные для примера - в реальности нужно использовать API DexScreener
    # Здесь должен быть запрос к DexScreener API для получения данных о токенах
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('pairs', [])
    except Exception as e:
        logger.error(f"Ошибка получения данных с DexScreener: {e}")
    
    # Возвращаем тестовые данные
    return [
        {
            'baseToken': {'symbol': 'BTC', 'name': 'Bitcoin'},
            'quoteToken': {'symbol': 'USDT'},
            'priceUsd': '45000.00',
            'volume': {'h24': '1000000'},
            'url': 'https://dexscreener.com/ethereum/0x...',
            'chainId': 'ethereum'
        },
        {
            'baseToken': {'symbol': 'ETH', 'name': 'Ethereum'},
            'quoteToken': {'symbol': 'USDT'},
            'priceUsd': '3000.00',
            'volume': {'h24': '500000'},
            'url': 'https://dexscreener.com/ethereum/0x...',
            'chainId': 'ethereum'
        }
    ]

# Получение цены фьючерса с MEXC
async def get_mexc_futures_price(symbol: str):
    """Получает цену фьючерса с MEXC"""
    if not MEXC_EXCHANGE:
        return None
    
    try:
        futures_symbol = f"{symbol}/USDT:USDT"
        ticker = await asyncio.get_event_loop().run_in_executor(
            None, MEXC_EXCHANGE.fetch_ticker, futures_symbol
        )
        return float(ticker['last']) if ticker and ticker.get('last') else None
    except Exception as e:
        logger.warning(f"Ошибка получения цены {symbol} на MEXC: {e}")
        return None

# Расчет прибыли
def calculate_profit(dex_price: float, cex_price: float, amount: float, position_type: str):
    """Рассчитывает прибыль для арбитражной сделки"""
    if position_type == "LONG":
        # Покупаем на CEX, продаем на DEX (когда цена DEX выше)
        profit = (dex_price - cex_price) * amount
        profit_percent = ((dex_price - cex_price) / cex_price) * 100
    else:  # SHORT
        # Продаем на CEX, покупаем на DEX (когда цена DEX ниже)
        profit = (cex_price - dex_price) * amount
        profit_percent = ((cex_price - dex_price) / cex_price) * 100
    
    return {
        "net": profit,
        "percent": profit_percent,
        "entry_amount": amount * cex_price
    }

# Открытие позиции
async def open_position(symbol: str, dex_price: float, cex_price: float, position_type: str, amount: float):
    """Открывает арбитражную позицию"""
    position_id = f"{symbol}_{position_type}_{int(time.time())}"
    
    position = {
        'id': position_id,
        'symbol': symbol,
        'position_type': position_type,
        'dex_price': dex_price,
        'cex_price': cex_price,
        'amount': amount,
        'open_time': time.time(),
        'status': 'OPEN'
    }
    
    open_positions[position_id] = position
    
    # Отправляем уведомление
    profit_info = calculate_profit(dex_price, cex_price, amount, position_type)
    
    message = (
        f"🎯 <b>ОТКРЫТА ПОЗИЦИЯ</b> 🎯\n\n"
        f"▫️ <b>Монета:</b> <code>{symbol}</code>\n"
        f"▫️ <b>Тип позиции:</b> {position_type}\n"
        f"▫️ <b>Цена DEX:</b> ${dex_price:.8f}\n"
        f"▫️ <b>Цена CEX:</b> ${cex_price:.8f}\n"
        f"▫️ <b>Количество:</b> {amount:.6f} {symbol}\n"
        f"▫️ <b>Сумма входа:</b> ${amount * cex_price:.2f}\n"
        f"▫️ <b>Потенциальная прибыль:</b> ${profit_info['net']:.2f} ({profit_info['percent']:.2f}%)\n\n"
        f"🔗 <a href='https://dexscreener.com/'>DEX Screener</a> | "
        f"<a href='https://futures.mexc.com/exchange/{symbol}_USDT'>MEXC Futures</a>\n"
        f"⏱ {datetime.now(timezone(timedelta(hours=3))).strftime('%H:%M:%S')}"
    )
    
    await send_telegram_message(message)
    return position_id

# Закрытие позиции
async def close_position(position_id: str, current_dex_price: float, current_cex_price: float):
    """Закрывает арбитражную позицию"""
    if position_id not in open_positions:
        return None
    
    position = open_positions[position_id]
    position['close_time'] = time.time()
    position['current_dex_price'] = current_dex_price
    position['current_cex_price'] = current_cex_price
    position['status'] = 'CLOSED'
    
    # Расчет реальной прибыли
    duration = position['close_time'] - position['open_time']
    profit_info = calculate_profit(
        current_dex_price, 
        current_cex_price, 
        position['amount'], 
        position['position_type']
    )
    
    position['profit'] = profit_info['net']
    position['profit_percent'] = profit_info['percent']
    position['duration'] = duration
    
    # Сохраняем в историю
    position_history[position_id] = position.copy()
    
    # Удаляем из открытых позиций
    del open_positions[position_id]
    
    # Определяем результат сделки
    result = "✅ ПРИБЫЛЬ" if profit_info['net'] > 0 else "❌ УБЫТОК"
    
    message = (
        f"🏁 <b>ПОЗИЦИЯ ЗАКРЫТА</b> 🏁\n\n"
        f"▫️ <b>Монета:</b> <code>{position['symbol']}</code>\n"
        f"▫️ <b>Тип позиции:</b> {position['position_type']}\n"
        f"▫️ <b>Результат:</b> {result}\n"
        f"▫️ <b>Прибыль:</b> ${profit_info['net']:.2f} ({profit_info['percent']:.2f}%)\n"
        f"▫️ <b>Длительность:</b> {format_duration(duration)}\n"
        f"▫️ <b>Начальная цена DEX:</b> ${position['dex_price']:.8f}\n"
        f"▫️ <b>Конечная цена DEX:</b> ${current_dex_price:.8f}\n"
        f"▫️ <b>Начальная цена CEX:</b> ${position['cex_price']:.8f}\n"
        f"▫️ <b>Конечная цена CEX:</b> ${current_cex_price:.8f}\n\n"
        f"⏱ {datetime.now(timezone(timedelta(hours=3))).strftime('%H:%M:%S')}"
    )
    
    await send_telegram_message(message)
    return position

def format_duration(seconds):
    """Форматирует длительность в читаемый вид"""
    if seconds < 60:
        return f"{int(seconds)} сек"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        seconds_remaining = int(seconds % 60)
        return f"{minutes} мин {seconds_remaining} сек"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours} ч {minutes} мин"

# Проверка арбитражных возможностей
async def check_dex_cex_arbitrage():
    """Основная функция проверки DEX-CEX арбитража"""
    logger.info("Запуск проверки DEX-CEX арбитража")
    
    if not SETTINGS['DEX_CEX']['ENABLED']:
        logger.info("DEX-CEX арбитраж отключен в настройках")
        return
    
    # Инициализация MEXC
    if not await init_mexc():
        logger.error("Не удалось инициализировать MEXC")
        return
    
    while SETTINGS['DEX_CEX']['ENABLED']:
        try:
            # Получаем данные с DexScreener
            dex_data = await get_dex_screener_data()
            
            found_opportunities = 0
            
            for token_data in dex_data:
                try:
                    symbol = token_data['baseToken']['symbol']
                    dex_price = float(token_data['priceUsd'])
                    volume_24h = float(token_data['volume']['h24'])
                    
                    # Проверяем объем
                    if volume_24h < SETTINGS['DEX_CEX']['MIN_VOLUME_USD']:
                        continue
                    
                    # Получаем цену с MEXC
                    cex_price = await get_mexc_futures_price(symbol)
                    if not cex_price:
                        continue
                    
                    # Рассчитываем спред
                    spread = ((dex_price - cex_price) / cex_price) * 100
                    
                    # Проверяем арбитражные условия
                    if abs(spread) >= SETTINGS['DEX_CEX']['THRESHOLD_PERCENT']:
                        
                        # Определяем тип позиции
                        if spread > 0:
                            position_type = "LONG"  # Цена DEX выше - покупаем на CEX
                        else:
                            position_type = "SHORT"  # Цена DEX ниже - продаем на CEX
                        
                        # Рассчитываем количество для минимальной и максимальной суммы
                        amount_min = SETTINGS['DEX_CEX']['MIN_ENTRY_AMOUNT_USDT'] / cex_price
                        amount_max = SETTINGS['DEX_CEX']['MAX_ENTRY_AMOUNT_USDT'] / cex_price
                        
                        # Рассчитываем прибыль
                        profit_min = calculate_profit(dex_price, cex_price, amount_min, position_type)
                        profit_max = calculate_profit(dex_price, cex_price, amount_max, position_type)
                        
                        # Проверяем минимальную прибыль
                        if profit_min['net'] < SETTINGS['DEX_CEX']['MIN_NET_PROFIT_USDT']:
                            continue
                        
                        # Форматируем сообщение
                        utc_plus_3 = timezone(timedelta(hours=3))
                        current_time = datetime.now(utc_plus_3).strftime('%H:%M:%S')
                        
                        safe_symbol = html.escape(symbol)
                        dex_url = token_data['url']
                        mexc_url = f"https://futures.mexc.com/exchange/{symbol}_USDT"
                        
                        message = (
                            f"🔄 <b>DEX-CEX АРБИТРАЖ</b> 🔄\n\n"
                            f"▫️ <b>Монета:</b> <code>{safe_symbol}</code>\n"
                            f"▫️ <b>Тип позиции:</b> {position_type}\n"
                            f"▫️ <b>Спред:</b> {abs(spread):.2f}%\n"
                            f"▫️ <b>Цена DEX:</b> ${dex_price:.8f}\n"
                            f"▫️ <b>Цена CEX:</b> ${cex_price:.8f}\n"
                            f"▫️ <b>Объем 24h:</b> ${volume_24h:,.0f}\n"
                            f"▫️ <b>Сумма входа:</b> ${SETTINGS['DEX_CEX']['MIN_ENTRY_AMOUNT_USDT']}-${SETTINGS['DEX_CEX']['MAX_ENTRY_AMOUNT_USDT']}\n"
                            f"▫️ <b>Прибыль:</b> ${profit_min['net']:.2f}-${profit_max['net']:.2f}\n\n"
                            f"💡 <i>Сигнал: {f'Покупать на CEX, продавать на DEX' if position_type == 'LONG' else 'Продавать на CEX, покупать на DEX'}</i>\n\n"
                            f"🔗 <a href='{dex_url}'>DEX Screener</a> | <a href='{mexc_url}'>MEXC Futures</a>\n"
                            f"⏱ {current_time}"
                        )
                        
                        # Отправляем уведомление
                        await send_telegram_message(message)
                        
                        # Сохраняем информацию о возможности
                        opportunity_id = f"{symbol}_{position_type}_{int(time.time())}"
                        sent_opportunities[opportunity_id] = {
                            'symbol': symbol,
                            'position_type': position_type,
                            'dex_price': dex_price,
                            'cex_price': cex_price,
                            'spread': spread,
                            'timestamp': time.time()
                        }
                        
                        found_opportunities += 1
                        
                except Exception as e:
                    logger.error(f"Ошибка обработки токена {token_data.get('baseToken', {}).get('symbol', 'Unknown')}: {e}")
            
            logger.info(f"Цикл DEX-CEX арбитража завершен. Найдено возможностей: {found_opportunities}")
            await asyncio.sleep(SETTINGS['DEX_CEX']['CHECK_INTERVAL'])
            
        except Exception as e:
            logger.error(f"Ошибка в основном цикле DEX-CEX арбитража: {e}")
            await asyncio.sleep(60)

# Получение актуальных связок
async def get_current_opportunities():
    """Возвращает текущие арбитражные возможности"""
    current_time = time.time()
    
    # Фильтруем только свежие возможности (последние 30 минут)
    recent_opportunities = {
        k: v for k, v in sent_opportunities.items() 
        if current_time - v['timestamp'] < 1800
    }
    
    if not recent_opportunities:
        return "📊 <b>Актуальные арбитражные связки</b>\n\n⏳ В данный момент активных арбитражных возможностей не обнаружено."
    
    # Группируем и сортируем
    opportunities_list = list(recent_opportunities.values())
    opportunities_list.sort(key=lambda x: abs(x['spread']), reverse=True)
    
    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')
    
    message = "📊 <b>Актуальные арбитражные связки</b>\n\n"
    
    for opp in opportunities_list:
        duration = current_time - opp['timestamp']
        duration_str = format_duration(duration)
        
        message += (
            f"▫️ <code>{opp['symbol']}</code>: {abs(opp['spread']):.2f}% ({opp['position_type']})\n"
            f"   💰 DEX: ${opp['dex_price']:.8f} | CEX: ${opp['cex_price']:.8f}\n"
            f"   ⏱ Обнаружена: {duration_str} назад\n\n"
        )
    
    message += f"⏰ <i>Обновлено: {current_time_str}</i>\n"
    message += f"📈 <i>Всего активных связок: {len(recent_opportunities)}</i>"
    
    return message

# Получение открытых позиций
async def get_open_positions():
    """Возвращает информацию об открытых позициях"""
    if not open_positions:
        return "📊 <b>Открытые позиции</b>\n\n⏳ Нет открытых позиций."
    
    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')
    
    message = "📊 <b>Открытые позиции</b>\n\n"
    
    for pos_id, position in open_positions.items():
        duration = time.time() - position['open_time']
        duration_str = format_duration(duration)
        
        # Текущие цены (в реальной реализации нужно получать актуальные цены)
        current_profit = calculate_profit(
            position['dex_price'],  # В реальности нужно получать текущие цены
            position['cex_price'], 
            position['amount'], 
            position['position_type']
        )
        
        message += (
            f"▫️ <code>{position['symbol']}</code> ({position['position_type']})\n"
            f"   💰 Открыта по: DEX ${position['dex_price']:.8f} | CEX ${position['cex_price']:.8f}\n"
            f"   💵 Текущая прибыль: ${current_profit['net']:.2f}\n"
            f"   ⏱ Длительность: {duration_str}\n\n"
        )
    
    message += f"⏰ <i>Обновлено: {current_time_str}</i>\n"
    message += f"📈 <i>Всего открытых позиций: {len(open_positions)}</i>"
    
    return message

# Получение истории сделок
async def get_trade_history():
    """Возвращает историю сделок"""
    if not position_history:
        return "📋 <b>История сделок</b>\n\n⏳ История сделок пуста."
    
    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')
    
    # Берем последние 10 сделок
    recent_history = sorted(
        position_history.values(), 
        key=lambda x: x.get('close_time', 0), 
        reverse=True
    )[:10]
    
    message = "📋 <b>История сделок</b>\n\n"
    
    total_profit = 0
    winning_trades = 0
    
    for trade in recent_history:
        profit = trade.get('profit', 0)
        total_profit += profit
        if profit > 0:
            winning_trades += 1
        
        duration_str = format_duration(trade.get('duration', 0))
        result = "✅" if profit > 0 else "❌"
        
        message += (
            f"{result} <code>{trade['symbol']}</code> ({trade['position_type']})\n"
            f"   💰 Прибыль: ${profit:.2f}\n"
            f"   ⏱ Длительность: {duration_str}\n\n"
        )
    
    win_rate = (winning_trades / len(recent_history)) * 100 if recent_history else 0
    
    message += (
        f"📈 <b>Статистика:</b>\n"
        f"   Общая прибыль: ${total_profit:.2f}\n"
        f"   Винрейт: {win_rate:.1f}%\n"
        f"   Всего сделок: {len(recent_history)}\n\n"
        f"⏰ <i>Обновлено: {current_time_str}</i>"
    )
    
    return message

# Обработчики команд Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 <b>DEX-CEX Arbitrage Bot</b>\n\n"
        "Арбитраж между DEX (DexScreener) и CEX (MEXC Futures)\n\n"
        "Используйте кнопки ниже для взаимодействия:",
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

    if text == "🔧 Настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    elif text == "📈 Актуальные связки":
        await update.message.reply_text(
            "⏳ Загружаем информацию о текущих арбитражных возможностях...",
            parse_mode="HTML"
        )
        response = await get_current_opportunities()
        await update.message.reply_text(
            text=response,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "📊 Открытые позиции":
        response = await get_open_positions()
        await update.message.reply_text(
            text=response,
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "📋 История сделок":
        response = await get_trade_history()
        await update.message.reply_text(
            text=response,
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "🤖 <b>DEX-CEX Arbitrage Bot</b>\n\n"
            "🔍 <b>Как работает арбитраж:</b>\n"
            "• DEX цена > CEX цена: LONG (покупаем на CEX)\n"
            "• DEX цена < CEX цена: SHORT (продаем на CEX)\n\n"
            "📊 <b>Функции:</b>\n"
            "• Актуальные связки - текущие арбитражные возможности\n"
            "• Открытые позиции - активные сделки\n"
            "• История сделок - завершенные операции\n"
            "• Настройки - параметры арбитража\n\n"
            "⚡ Бот автоматически ищет возможности и присылает уведомления!",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_main_keyboard()
    )

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка меню настроек"""
    text = update.message.text

    if text == "🔄 DEX-CEX Арбитраж":
        await update.message.reply_text(
            "🔄 <b>Настройки DEX-CEX арбитража</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_dex_cex_settings_keyboard()
        )
        return DEX_CEX_SETTINGS

    elif text == "🔄 Сброс настроек":
        global SETTINGS
        SETTINGS = {"DEX_CEX": DEFAULT_DEX_CEX_SETTINGS.copy()}
        save_settings(SETTINGS)
        await update.message.reply_text(
            "✅ Настройки сброшены к значениям по умолчанию",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    elif text == "🔙 Главное меню":
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_settings_keyboard()
    )
    return SETTINGS_MENU

async def handle_dex_cex_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек DEX-CEX арбитража"""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    # Обработка изменения параметров
    if text.startswith("Порог:"):
        context.user_data['setting'] = ('DEX_CEX', 'THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для порога арбитража (текущее: {SETTINGS['DEX_CEX']['THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. порог:"):
        context.user_data['setting'] = ('DEX_CEX', 'MAX_THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для максимального порога (текущее: {SETTINGS['DEX_CEX']['MAX_THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Интервал:"):
        context.user_data['setting'] = ('DEX_CEX', 'CHECK_INTERVAL')
        await update.message.reply_text(
            f"Введите новое значение для интервала проверки (текущее: {SETTINGS['DEX_CEX']['CHECK_INTERVAL']} сек):"
        )
        return SETTING_VALUE

    elif text.startswith("Объем:"):
        context.user_data['setting'] = ('DEX_CEX', 'MIN_VOLUME_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимального объема (текущее: ${SETTINGS['DEX_CEX']['MIN_VOLUME_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Мин. сумма:"):
        context.user_data['setting'] = ('DEX_CEX', 'MIN_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для минимальной суммы входа (текущее: ${SETTINGS['DEX_CEX']['MIN_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. сумма:"):
        context.user_data['setting'] = ('DEX_CEX', 'MAX_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для максимальной суммы входа (текущее: ${SETTINGS['DEX_CEX']['MAX_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Прибыль:"):
        context.user_data['setting'] = ('DEX_CEX', 'MIN_NET_PROFIT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для минимальной прибыли (текущее: ${SETTINGS['DEX_CEX']['MIN_NET_PROFIT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Сходимость:"):
        context.user_data['setting'] = ('DEX_CEX', 'PRICE_CONVERGENCE_THRESHOLD')
        await update.message.reply_text(
            f"Введите новое значение для порога сходимости цен (текущее: {SETTINGS['DEX_CEX']['PRICE_CONVERGENCE_THRESHOLD']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Увед. сравн.:"):
        SETTINGS['DEX_CEX']['PRICE_CONVERGENCE_ENABLED'] = not SETTINGS['DEX_CEX']['PRICE_CONVERGENCE_ENABLED']
        save_settings(SETTINGS)
        status = "🔔 ВКЛ" if SETTINGS['DEX_CEX']['PRICE_CONVERGENCE_ENABLED'] else "🔕 ВЫКЛ"
        await update.message.reply_text(
            f"✅ Уведомления о сравнении цен {status}",
            reply_markup=get_dex_cex_settings_keyboard()
        )
        return DEX_CEX_SETTINGS

    elif text.startswith("Статус:"):
        SETTINGS['DEX_CEX']['ENABLED'] = not SETTINGS['DEX_CEX']['ENABLED']
        save_settings(SETTINGS)
        status = "ВКЛ" if SETTINGS['DEX_CEX']['ENABLED'] else "ВЫКЛ"
        await update.message.reply_text(
            f"✅ DEX-CEX арбитраж {status}",
            reply_markup=get_dex_cex_settings_keyboard()
        )
        return DEX_CEX_SETTINGS

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_dex_cex_settings_keyboard()
    )
    return DEX_CEX_SETTINGS

async def handle_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода значения настройки"""
    text = update.message.text
    setting_info = context.user_data.get('setting')

    if not setting_info:
        await update.message.reply_text(
            "Ошибка: не удалось определить настройку. Попробуйте снова.",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    category, setting_key = setting_info

    try:
        if setting_key in ['THRESHOLD_PERCENT', 'MAX_THRESHOLD_PERCENT', 'PRICE_CONVERGENCE_THRESHOLD']:
            value = float(text)
        elif setting_key in ['CHECK_INTERVAL']:
            value = int(text)
        elif setting_key in ['MIN_VOLUME_USD', 'MIN_ENTRY_AMOUNT_USDT', 'MAX_ENTRY_AMOUNT_USDT', 'MIN_NET_PROFIT_USDT']:
            value = float(text)
        else:
            value = text

        SETTINGS[category][setting_key] = value
        save_settings(SETTINGS)

        await update.message.reply_text(
            f"✅ Настройка {setting_key} изменена на {text}",
            reply_markup=get_dex_cex_settings_keyboard()
        )

        return DEX_CEX_SETTINGS

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите число.",
            reply_markup=get_dex_cex_settings_keyboard()
        )
        return SETTING_VALUE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога"""
    await update.message.reply_text(
        "Операция отменена.",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

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
            SETTINGS_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings)
            ],
            DEX_CEX_SETTINGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dex_cex_settings)
            ],
            SETTING_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_setting_value)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    # Запускаем арбитражную задачу в фоне
    loop = asyncio.get_event_loop()
    loop.create_task(check_dex_cex_arbitrage())

    logger.info("Бот запущен")

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
