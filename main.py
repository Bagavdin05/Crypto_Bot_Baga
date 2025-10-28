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
from collections import defaultdict
import html
import re
import json
import os
import time
import aiohttp
import requests

# Общая конфигурация
TELEGRAM_TOKEN = "7990034184:AAFTx--E5GE0NIPA0Yghr6KpBC80aVtSACs"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894", "1111230981"]

# Конфигурация DEX-CEX арбитража
DEFAULT_DEX_CEX_SETTINGS = {
    "THRESHOLD_PERCENT": 2.0,
    "MAX_THRESHOLD_PERCENT": 50,
    "CHECK_INTERVAL": 30,
    "MIN_LIQUIDITY_USD": 50000,
    "MIN_VOLUME_USD": 100000,
    "MIN_ENTRY_AMOUNT_USDT": 10,
    "MAX_ENTRY_AMOUNT_USDT": 500,
    "MIN_NET_PROFIT_USD": 5,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True,
    "MAX_PAIRS_TO_MONITOR": 100
}

# Настройки бирж
EXCHANGE_SETTINGS = {
    "mexc": {"ENABLED": True}
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
FUTURES_EXCHANGES_LOADED = {}
SETTINGS = {
    "DEX_CEX": DEFAULT_DEX_CEX_SETTINGS.copy(),
    "EXCHANGES": EXCHANGE_SETTINGS.copy()
}

# Конфигурация MEXC для фьючерсов
FUTURES_EXCHANGES = {
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://futures.mexc.com/exchange/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    }
}

# Глобальные переменные для отслеживания
sent_arbitrage_opportunities = defaultdict(dict)
current_arbitrage_opportunities = defaultdict(dict)
arbitrage_start_times = defaultdict(dict)
last_convergence_notification = defaultdict(dict)

# Reply-клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📈 Актуальные связки")], [KeyboardButton("🔧 Настройки")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)

def get_settings_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔄 DEX-CEX Арбитраж")],
        [KeyboardButton("🔙 Главное меню")]
    ], resize_keyboard=True)

def get_dex_cex_settings_keyboard():
    dex_cex = SETTINGS['DEX_CEX']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {dex_cex['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {dex_cex['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {dex_cex['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Лимидность: ${dex_cex['MIN_LIQUIDITY_USD']/1000:.0f}K")],
        [KeyboardButton(f"Объем: ${dex_cex['MIN_VOLUME_USD']/1000:.0f}K"),
         KeyboardButton(f"Пары: {dex_cex['MAX_PAIRS_TO_MONITOR']}")],
        [KeyboardButton(f"Мин. сумма: ${dex_cex['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${dex_cex['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Прибыль: ${dex_cex['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if dex_cex['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"Сходимость: {dex_cex['PRICE_CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if dex_cex['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
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

def add_opportunity_to_sent(base: str, dex_price: float, cex_price: float, spread: float,
                           signal: str, dex_data: dict, min_entry_amount: float = None, 
                           max_entry_amount: float = None, profit_min: dict = None, profit_max: dict = None):
    """Добавляет связку в отправленные возможности"""
    key = f"DEX_CEX_{base}"
    current_time = time.time()

    sent_arbitrage_opportunities[key] = {
        'arb_type': 'DEX_CEX',
        'base': base,
        'dex_price': dex_price,
        'cex_price': cex_price,
        'spread': spread,
        'signal': signal,
        'dex_data': dex_data,
        'min_entry_amount': min_entry_amount,
        'max_entry_amount': max_entry_amount,
        'profit_min': profit_min,
        'profit_max': profit_max,
        'start_time': current_time,
        'last_updated': current_time
    }

    current_arbitrage_opportunities[key] = sent_arbitrage_opportunities[key].copy()
    arbitrage_start_times[key] = current_time

    logger.info(f"DEX-CEX связка добавлена: {key}")

async def send_price_convergence_notification(base: str, dex_price: float, cex_price: float, 
                                            spread: float, signal: str, dex_data: dict, duration: float = None):
    """Отправляет уведомление о сравнении цен"""
    if not SETTINGS['DEX_CEX']['PRICE_CONVERGENCE_ENABLED']:
        return

    convergence_threshold = SETTINGS['DEX_CEX']['PRICE_CONVERGENCE_THRESHOLD']

    if abs(spread) > convergence_threshold:
        return

    # Проверяем, была ли эта связка ранее отправленной
    key = f"DEX_CEX_{base}"
    if key not in sent_arbitrage_opportunities:
        return

    # Проверяем время последнего уведомления
    current_time = time.time()
    notification_key = f"DEX_CEX_{base}"

    if (notification_key in last_convergence_notification and
            current_time - last_convergence_notification[notification_key] < 300):
        return

    last_convergence_notification[notification_key] = current_time

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    # Форматируем данные DEX
    dex_url = dex_data.get('url', f"https://dexscreener.com/{dex_data.get('chainId', '')}/{dex_data.get('pairAddress', '')}")
    dex_chain = dex_data.get('chain', 'Unknown')
    dex_liquidity = dex_data.get('liquidity', {}).get('usd', 0)
    
    liquidity_str = f"${dex_liquidity:,.0f}" if dex_liquidity else "N/A"

    duration_str = format_duration(duration) if duration is not None else "N/A"

    safe_base = html.escape(base)

    # Определяем действие для закрытия
    close_action = "Закрыть ШОРТ" if signal == "LONG" else "Закрыть ЛОНГ"

    message = (
        f"🎯 <b>ЦЕНЫ СРАВНИЛИСЬ! ПОРА ЗАКРЫВАТЬ СДЕЛКУ!</b>\n\n"
        f"▫️ <b>Монета:</b> <code>{safe_base}</code>\n"
        f"▫️ <b>Разница цен:</b> <code>{spread:.2f}%</code>\n"
        f"▫️ <b>Сигнал был:</b> {signal}\n"
        f"▫️ <b>Действие:</b> {close_action} на MEXC\n"
        f"▫️ <b>Длительность арбитража:</b> {duration_str}\n\n"

        f"🟢 <b><a href='{dex_url}'>DEX (DexScreener)</a>:</b>\n"
        f"   💰 Цена: <code>${dex_price:.8f}</code>\n"
        f"   ⛓ Сеть: {dex_chain}\n"
        f"   💧 Ликвидность: {liquidity_str}\n\n"

        f"🔵 <b><a href='https://futures.mexc.com/exchange/{safe_base}_USDT'>MEXC Futures</a>:</b>\n"
        f"   💰 Цена: <code>${cex_price:.8f}</code>\n\n"

        f"⏰ <i>{current_time_str}</i>\n"
        f"🔔 <i>Уведомление о сходимости цен</i>"
    )

    await send_telegram_message(message)
    logger.info(f"Отправлено уведомление о сходимости для {base}: {spread:.4f}%")

    # Удаляем связку из отслеживания
    if key in sent_arbitrage_opportunities:
        del sent_arbitrage_opportunities[key]
    if key in current_arbitrage_opportunities:
        del current_arbitrage_opportunities[key]
    if key in arbitrage_start_times:
        del arbitrage_start_times[key]

def update_arbitrage_duration(base: str, spread: float):
    """Обновляет время длительности арбитражной возможности"""
    key = f"DEX_CEX_{base}"
    current_time = time.time()

    # Если связка активна и спред превышает порог - начинаем отсчет
    if (key in sent_arbitrage_opportunities and
            SETTINGS['DEX_CEX']['THRESHOLD_PERCENT'] <= abs(spread) <= SETTINGS['DEX_CEX']['MAX_THRESHOLD_PERCENT'] and
            key not in arbitrage_start_times):
        arbitrage_start_times[key] = current_time
        logger.debug(f"Начало арбитража для {key}")

    # Если спред упал ниже порога сходимости - вычисляем длительность
    elif (abs(spread) <= SETTINGS['DEX_CEX']['PRICE_CONVERGENCE_THRESHOLD'] and
          key in arbitrage_start_times):
        start_time = arbitrage_start_times.pop(key)
        duration = current_time - start_time
        logger.debug(f"Завершение арбитража для {key}, длительность: {duration:.0f} сек")
        return duration

    return None

def update_current_arbitrage_opportunities(base: str, dex_price: float, cex_price: float, 
                                         spread: float, signal: str, dex_data: dict):
    """Обновляет информацию о текущих арбитражных возможностях"""
    key = f"DEX_CEX_{base}"
    current_time = time.time()

    if key in sent_arbitrage_opportunities:
        current_arbitrage_opportunities[key] = {
            'arb_type': 'DEX_CEX',
            'base': base,
            'dex_price': dex_price,
            'cex_price': cex_price,
            'spread': spread,
            'signal': signal,
            'dex_data': dex_data,
            'min_entry_amount': sent_arbitrage_opportunities[key].get('min_entry_amount'),
            'max_entry_amount': sent_arbitrage_opportunities[key].get('max_entry_amount'),
            'profit_min': sent_arbitrage_opportunities[key].get('profit_min'),
            'profit_max': sent_arbitrage_opportunities[key].get('profit_max'),
            'start_time': sent_arbitrage_opportunities[key]['start_time'],
            'last_updated': current_time
        }

async def get_dex_screener_pairs():
    """Получает пары с DexScreener с фильтрацией по ликвидности"""
    # Используем популярные токены для мониторинга
    popular_tokens = [
        "SOL", "ETH", "BTC", "BNB", "AVAX", "MATIC", "ARB", "OP", 
        "SUI", "APT", "ADA", "XRP", "DOGE", "DOT", "LINK", "LTC",
        "BCH", "ATOM", "NEAR", "FIL", "ETC", "ALGO", "XLM", "XMR",
        "EOS", "TRX", "XTZ", "AAVE", "COMP", "MKR", "SNX", "UNI",
        "CRV", "SUSHI", "YFI", "BAL", "REN", "OMG", "ZRX", "BAT",
        "ENJ", "MANA", "SAND", "GALA", "AXS", "SLP", "CHZ", "FTM",
        "ONE", "VET", "ICX", "ZIL", "ONT", "IOST", "WAVES", "KSM",
        "DASH", "ZEC", "XEM", "SC", "BTT", "WIN", "BAND", "OCEAN",
        "RSR", "CVC", "REQ", "NMR", "POLY", "LRC", "STORJ", "KNC"
    ]
    
    all_pairs = []
    
    for token in popular_tokens:
        try:
            url = f"https://api.dexscreener.com/latest/dex/search?q={token}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        pairs = data.get('pairs', [])
                        
                        for pair in pairs:
                            try:
                                # Проверяем, что это USDT пара
                                quote_token = pair.get('quoteToken', {}).get('symbol', '').upper()
                                if quote_token != 'USDT':
                                    continue
                                
                                liquidity_usd = pair.get('liquidity', {}).get('usd', 0)
                                volume_h24 = pair.get('volume', {}).get('h24', 0)
                                price_usd = pair.get('priceUsd', 0)
                                
                                # Проверяем ликвидность и объем
                                if (liquidity_usd >= SETTINGS['DEX_CEX']['MIN_LIQUIDITY_USD'] and
                                    volume_h24 >= SETTINGS['DEX_CEX']['MIN_VOLUME_USD'] and
                                    price_usd > 0):
                                    
                                    base_symbol = pair['baseToken']['symbol'].upper()
                                    base_symbol = re.sub(r'\.\w+$', '', base_symbol)
                                    
                                    # Пропускаем пары с неподходящими символами
                                    if not re.match(r'^[A-Z0-9]{2,15}$', base_symbol):
                                        continue
                                    
                                    # Проверяем, что это не стейблкоин
                                    if any(stable in base_symbol for stable in ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD']):
                                        continue
                                    
                                    pair_data = {
                                        'baseSymbol': base_symbol,
                                        'price': float(price_usd),
                                        'liquidity': {'usd': liquidity_usd},
                                        'volume': {'h24': volume_h24},
                                        'chain': pair.get('chain', 'Unknown'),
                                        'pairAddress': pair.get('pairAddress'),
                                        'chainId': pair.get('chainId'),
                                        'url': pair.get('url', f"https://dexscreener.com/{pair.get('chainId', '')}/{pair.get('pairAddress', '')}")
                                    }
                                    
                                    # Добавляем только если такой символ еще не добавлен или если у этой пары больше ликвидности
                                    existing_pair = next((p for p in all_pairs if p['baseSymbol'] == base_symbol), None)
                                    if not existing_pair or liquidity_usd > existing_pair['liquidity']['usd']:
                                        if existing_pair:
                                            all_pairs.remove(existing_pair)
                                        all_pairs.append(pair_data)
                                    
                                    # Ограничиваем общее количество пар
                                    if len(all_pairs) >= SETTINGS['DEX_CEX']['MAX_PAIRS_TO_MONITOR']:
                                        break
                                    
                            except Exception as e:
                                logger.warning(f"Ошибка обработки пары {token}: {e}")
                                continue
                    
                    else:
                        logger.warning(f"Ошибка API DexScreener для {token}: {response.status}")
                        
        except Exception as e:
            logger.warning(f"Ошибка получения данных для токена {token}: {e}")
            continue
        
        # Делаем небольшую паузу между запросами
        await asyncio.sleep(0.5)
    
    logger.info(f"Загружено {len(all_pairs)} пар с DexScreener")
    return all_pairs

async def load_futures_exchanges():
    """Загружает фьючерсные биржи"""
    global FUTURES_EXCHANGES_LOADED

    exchanges = {}
    for name, config in FUTURES_EXCHANGES.items():
        if not SETTINGS['EXCHANGES'][name]['ENABLED']:
            continue

        try:
            exchange = await asyncio.get_event_loop().run_in_executor(
                None, config["api"].load_markets)
            if exchange:
                exchanges[name] = {
                    "api": config["api"],
                    "config": config
                }
                logger.info(f"{name.upper()} успешно загружена")
        except Exception as e:
            logger.error(f"Ошибка инициализации {name}: {e}")

    FUTURES_EXCHANGES_LOADED = exchanges
    return exchanges

async def fetch_cex_price(symbol: str):
    """Получает цену с MEXC фьючерсов"""
    try:
        if "mexc" not in FUTURES_EXCHANGES_LOADED:
            return None
            
        exchange = FUTURES_EXCHANGES_LOADED["mexc"]["api"]
        futures_symbol = FUTURES_EXCHANGES_LOADED["mexc"]["config"]["symbol_format"](symbol)
        
        try:
            ticker = await asyncio.get_event_loop().run_in_executor(
                None, exchange.fetch_ticker, futures_symbol)
            return float(ticker['last']) if ticker and ticker.get('last') else None
        except ccxt.BadSymbol:
            # Пара не найдена на фьючерсах
            return None
            
    except Exception as e:
        logger.warning(f"Ошибка получения цены {symbol} на MEXC: {e}")
        return None

def calculate_profit(buy_price: float, sell_price: float, amount: float, fee_percent: float = 0.0006) -> dict:
    """Рассчитывает прибыль для арбитража"""
    buy_cost = amount * buy_price * (1 + fee_percent)
    sell_revenue = amount * sell_price * (1 - fee_percent)
    net_profit = sell_revenue - buy_cost
    profit_percent = (net_profit / buy_cost) * 100 if buy_cost > 0 else 0

    return {
        "net": net_profit,
        "percent": profit_percent,
        "entry_amount": amount * buy_price
    }

async def check_dex_cex_arbitrage():
    """Основная функция проверки DEX-CEX арбитража"""
    logger.info("Запуск проверки DEX-CEX арбитража")

    if not SETTINGS['DEX_CEX']['ENABLED']:
        logger.info("DEX-CEX арбитраж отключен в настройках")
        return

    # Загружаем фьючерсные биржи
    await load_futures_exchanges()

    if not FUTURES_EXCHANGES_LOADED:
        logger.error("MEXC фьючерсы не загружены")
        return

    while SETTINGS['DEX_CEX']['ENABLED']:
        try:
            # Получаем пары с DexScreener
            dex_pairs = await get_dex_screener_pairs()
            if not dex_pairs:
                logger.warning("Не удалось получить пары с DexScreener")
                await asyncio.sleep(SETTINGS['DEX_CEX']['CHECK_INTERVAL'])
                continue

            found_opportunities = 0
            
            # Группируем пары по символу, выбираем самую ликвидную для каждого символа
            pairs_by_symbol = {}
            for pair in dex_pairs:
                symbol = pair['baseSymbol']
                if symbol not in pairs_by_symbol or pair['liquidity']['usd'] > pairs_by_symbol[symbol]['liquidity']['usd']:
                    pairs_by_symbol[symbol] = pair

            # Проверяем арбитраж для каждой пары
            for symbol, dex_data in pairs_by_symbol.items():
                try:
                    dex_price = dex_data['price']
                    cex_price = await fetch_cex_price(symbol)
                    
                    if not cex_price or dex_price == 0:
                        continue

                    # Рассчитываем спред
                    spread = ((dex_price - cex_price) / cex_price) * 100
                    
                    # Определяем сигнал
                    if dex_price > cex_price:
                        signal = "LONG"  # Покупка на DEX, Шорт на CEX
                        action = "ШОРТ на MEXC"
                    else:
                        signal = "SHORT"  # Продажа на DEX, Лонг на CEX  
                        action = "ЛОНГ на MEXC"
                    
                    abs_spread = abs(spread)
                    
                    # Обновляем текущие возможности
                    update_current_arbitrage_opportunities(
                        symbol, dex_price, cex_price, spread, signal, dex_data
                    )

                    # Проверяем сходимость цен
                    duration = update_arbitrage_duration(symbol, spread)
                    if duration is not None:
                        await send_price_convergence_notification(
                            symbol, dex_price, cex_price, spread, signal, dex_data, duration
                        )

                    # Проверяем порог для нового арбитража
                    if (SETTINGS['DEX_CEX']['THRESHOLD_PERCENT'] <= abs_spread <= 
                        SETTINGS['DEX_CEX']['MAX_THRESHOLD_PERCENT']):
                        
                        # Рассчитываем прибыль
                        fee = FUTURES_EXCHANGES_LOADED["mexc"]["config"]["taker_fee"]
                        
                        # Для LONG: покупаем на DEX по dex_price, продаем на CEX по cex_price
                        # Для SHORT: продаем на DEX по dex_price, покупаем на CEX по cex_price
                        
                        if signal == "LONG":
                            buy_price = dex_price
                            sell_price = cex_price
                        else:  # SHORT
                            buy_price = cex_price
                            sell_price = dex_price

                        # Рассчитываем минимальную сумму для прибыли
                        min_amount_for_profit = (SETTINGS['DEX_CEX']['MIN_NET_PROFIT_USD'] / 
                                               (sell_price * (1 - fee) - buy_price * (1 + fee)))
                        
                        if min_amount_for_profit <= 0:
                            continue

                        # Рассчитываем суммы входа
                        min_entry_amount = max(min_amount_for_profit * buy_price, 
                                             SETTINGS['DEX_CEX']['MIN_ENTRY_AMOUNT_USDT'])
                        max_entry_amount = SETTINGS['DEX_CEX']['MAX_ENTRY_AMOUNT_USDT']

                        if min_entry_amount > max_entry_amount:
                            continue

                        # Рассчитываем прибыль для min и max сумм
                        amount_min = min_entry_amount / buy_price
                        amount_max = max_entry_amount / buy_price

                        profit_min = calculate_profit(buy_price, sell_price, amount_min, fee)
                        profit_max = calculate_profit(buy_price, sell_price, amount_max, fee)

                        if profit_min['net'] < SETTINGS['DEX_CEX']['MIN_NET_PROFIT_USD']:
                            continue

                        # Форматируем сообщение
                        utc_plus_3 = timezone(timedelta(hours=3))
                        current_time = datetime.now(utc_plus_3).strftime('%H:%M:%S')

                        safe_symbol = html.escape(symbol)
                        dex_url = dex_data['url']
                        mexc_url = f"https://futures.mexc.com/exchange/{symbol}_USDT"

                        liquidity_str = f"${dex_data['liquidity']['usd']:,.0f}" if dex_data['liquidity']['usd'] else "N/A"

                        message = (
                            f"🔄 <b>DEX-CEX АРБИТРАЖ</b>\n\n"
                            f"▫️ <b>Монета:</b> <code>{safe_symbol}</code>\n"
                            f"▫️ <b>Разница цен:</b> {abs_spread:.2f}%\n"
                            f"▫️ <b>Сигнал:</b> {signal}\n"
                            f"▫️ <b>Действие:</b> {action}\n"
                            f"▫️ <b>Сумма входа:</b> ${min_entry_amount:.2f}-${max_entry_amount:.2f}\n\n"
                            
                            f"🟢 <b><a href='{dex_url}'>DEX (DexScreener)</a>:</b>\n"
                            f"   💰 Цена: <code>${dex_price:.8f}</code>\n"
                            f"   ⛓ Сеть: {dex_data['chain']}\n"
                            f"   💧 Ликвидность: {liquidity_str}\n\n"
                            
                            f"🔵 <b><a href='{mexc_url}'>MEXC Futures</a>:</b>\n"
                            f"   💰 Цена: <code>${cex_price:.8f}</code>\n"
                            f"   📊 Комиссия: {fee * 100:.3f}%\n\n"
                            
                            f"💰 <b>Чистая прибыль:</b> ${profit_min['net']:.2f}-${profit_max['net']:.2f}\n\n"
                            f"⏱ {current_time}\n"
                        )

                        logger.info(f"Найдена DEX-CEX возможность: {symbol} ({abs_spread:.2f}%)")

                        # Отправляем сообщение
                        await send_telegram_message(message)

                        # Добавляем в отслеживание
                        add_opportunity_to_sent(
                            symbol, dex_price, cex_price, spread, signal, dex_data,
                            min_entry_amount, max_entry_amount, profit_min, profit_max
                        )

                        found_opportunities += 1

                except Exception as e:
                    logger.error(f"Ошибка обработки пары {symbol}: {e}")

            logger.info(f"Цикл DEX-CEX арбитража завершен. Найдено возможностей: {found_opportunities}")
            await asyncio.sleep(SETTINGS['DEX_CEX']['CHECK_INTERVAL'])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле DEX-CEX арбитража: {e}")
            await asyncio.sleep(60)

async def get_current_arbitrage_opportunities():
    """Возвращает текущие арбитражные возможности"""
    current_time = time.time()
    
    # Очищаем устаревшие возможности (старше 1 часа)
    keys_to_remove = []
    for key, opportunity in sent_arbitrage_opportunities.items():
        if current_time - opportunity['last_updated'] > 3600:
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        del sent_arbitrage_opportunities[key]
        if key in current_arbitrage_opportunities:
            del current_arbitrage_opportunities[key]

    if not sent_arbitrage_opportunities:
        return "📊 <b>Актуальные DEX-CEX связки</b>\n\n" \
               "⏳ В данный момент активных арбитражных возможностей не обнаружено."

    # Сортируем по спреду (по убыванию)
    sorted_opportunities = sorted(
        sent_arbitrage_opportunities.values(), 
        key=lambda x: abs(x['spread']), 
        reverse=True
    )

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    message = "📊 <b>Актуальные DEX-CEX связки</b>\n\n"

    for opp in sorted_opportunities:
        duration = time.time() - opp['start_time']
        duration_str = format_duration(duration)

        entry_amount_str = f"${opp['min_entry_amount']:.2f}-${opp['max_entry_amount']:.2f}" if opp.get('min_entry_amount') and opp.get('max_entry_amount') else "N/A"

        profit_str = "N/A"
        if opp.get('profit_min') and opp.get('profit_max'):
            profit_min_net = opp['profit_min'].get('net', 0)
            profit_max_net = opp['profit_max'].get('net', 0)
            profit_str = f"${profit_min_net:.2f}-${profit_max_net:.2f}"

        message += (
            f"▫️ <code>{opp['base']}</code>: {abs(opp['spread']):.2f}% ({opp['signal']})\n"
            f"   💰 Сумма входа: {entry_amount_str}\n"
            f"   💵 Прибыль: {profit_str}\n"
            f"   ⏱ Длительность: {duration_str}\n\n"
        )

    message += f"⏰ <i>Обновлено: {current_time_str}</i>\n"
    message += f"📈 <i>Всего активных связок: {len(sorted_opportunities)}</i>"

    return message

# Обработчики Telegram команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 <b>DEX-CEX Arbitrage Bot</b>\n\n"
        "Арбитраж между DexScreener (DEX) и MEXC Futures (CEX)\n\n"
        "Используйте кнопки ниже для взаимодействия с ботом:",
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

        response = await get_current_arbitrage_opportunities()
        await update.message.reply_text(
            text=response,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "📊 Статус бота":
        dex_cex_status = "✅ ВКЛ" if SETTINGS['DEX_CEX']['ENABLED'] else "❌ ВЫКЛ"
        active_opportunities = len(sent_arbitrage_opportunities)

        await update.message.reply_text(
            f"🤖 <b>Статус бота</b>\n\n"
            f"🔄 DEX-CEX арбитраж: {dex_cex_status}\n"
            f"🏛 Активные биржи: MEXC Futures\n"
            f"📈 Активных связок: {active_opportunities}\n"
            f"⚡ Мониторинг пар: {SETTINGS['DEX_CEX']['MAX_PAIRS_TO_MONITOR']}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "🤖 <b>DEX-CEX Arbitrage Bot</b>\n\n"
            "🔍 <b>Как это работает:</b>\n"
            "• Бот мониторит цены на DexScreener (DEX) и MEXC Futures (CEX)\n"
            "• При обнаружении разницы цен отправляет сигнал:\n"
            "  🟢 LONG: Цена на DEX выше - ШОРТ на MEXC\n"
            "  🔴 SHORT: Цена на DEX ниже - ЛОНГ на MEXC\n"
            "• При сходимости цен отправляет уведомление о закрытии сделки\n\n"
            "📊 <b>Актуальные связки</b> - текущие арбитражные возможности\n"
            "🔧 <b>Настройки</b> - параметры арбитража\n"
            "📊 <b>Статус бота</b> - текущее состояние\n\n"
            "⚡ <i>Бот работает полностью автоматически</i>",
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

    elif text.startswith("Лимидность:"):
        context.user_data['setting'] = ('DEX_CEX', 'MIN_LIQUIDITY_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимальной ликвидности (текущее: ${SETTINGS['DEX_CEX']['MIN_LIQUIDITY_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Объем:"):
        context.user_data['setting'] = ('DEX_CEX', 'MIN_VOLUME_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимального объема (текущее: ${SETTINGS['DEX_CEX']['MIN_VOLUME_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Пары:"):
        context.user_data['setting'] = ('DEX_CEX', 'MAX_PAIRS_TO_MONITOR')
        await update.message.reply_text(
            f"Введите новое значение для максимального количества пар (текущее: {SETTINGS['DEX_CEX']['MAX_PAIRS_TO_MONITOR']}):"
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
        context.user_data['setting'] = ('DEX_CEX', 'MIN_NET_PROFIT_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимальной прибыли (текущее: ${SETTINGS['DEX_CEX']['MIN_NET_PROFIT_USD']}):"
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
        status = "🔔 ВКЛ" if SETTINGS['DEX_CEX']['PRICE_CONVERGENCE_ENABLED'] else "🔕 ВЫКЛ"
        await update.message.reply_text(
            f"✅ Уведомления о сравнении цен {status}",
            reply_markup=get_dex_cex_settings_keyboard()
        )
        return DEX_CEX_SETTINGS

    elif text.startswith("Статус:"):
        SETTINGS['DEX_CEX']['ENABLED'] = not SETTINGS['DEX_CEX']['ENABLED']
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

    arb_type, setting_key = setting_info

    try:
        # Обработка числовых значений
        if setting_key in ['THRESHOLD_PERCENT', 'MAX_THRESHOLD_PERCENT', 'PRICE_CONVERGENCE_THRESHOLD']:
            value = float(text)
        elif setting_key in ['CHECK_INTERVAL', 'MAX_PAIRS_TO_MONITOR']:
            value = int(text)
        elif setting_key in ['MIN_LIQUIDITY_USD', 'MIN_VOLUME_USD', 'MIN_ENTRY_AMOUNT_USDT', 
                           'MAX_ENTRY_AMOUNT_USDT', 'MIN_NET_PROFIT_USD']:
            value = float(text)
        else:
            value = text

        # Устанавливаем новое значение
        SETTINGS[arb_type][setting_key] = value

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

    logger.info("DEX-CEX Arbitrage Bot запущен")

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
