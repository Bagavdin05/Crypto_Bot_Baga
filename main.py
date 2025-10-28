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
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 20,
    "CHECK_INTERVAL": 30,
    "MIN_VOLUME_USD": 100000,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 170,
    "MIN_NET_PROFIT_USD": 3,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True,
    "DEX_TAKER_FEE": 0.003,  # 0.3% для DEX
    "CEX_TAKER_FEE": 0.0006  # 0.06% для MEXC фьючерсов
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

# Глобальные переменные для отслеживания истории уведомлений и длительности арбитража
price_convergence_history = defaultdict(dict)
last_convergence_notification = defaultdict(dict)
arbitrage_start_times = defaultdict(dict)
current_arbitrage_opportunities = defaultdict(dict)
previous_arbitrage_opportunities = defaultdict(dict)
sent_arbitrage_opportunities = defaultdict(dict)

# Глобальные переменные для хранения последних настроек бирж
LAST_EXCHANGE_SETTINGS = None

# Загрузка сохраненных настроек
def load_settings():
    try:
        if os.path.exists('settings.json'):
            with open('settings.json', 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки настроек: {e}")

    # Возвращаем настройки по умолчанию
    return {
        "DEX_CEX": DEFAULT_DEX_CEX_SETTINGS.copy(),
        "EXCHANGES": EXCHANGE_SETTINGS.copy()
    }

# Сохранение настроек
def save_settings(settings):
    try:
        with open('settings.json', 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")

# Глобальные переменные
SHARED_BOT = None
FUTURES_EXCHANGES_LOADED = {}
SETTINGS = load_settings()

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

# Reply-клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📈 Актуальные связки")], [KeyboardButton("🔧 Настройки")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)

def get_settings_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🦄 DEX-CEX Арбитраж")],
        [KeyboardButton("🏛 Биржи"), KeyboardButton("🔄 Сброс")],
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
        [KeyboardButton(f"Прибыль: ${dex_cex['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if dex_cex['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"DEX комиссия: {dex_cex['DEX_TAKER_FEE']*100}%"),
         KeyboardButton(f"CEX комиссия: {dex_cex['CEX_TAKER_FEE']*100}%")],
        [KeyboardButton(f"Сходимость: {dex_cex['PRICE_CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if dex_cex['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)

def get_exchange_settings_keyboard():
    keyboard = []
    row = []
    for i, (exchange, config) in enumerate(SETTINGS['EXCHANGES'].items()):
        status = "✅" if config['ENABLED'] else "❌"
        row.append(KeyboardButton(f"{exchange}: {status}"))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton("🔙 Назад в настройки")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

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

def add_opportunity_to_sent(arb_type: str, base: str, dex_data: dict, cex_data: dict, spread: float,
                            direction: str, min_entry_amount: float = None, max_entry_amount: float = None,
                            profit_min: dict = None, profit_max: dict = None):
    """Добавляет связку в отправленные возможности"""
    key = f"{arb_type}_{base}_{dex_data['dex_url']}_{cex_data['exchange']}"
    current_time = time.time()

    sent_arbitrage_opportunities[key] = {
        'arb_type': arb_type,
        'base': base,
        'dex_data': dex_data,
        'cex_data': cex_data,
        'spread': spread,
        'direction': direction,
        'min_entry_amount': min_entry_amount,
        'max_entry_amount': max_entry_amount,
        'profit_min': profit_min,
        'profit_max': profit_max,
        'start_time': current_time,
        'last_updated': current_time
    }

    current_arbitrage_opportunities[key] = sent_arbitrage_opportunities[key].copy()
    arbitrage_start_times[key] = current_time
    previous_arbitrage_opportunities[key] = True

    logger.info(f"Связка добавлена в отправленные: {key}")

async def send_price_convergence_notification(arb_type: str, base: str, dex_data: dict, cex_data: dict,
                                              spread: float, direction: str, duration: float = None):
    """Отправляет уведомление о сравнении цен с длительностью арбитража"""

    if not SETTINGS[arb_type]['PRICE_CONVERGENCE_ENABLED']:
        return

    convergence_threshold = SETTINGS[arb_type]['PRICE_CONVERGENCE_THRESHOLD']

    if abs(spread) > convergence_threshold:
        return

    previous_key = f"{arb_type}_{base}_{dex_data['dex_url']}_{cex_data['exchange']}"
    if previous_key not in sent_arbitrage_opportunities:
        return

    current_time = time.time()
    notification_key = f"{arb_type}_{base}_{dex_data['dex_url']}_{cex_data['exchange']}"

    if (notification_key in last_convergence_notification and
            current_time - last_convergence_notification[notification_key] < 300):
        return

    last_convergence_notification[notification_key] = current_time

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    def format_volume(vol):
        if vol is None:
            return "N/A"
        if vol >= 1_000_000:
            return f"${vol / 1_000_000:.1f}M"
        if vol >= 1_000:
            return f"${vol / 1_000:.1f}K"
        return f"${vol:.1f}"

    dex_volume_str = format_volume(dex_data.get('volume'))
    cex_volume_str = format_volume(cex_data.get('volume'))

    duration_str = format_duration(duration) if duration is not None else "N/A"

    safe_base = html.escape(base)

    message = (
        f"🎯 <b>ЦЕНЫ СРАВНИЛИСЬ!</b> 🦄\n\n"
        f"▫️ <b>Тип:</b> DEX-CEX арбитраж\n"
        f"▫️ <b>Монета:</b> <code>{safe_base}</code>\n"
        f"▫️ <b>Направление:</b> {direction}\n"
        f"▫️ <b>Разница цен:</b> <code>{spread:.2f}%</code>\n"
        f"▫️ <b>Длительность арбитража:</b> {duration_str}\n\n"

        f"🟢 <b><a href='{dex_data['dex_url']}'>DEX (DexScreener)</a>:</b>\n"
        f"   💰 Цена: <code>${dex_data['price']:.8f}</code>\n"
        f"   📊 Объем: {dex_volume_str}\n"
        f"   🌐 Сеть: {dex_data.get('network', 'N/A')}\n\n"

        f"🔵 <b><a href='{cex_data['url']}'>CEX ({cex_data['exchange'].upper()})</a>:</b>\n"
        f"   💰 Цена: <code>${cex_data['price']:.8f}</code>\n"
        f"   📊 Объем: {cex_volume_str}\n\n"

        f"⏰ <i>{current_time_str}</i>\n"
        f"🔔 <i>Уведомление о сходимости цен</i>"
    )

    await send_telegram_message(message)
    logger.info(f"Отправлено уведомление о сходимости цен для {base}: {spread:.4f}%, длительность: {duration_str}")

    key = f"{arb_type}_{base}_{dex_data['dex_url']}_{cex_data['exchange']}"
    if key in sent_arbitrage_opportunities:
        del sent_arbitrage_opportunities[key]
    if key in current_arbitrage_opportunities:
        del current_arbitrage_opportunities[key]
    if key in arbitrage_start_times:
        del arbitrage_start_times[key]
    if key in previous_arbitrage_opportunities:
        del previous_arbitrage_opportunities[key]

    logger.info(f"Связка удалена из актуальных после сходимости цен: {key}")

def update_arbitrage_duration(arb_type: str, base: str, dex_data: dict, cex_data: dict, spread: float):
    """Обновляет время длительности арбитражной возможности"""
    key = f"{arb_type}_{base}_{dex_data['dex_url']}_{cex_data['exchange']}"
    current_time = time.time()

    if (key in sent_arbitrage_opportunities and
            SETTINGS[arb_type]['THRESHOLD_PERCENT'] <= abs(spread) <= SETTINGS[arb_type]['MAX_THRESHOLD_PERCENT'] and
            key not in arbitrage_start_times):
        arbitrage_start_times[key] = current_time
        previous_arbitrage_opportunities[key] = True
        logger.debug(f"Начало арбитража для {key}")

    elif (abs(spread) <= SETTINGS[arb_type]['PRICE_CONVERGENCE_THRESHOLD'] and
          key in arbitrage_start_times):
        start_time = arbitrage_start_times.pop(key)
        duration = current_time - start_time
        logger.debug(f"Завершение арбитража для {key}, длительность: {duration:.0f} сек")
        return duration

    return None

def update_current_arbitrage_opportunities(arb_type: str, base: str, dex_data: dict, cex_data: dict, spread: float,
                                           direction: str, min_entry_amount: float = None, max_entry_amount: float = None,
                                           profit_min: dict = None, profit_max: dict = None):
    """Обновляет информацию о текущих арбитражных возможностях"""
    key = f"{arb_type}_{base}_{dex_data['dex_url']}_{cex_data['exchange']}"
    current_time = time.time()

    if key in sent_arbitrage_opportunities:
        current_arbitrage_opportunities[key] = {
            'arb_type': arb_type,
            'base': base,
            'dex_data': dex_data,
            'cex_data': cex_data,
            'spread': spread,
            'direction': direction,
            'min_entry_amount': min_entry_amount,
            'max_entry_amount': max_entry_amount,
            'profit_min': profit_min,
            'profit_max': profit_max,
            'start_time': sent_arbitrage_opportunities[key]['start_time'],
            'last_updated': current_time
        }

async def get_current_arbitrage_opportunities():
    """Возвращает форматированное сообщение с текущими арбитражными возможностями"""
    cleanup_old_opportunities()

    filtered_opportunities = {}
    current_time = time.time()

    for key, opportunity in sent_arbitrage_opportunities.items():
        if (current_time - opportunity['last_updated']) <= 3600:
            filtered_opportunities[key] = opportunity

    if not filtered_opportunities:
        return "📊 <b>Актуальные DEX-CEX связки</b>\n\n" \
               "⏳ В данный момент активных арбитражных возможностей не обнаружено."

    opportunities_list = []
    for key, opportunity in filtered_opportunities.items():
        duration = time.time() - opportunity['start_time']
        opportunities_list.append({
            'base': opportunity['base'],
            'dex_data': opportunity['dex_data'],
            'cex_data': opportunity['cex_data'],
            'spread': opportunity['spread'],
            'direction': opportunity['direction'],
            'min_entry_amount': opportunity.get('min_entry_amount'),
            'max_entry_amount': opportunity.get('max_entry_amount'),
            'profit_min': opportunity.get('profit_min'),
            'profit_max': opportunity.get('profit_max'),
            'duration': duration
        })

    opportunities_list.sort(key=lambda x: x['spread'], reverse=True)

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    message = "📊 <b>Актуальные DEX-CEX связки</b>\n\n"

    for opp in opportunities_list:
        duration_str = format_duration(opp['duration'])

        entry_amount_str = f"${opp['min_entry_amount']:.2f}-${opp['max_entry_amount']:.2f}" if opp.get(
            'min_entry_amount') and opp.get('max_entry_amount') else "N/A"

        profit_str = "N/A"
        if opp.get('profit_min') and opp.get('profit_max'):
            profit_min_net = opp['profit_min'].get('net', 0)
            profit_max_net = opp['profit_max'].get('net', 0)
            profit_str = f"${profit_min_net:.2f}-${profit_max_net:.2f}"

        message += (
            f"▫️ <code>{opp['base']}</code>: {opp['spread']:.2f}%\n"
            f"   🦄 DEX → 📊 {opp['cex_data']['exchange'].upper()}\n"
            f"   📈 Направление: {opp['direction']}\n"
            f"   💰 Сумма входа: {entry_amount_str}\n"
            f"   💵 Прибыль: {profit_str}\n"
            f"   ⏱ Длительность: {duration_str}\n\n"
        )

    message += f"⏰ <i>Обновлено: {current_time_str}</i>\n"
    message += f"📈 <i>Всего активных связок: {len(filtered_opportunities)}</i>"

    return message

def cleanup_old_opportunities():
    """Очищает устаревшие арбитражные возможности"""
    current_time = time.time()
    keys_to_remove = []

    for key, opportunity in sent_arbitrage_opportunities.items():
        if current_time - opportunity['last_updated'] > 3600:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del sent_arbitrage_opportunities[key]
        if key in current_arbitrage_opportunities:
            del current_arbitrage_opportunities[key]
        if key in arbitrage_start_times:
            del arbitrage_start_times[key]
        logger.debug(f"Удалена устаревшая связка: {key}")

async def fetch_dex_pairs():
    """Получает список пар с DexScreener"""
    try:
        async with aiohttp.ClientSession() as session:
            # Получаем топ-200 пар по объему
            async with session.get('https://api.dexscreener.com/latest/dex/volumes?limit=200') as response:
                if response.status == 200:
                    data = await response.json()
                    pairs = data.get('pairs', [])
                    
                    # Фильтруем только пары с USDT и достаточным объемом
                    filtered_pairs = []
                    for pair in pairs:
                        if (pair.get('quoteToken', {}).get('symbol') == 'USDT' and
                            pair.get('volume', {}).get('h24', 0) >= SETTINGS['DEX_CEX']['MIN_VOLUME_USD']):
                            filtered_pairs.append(pair)
                    
                    logger.info(f"Получено {len(filtered_pairs)} пар с DexScreener")
                    return filtered_pairs
                else:
                    logger.error(f"Ошибка получения данных DexScreener: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Ошибка получения пар DexScreener: {e}")
        return []

async def fetch_ticker_data(exchange, symbol: str):
    """Получает данные тикера с биржи"""
    try:
        ticker = await asyncio.get_event_loop().run_in_executor(
            None, exchange.fetch_ticker, symbol
        )

        if ticker:
            price = float(ticker['last']) if ticker.get('last') else None
            volume = None
            if ticker.get('quoteVolume') is not None:
                volume = float(ticker['quoteVolume'])
            elif ticker.get('baseVolume') is not None and price:
                volume = float(ticker['baseVolume']) * price

            logger.debug(f"Данные тикера {symbol} на {exchange.id}: цена={price}, объем={volume}")

            return {
                'price': price,
                'volume': volume,
                'symbol': symbol
            }
        return None
    except Exception as e:
        logger.warning(f"Ошибка данных {symbol} на {exchange.id}: {e}")
        return None

def load_markets_sync(exchange):
    """Синхронная загрузка рынков"""
    try:
        exchange.load_markets()
        logger.info(f"Рынки загружены для {exchange.id}")
        return exchange
    except Exception as e:
        logger.error(f"Ошибка загрузки {exchange.id}: {e}")
        return None

async def load_futures_exchanges():
    """Загружает фьючерсные биржи"""
    global FUTURES_EXCHANGES_LOADED, LAST_EXCHANGE_SETTINGS

    exchanges = {}
    for name, config in FUTURES_EXCHANGES.items():
        if not SETTINGS['EXCHANGES'][name]['ENABLED']:
            continue

        try:
            exchange = await asyncio.get_event_loop().run_in_executor(
                None, load_markets_sync, config["api"]
            )
            if exchange:
                exchanges[name] = {
                    "api": exchange,
                    "config": config
                }
                logger.info(f"{name.upper()} успешно загружена")
        except Exception as e:
            logger.error(f"Ошибка инициализации {name}: {e}")

    FUTURES_EXCHANGES_LOADED = exchanges
    LAST_EXCHANGE_SETTINGS = SETTINGS['EXCHANGES'].copy()
    return exchanges

def calculate_min_entry_amount(buy_price: float, sell_price: float, min_profit: float, buy_fee_percent: float,
                               sell_fee_percent: float) -> float:
    """Рассчитывает минимальную сумму входа"""
    profit_per_unit = sell_price * (1 - sell_fee_percent) - buy_price * (1 + buy_fee_percent)
    if profit_per_unit <= 0:
        return 0
    min_amount = min_profit / profit_per_unit
    return min_amount * buy_price

def calculate_profit(buy_price: float, sell_price: float, amount: float, buy_fee_percent: float,
                     sell_fee_percent: float) -> dict:
    """Рассчитывает прибыль"""
    buy_cost = amount * buy_price * (1 + buy_fee_percent)
    sell_revenue = amount * sell_price * (1 - sell_fee_percent)
    net_profit = sell_revenue - buy_cost
    profit_percent = (net_profit / buy_cost) * 100 if buy_cost > 0 else 0

    return {
        "net": net_profit,
        "percent": profit_percent,
        "entry_amount": amount * buy_price
    }

async def check_dex_cex_arbitrage():
    """Проверка DEX-CEX арбитража между DexScreener и MEXC фьючерсами"""
    logger.info("Запуск проверки DEX-CEX арбитража")

    if not SETTINGS['DEX_CEX']['ENABLED']:
        logger.info("DEX-CEX арбитраж отключен в настройках")
        return

    # Инициализация бирж
    await load_futures_exchanges()

    if not FUTURES_EXCHANGES_LOADED:
        logger.error("MEXC не загружена")
        return

    while SETTINGS['DEX_CEX']['ENABLED']:
        try:
            # Проверяем, изменились ли настройки бирж
            if LAST_EXCHANGE_SETTINGS != SETTINGS['EXCHANGES']:
                logger.info("Обнаружено изменение настроек бирж. Перезагружаем биржи...")
                await load_futures_exchanges()

                if not FUTURES_EXCHANGES_LOADED:
                    logger.error("MEXC не загружена после перезагрузки")
                    await asyncio.sleep(SETTINGS['DEX_CEX']['CHECK_INTERVAL'])
                    continue

            # Получаем пары с DexScreener
            dex_pairs = await fetch_dex_pairs()
            if not dex_pairs:
                logger.warning("Не удалось получить пары с DexScreener")
                await asyncio.sleep(SETTINGS['DEX_CEX']['CHECK_INTERVAL'])
                continue

            found_opportunities = 0
            
            for dex_pair in dex_pairs:
                try:
                    base_symbol = dex_pair['baseToken']['symbol']
                    dex_price = float(dex_pair.get('priceUsd', 0))
                    dex_volume = float(dex_pair.get('volume', {}).get('h24', 0))
                    dex_url = dex_pair.get('url', '')
                    network = dex_pair.get('chainId', 'N/A')

                    if dex_price <= 0:
                        continue

                    # Ищем соответствующую пару на MEXC
                    mexc_data = FUTURES_EXCHANGES_LOADED['mexc']
                    symbol = mexc_data["config"]["symbol_format"](base_symbol)

                    try:
                        # Проверяем существование рынка
                        market = mexc_data["api"].market(symbol)
                        if not mexc_data["config"]["is_futures"](market):
                            continue
                    except Exception:
                        # Рынок не найден, пропускаем
                        continue

                    # Получаем цену с MEXC
                    cex_ticker = await fetch_ticker_data(mexc_data["api"], symbol)
                    if not cex_ticker or not cex_ticker['price']:
                        continue

                    cex_price = cex_ticker['price']
                    cex_volume = cex_ticker.get('volume')

                    # Рассчитываем спред
                    spread = (dex_price - cex_price) / cex_price * 100

                    # Определяем направление арбитража
                    if spread > 0:
                        direction = "Лонг CEX / Шорт DEX"
                        buy_price = cex_price
                        sell_price = dex_price
                        buy_fee = SETTINGS['DEX_CEX']['CEX_TAKER_FEE']
                        sell_fee = SETTINGS['DEX_CEX']['DEX_TAKER_FEE']
                    else:
                        direction = "Шорт CEX / Лонг DEX"
                        buy_price = dex_price
                        sell_price = cex_price
                        buy_fee = SETTINGS['DEX_CEX']['DEX_TAKER_FEE']
                        sell_fee = SETTINGS['DEX_CEX']['CEX_TAKER_FEE']

                    abs_spread = abs(spread)

                    # Подготавливаем данные
                    dex_data = {
                        'price': dex_price,
                        'volume': dex_volume,
                        'dex_url': dex_url,
                        'network': network
                    }

                    cex_data = {
                        'price': cex_price,
                        'volume': cex_volume,
                        'exchange': 'mexc',
                        'url': mexc_data["config"]["url_format"](symbol.replace(':USDT', ''))
                    }

                    # Обновляем информацию о текущих арбитражных возможностях
                    update_current_arbitrage_opportunities(
                        'DEX_CEX', base_symbol, dex_data, cex_data, spread,
                        direction
                    )

                    # Проверяем сходимость цен для уведомления
                    duration = update_arbitrage_duration('DEX_CEX', base_symbol, dex_data, cex_data, spread)
                    if duration is not None:
                        await send_price_convergence_notification(
                            'DEX_CEX', base_symbol, dex_data, cex_data,
                            spread, direction, duration
                        )

                    if (SETTINGS['DEX_CEX']['THRESHOLD_PERCENT'] <= abs_spread <= 
                        SETTINGS['DEX_CEX']['MAX_THRESHOLD_PERCENT']):
                        
                        # Рассчитываем минимальную сумму для MIN_NET_PROFIT_USD
                        min_amount_for_profit = calculate_min_entry_amount(
                            buy_price=buy_price,
                            sell_price=sell_price,
                            min_profit=SETTINGS['DEX_CEX']['MIN_NET_PROFIT_USD'],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        if min_amount_for_profit <= 0:
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_entry_amount = SETTINGS['DEX_CEX']['MAX_ENTRY_AMOUNT_USDT']
                        min_entry_amount = max(min_amount_for_profit, SETTINGS['DEX_CEX']['MIN_ENTRY_AMOUNT_USDT'])

                        if min_entry_amount > max_entry_amount:
                            continue

                        # Рассчитываем прибыль
                        profit_min = calculate_profit(
                            buy_price=buy_price,
                            sell_price=sell_price,
                            amount=min_entry_amount / buy_price,
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        profit_max = calculate_profit(
                            buy_price=buy_price,
                            sell_price=sell_price,
                            amount=max_entry_amount / buy_price,
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        # Форматируем сообщение
                        utc_plus_3 = timezone(timedelta(hours=3))
                        current_time = datetime.now(utc_plus_3).strftime('%H:%M:%S')

                        def format_volume(vol):
                            if vol is None:
                                return "N/A"
                            if vol >= 1_000_000:
                                return f"${vol / 1_000_000:.1f}M"
                            if vol >= 1_000:
                                return f"${vol / 1_000:.1f}K"
                            return f"${vol:.1f}"

                        dex_volume_str = format_volume(dex_volume)
                        cex_volume_str = format_volume(cex_volume)

                        safe_base = html.escape(base_symbol)

                        message = (
                            f"🦄 <b>DEX-CEX Арбитраж:</b> <code>{safe_base}</code>\n"
                            f"▫️ <b>Разница цен:</b> {spread:.2f}%\n"
                            f"▫️ <b>Направление:</b> {direction}\n"
                            f"▫️ <b>Сумма входа:</b> ${min_entry_amount:.2f}-${max_entry_amount:.2f}\n\n"
                            
                            f"🟢 <b><a href='{dex_url}'>DEX (DexScreener)</a>:</b>\n"
                            f"   💰 Цена: <code>${dex_price:.8f}</code>\n"
                            f"   📊 Объем: {dex_volume_str}\n"
                            f"   🌐 Сеть: {network}\n"
                            f"   💸 Комиссия: {SETTINGS['DEX_CEX']['DEX_TAKER_FEE']*100:.2f}%\n\n"
                            
                            f"🔵 <b><a href='{cex_data['url']}'>CEX (MEXC Futures)</a>:</b>\n"
                            f"   💰 Цена: <code>${cex_price:.8f}</code>\n"
                            f"   📊 Объем: {cex_volume_str}\n"
                            f"   💸 Комиссия: {SETTINGS['DEX_CEX']['CEX_TAKER_FEE']*100:.3f}%\n\n"
                            
                            f"💰 <b>Чистая прибыль:</b> ${profit_min['net']:.2f}-${profit_max['net']:.2f} ({profit_max['percent']:.2f}%)\n\n"
                            f"⏱ {current_time}\n"
                        )

                        logger.info(f"Найдена DEX-CEX арбитражная возможность: {base_symbol} ({spread:.2f}%)")

                        # Отправляем сообщение в Telegram
                        await send_telegram_message(message)

                        # Добавляем связку в отправленные возможности
                        add_opportunity_to_sent(
                            'DEX_CEX', base_symbol, dex_data, cex_data, spread,
                            direction, min_entry_amount, max_entry_amount, profit_min, profit_max
                        )

                        found_opportunities += 1

                except Exception as e:
                    logger.error(f"Ошибка обработки пары {dex_pair.get('baseToken', {}).get('symbol', 'Unknown')}: {e}")

            # Очищаем устаревшие возможности
            cleanup_old_opportunities()

            logger.info(f"Цикл DEX-CEX арбитража завершен. Найдено возможностей: {found_opportunities}")
            await asyncio.sleep(SETTINGS['DEX_CEX']['CHECK_INTERVAL'])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле DEX-CEX арбитража: {e}")
            await asyncio.sleep(60)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 <b>DEX-CEX Arbitrage Bot</b>\n\n"
        "Мониторинг арбитражных возможностей между DEX (DexScreener) и CEX (MEXC Futures)\n\n"
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
        enabled_exchanges = [name for name, config in SETTINGS['EXCHANGES'].items() if config['ENABLED']]
        exchanges_status = ", ".join(enabled_exchanges) if enabled_exchanges else "Нет активных бирж"

        await update.message.reply_text(
            f"🤖 <b>Статус бота</b>\n\n"
            f"🦄 DEX-CEX арбитраж: {dex_cex_status}\n"
            f"🏛 Активные биржи: {exchanges_status}\n"
            f"📈 Активных связок: {len(sent_arbitrage_opportunities)}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "🤖 <b>DEX-CEX Arbitrage Bot</b>\n\n"
            "🔍 <b>Арбитражная стратегия:</b>\n"
            "• Если цена на DEX > CEX: Лонг на CEX / Шорт на DEX\n"
            "• Если цена на DEX < CEX: Шорт на CEX / Лонг на DEX\n\n"
            "📊 <b>Функционал:</b>\n"
            "• Автоматический поиск арбитражных возможностей\n"
            "• Уведомления о появлении и закрытии арбитража\n"
            "• Отслеживание длительности арбитражных сделок\n"
            "• Настройка параметров арбитража\n\n"
            "⚙️ <b>Основные настройки:</b>\n"
            "• Порог арбитража (минимальная разница цен)\n"
            "• Минимальный объем торгов\n"
            "• Суммы входа и ожидаемая прибыль\n"
            "• Комиссии DEX/CEX\n"
            "• Уведомления о схождении цен",
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

    if text == "🦄 DEX-CEX Арбитраж":
        await update.message.reply_text(
            "🦄 <b>Настройки DEX-CEX арбитража</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_dex_cex_settings_keyboard()
        )
        return DEX_CEX_SETTINGS

    elif text == "🏛 Биржи":
        await update.message.reply_text(
            "🏛 <b>Настройки бирж</b>\n\nВыберите биржу для включения/выключения:",
            parse_mode="HTML",
            reply_markup=get_exchange_settings_keyboard()
        )
        return SETTINGS_MENU

    elif text == "🔄 Сброс":
        global SETTINGS, LAST_EXCHANGE_SETTINGS
        SETTINGS = {
            "DEX_CEX": DEFAULT_DEX_CEX_SETTINGS.copy(),
            "EXCHANGES": EXCHANGE_SETTINGS.copy()
        }
        save_settings(SETTINGS)
        LAST_EXCHANGE_SETTINGS = None
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
        context.user_data['setting'] = ('DEX_CEX', 'MIN_NET_PROFIT_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимальной прибыли (текущее: ${SETTINGS['DEX_CEX']['MIN_NET_PROFIT_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("DEX комиссия:"):
        context.user_data['setting'] = ('DEX_CEX', 'DEX_TAKER_FEE')
        await update.message.reply_text(
            f"Введите новое значение для DEX комиссии (текущее: {SETTINGS['DEX_CEX']['DEX_TAKER_FEE']*100}%):"
        )
        return SETTING_VALUE

    elif text.startswith("CEX комиссия:"):
        context.user_data['setting'] = ('DEX_CEX', 'CEX_TAKER_FEE')
        await update.message.reply_text(
            f"Введите новое значение для CEX комиссии (текущее: {SETTINGS['DEX_CEX']['CEX_TAKER_FEE']*100}%):"
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

async def handle_exchange_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек бирж"""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    # Обработка включения/выключения бирж
    for exchange in SETTINGS['EXCHANGES'].keys():
        if text.startswith(f"{exchange}:"):
            SETTINGS['EXCHANGES'][exchange]['ENABLED'] = not SETTINGS['EXCHANGES'][exchange]['ENABLED']
            save_settings(SETTINGS)

            status = "✅ ВКЛ" if SETTINGS['EXCHANGES'][exchange]['ENABLED'] else "❌ ВЫКЛ"
            await update.message.reply_text(
                f"✅ Биржа {exchange.upper()} {status}",
                reply_markup=get_exchange_settings_keyboard()
            )
            return SETTINGS_MENU

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_exchange_settings_keyboard()
    )
    return SETTINGS_MENU

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
        if setting_key in ['THRESHOLD_PERCENT', 'MAX_THRESHOLD_PERCENT', 'PRICE_CONVERGENCE_THRESHOLD',
                          'DEX_TAKER_FEE', 'CEX_TAKER_FEE']:
            value = float(text)
            # Для комиссий преобразуем из процентов в десятичные
            if setting_key in ['DEX_TAKER_FEE', 'CEX_TAKER_FEE']:
                value = value / 100
        elif setting_key in ['CHECK_INTERVAL']:
            value = int(text)
        elif setting_key in ['MIN_VOLUME_USD', 'MIN_ENTRY_AMOUNT_USDT', 'MAX_ENTRY_AMOUNT_USDT', 'MIN_NET_PROFIT_USD']:
            value = float(text)
        else:
            value = text

        # Устанавливаем новое значение
        SETTINGS[arb_type][setting_key] = value
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

    # Запускаем арбитражные задачи в фоне
    loop = asyncio.get_event_loop()
    loop.create_task(check_dex_cex_arbitrage())

    logger.info("Бот запущен")

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
