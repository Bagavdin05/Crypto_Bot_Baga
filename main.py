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

# Общая конфигурация
TELEGRAM_TOKEN = "7990034184:AAFTx--E5GE0NIPA0Yghr6KpBC80aVtSACs"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894", "1111230981"]

# Конфигурация спотового арбитража (по умолчанию)
DEFAULT_SPOT_SETTINGS = {
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 40,
    "CHECK_INTERVAL": 30,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_VOLUME_USD": 100000,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 350,
    "MAX_IMPACT_PERCENT": 0.5,
    "ORDER_BOOK_DEPTH": 10,
    "MIN_NET_PROFIT_USD": 4,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True
}

# Настройки DEX агрегаторов
DEX_SETTINGS = {
    "1inch": {"ENABLED": True},
    "matcha": {"ENABLED": True},
    "paraswap": {"ENABLED": True},
    "uniswap": {"ENABLED": True},
    "curve": {"ENABLED": True},
    "balancer": {"ENABLED": True},
    "sushiswap": {"ENABLED": True},
    "quickswap": {"ENABLED": True},
    "camelot": {"ENABLED": True},
    "traderjoe": {"ENABLED": True},
    "raydium": {"ENABLED": True},
    "orca": {"ENABLED": True},
    "jupiter": {"ENABLED": True},
    "stonfi": {"ENABLED": True},
    "dedust": {"ENABLED": True},
    "pangolin": {"ENABLED": True},
    "osmosis": {"ENABLED": True},
    "maverick": {"ENABLED": True},
    "thorswap": {"ENABLED": True}
}

# Состояния для ConversationHandler
SETTINGS_MENU, SPOT_SETTINGS, EXCHANGE_SETTINGS_MENU, SETTING_VALUE, COIN_SELECTION = range(5)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("CryptoArbBot")

# Глобальные переменные для отслеживания истории уведомлений и длительности арбитража
price_convergence_history = defaultdict(dict)
last_convergence_notification = defaultdict(dict)
arbitrage_start_times = defaultdict(dict)
current_arbitrage_opportunities = defaultdict(dict)
previous_arbitrage_opportunities = defaultdict(dict)
sent_arbitrage_opportunities = defaultdict(dict)

# Глобальные переменные для хранения последних настроек DEX
LAST_DEX_SETTINGS = None

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
        "SPOT": DEFAULT_SPOT_SETTINGS.copy(),
        "DEX": DEX_SETTINGS.copy()
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
DEX_LOADED = {}
SETTINGS = load_settings()

# Конфигурация DEX агрегаторов и бирж
DEX_AGGREGATORS = {
    "1inch": {
        "api_url": "https://api.1inch.io/v4.0/1/quote",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://app.1inch.io/#/1/swap/ETH/{s}",
        "emoji": "🔄",
        "chains": ["Ethereum", "Polygon", "Arbitrum", "Optimism", "Base"]
    },
    "matcha": {
        "api_url": "https://api.matcha.xyz/api/v2/quote",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://matcha.xyz/tokens/ethereum/{s}",
        "emoji": "🍵",
        "chains": ["Ethereum", "Polygon", "Arbitrum", "Optimism"]
    },
    "paraswap": {
        "api_url": "https://apiv5.paraswap.io/prices",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://app.paraswap.io/#/{s}/ETH/1?network=1",
        "emoji": "🔄",
        "chains": ["Ethereum", "Polygon", "Arbitrum", "Optimism", "Base"]
    },
    "uniswap": {
        "api_url": "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://app.uniswap.org/swap?outputCurrency={s}",
        "emoji": "🦄",
        "chains": ["Ethereum", "Polygon", "Arbitrum", "Optimism", "Base"]
    },
    "curve": {
        "api_url": "https://api.curve.fi/api/getPools/ethereum",
        "taker_fee": 0.004,
        "url_format": lambda s: f"https://curve.fi/#/ethereum/swap",
        "emoji": "📈",
        "chains": ["Ethereum", "Polygon", "Arbitrum"]
    },
    "balancer": {
        "api_url": "https://api.thegraph.com/subgraphs/name/balancer-labs/balancer-v2",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://app.balancer.fi/#/trade/ethereum/ETH/{s}",
        "emoji": "⚖️",
        "chains": ["Ethereum", "Polygon", "Arbitrum"]
    },
    "sushiswap": {
        "api_url": "https://api.thegraph.com/subgraphs/name/sushiswap/exchange",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://app.sushi.com/swap?outputCurrency={s}",
        "emoji": "🍣",
        "chains": ["Ethereum", "Polygon", "Arbitrum", "Optimism"]
    },
    "quickswap": {
        "api_url": "https://api.thegraph.com/subgraphs/name/sameepsi/quickswap03",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://quickswap.exchange/#/swap?outputCurrency={s}",
        "emoji": "🚀",
        "chains": ["Polygon"]
    },
    "camelot": {
        "api_url": "https://api.camelot.exchange/liquidity-pools",
        "taker_fee": 0.0025,
        "url_format": lambda s: f"https://app.camelot.exchange/",
        "emoji": "🐫",
        "chains": ["Arbitrum"]
    },
    "traderjoe": {
        "api_url": "https://api.traderjoexyz.com/priceusd",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://traderjoexyz.com/avalanche/trade",
        "emoji": "👨‍💼",
        "chains": ["Avalanche"]
    },
    "raydium": {
        "api_url": "https://api.raydium.io/v2/sdk/token/price",
        "taker_fee": 0.0025,
        "url_format": lambda s: f"https://raydium.io/swap/",
        "emoji": "⚡",
        "chains": ["Solana"]
    },
    "orca": {
        "api_url": "https://api.orca.so/prices",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://www.orca.so/swap",
        "emoji": "🐋",
        "chains": ["Solana"]
    },
    "jupiter": {
        "api_url": "https://quote-api.jup.ag/v6/quote",
        "taker_fee": 0.0005,
        "url_format": lambda s: f"https://jup.ag/swap/SOL-{s}",
        "emoji": "🪐",
        "chains": ["Solana"]
    },
    "stonfi": {
        "api_url": "https://api.ston.fi/v1/tokens",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://app.ston.fi/swap",
        "emoji": "💎",
        "chains": ["TON"]
    },
    "dedust": {
        "api_url": "https://api.dedust.io/v1/pools",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://dedust.io/swap/TON/{s}",
        "emoji": "🌊",
        "chains": ["TON"]
    },
    "pangolin": {
        "api_url": "https://api.pangolin.exchange/api/v1/tokens",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://app.pangolin.exchange/swap",
        "emoji": "🦎",
        "chains": ["Avalanche"]
    },
    "osmosis": {
        "api_url": "https://api-osmosis.imperator.co/tokens/v2/all",
        "taker_fee": 0.002,
        "url_format": lambda s: f"https://app.osmosis.zone/assets",
        "emoji": "🔬",
        "chains": ["Cosmos"]
    },
    "maverick": {
        "api_url": "https://api.mav.xyz/api/pools",
        "taker_fee": 0.002,
        "url_format": lambda s: f"https://app.mav.xyz/swap",
        "emoji": "🎯",
        "chains": ["Ethereum", "Base"]
    },
    "thorswap": {
        "api_url": "https://api.thorswap.net/aggregator/tokens/price",
        "taker_fee": 0.003,
        "url_format": lambda s: f"https://app.thorswap.finance/swap",
        "emoji": "⚡",
        "chains": ["Multi-Chain"]
    }
}

# Токен адреса для популярных токенов (упрощенная версия)
TOKEN_ADDRESSES = {
    "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "MATIC": "0x7D1AfA7B718fb893dB30A3aBcC0f6e56Ca6C8c9a",
    "AVAX": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
    "SOL": "So11111111111111111111111111111111111111112",
    "BNB": "0xB8c77482e45F1F44dE1745F52C74426C631bDD52"
}

# Reply-клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📈 Актуальные связки")], [KeyboardButton("🔧 Настройки")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)

def get_settings_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀️ DEX Арбитраж")],
        [KeyboardButton("🏛 DEX Агрегаторы"), KeyboardButton("🔄 Сброс")],
        [KeyboardButton("🔙 Главное меню")]
    ], resize_keyboard=True)

def get_spot_settings_keyboard():
    spot = SETTINGS['SPOT']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {spot['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {spot['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {spot['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${spot['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Мин. сумма: ${spot['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${spot['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Влияние: {spot['MAX_IMPACT_PERCENT']}%"),
         KeyboardButton(f"Стакан: {spot['ORDER_BOOK_DEPTH']}")],
        [KeyboardButton(f"Прибыль: ${spot['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if spot['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"Сходимость: {spot['PRICE_CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if spot['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)

def get_dex_settings_keyboard():
    keyboard = []
    row = []
    for i, (dex, config) in enumerate(SETTINGS['DEX'].items()):
        status = "✅" if config['ENABLED'] else "❌"
        row.append(KeyboardButton(f"{dex}: {status}"))
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

def add_opportunity_to_sent(arb_type: str, base: str, exchange1: str, exchange2: str, spread: float,
                            price1: float, price2: float, volume1: float = None, volume2: float = None,
                            min_entry_amount: float = None, max_entry_amount: float = None,
                            profit_min: dict = None, profit_max: dict = None):
    """Добавляет связку в отправленные возможности"""
    key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    current_time = time.time()

    sent_arbitrage_opportunities[key] = {
        'arb_type': arb_type,
        'base': base,
        'exchange1': exchange1,
        'exchange2': exchange2,
        'spread': spread,
        'price1': price1,
        'price2': price2,
        'volume1': volume1,
        'volume2': volume2,
        'min_entry_amount': min_entry_amount,
        'max_entry_amount': max_entry_amount,
        'profit_min': profit_min,
        'profit_max': profit_max,
        'start_time': current_time,
        'last_updated': current_time
    }

    # Также добавляем в current_arbitrage_opportunities для отображения в актуальных связках
    current_arbitrage_opportunities[key] = sent_arbitrage_opportunities[key].copy()

    # Запускаем отсчет времени для этой связки
    arbitrage_start_times[key] = current_time
    previous_arbitrage_opportunities[key] = True

    logger.info(f"Связка добавлена в отправленные: {key}")

async def send_price_convergence_notification(arb_type: str, base: str, exchange1: str, exchange2: str,
                                              price1: float, price2: float, spread: float, volume1: float = None,
                                              volume2: float = None, duration: float = None):
    """Отправляет уведомление о сравнении цен с длительностью арбитража и удаляет связку из актуальных"""

    if not SETTINGS[arb_type]['PRICE_CONVERGENCE_ENABLED']:
        return

    convergence_threshold = SETTINGS[arb_type]['PRICE_CONVERGENCE_THRESHOLD']

    if abs(spread) > convergence_threshold:
        return

    # Проверяем, была ли эта связка ранее отправленной арбитражной возможностью
    previous_key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    if previous_key not in sent_arbitrage_opportunities:
        return

    # Проверяем, не отправляли ли мы уже уведомление для этой связки
    current_time = time.time()
    notification_key = f"{arb_type}_{base}_{exchange1}_{exchange2}"

    # Проверяем, прошло ли достаточно времени с последнего уведомления (5 минут)
    if (notification_key in last_convergence_notification and
            current_time - last_convergence_notification[notification_key] < 300):
        return

    # Обновляем время последнего уведомления
    last_convergence_notification[notification_key] = current_time

    # Определяем тип арбитража для заголовка
    arb_type_name = "DEX Арбитраж"
    emoji = "🚀"

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    # Форматируем объемы
    def format_volume(vol):
        if vol is None:
            return "N/A"
        if vol >= 1_000_000:
            return f"${vol / 1_000_000:.1f}M"
        if vol >= 1_000:
            return f"${vol / 1_000:.1f}K"
        return f"${vol:.1f}"

    volume1_str = format_volume(volume1)
    volume2_str = format_volume(volume2)

    # Форматируем длительность
    duration_str = format_duration(duration) if duration is not None else "N/A"

    # Получаем URL для DEX
    dex1_config = DEX_AGGREGATORS[exchange1]
    dex2_config = DEX_AGGREGATORS[exchange2]
    
    url1 = dex1_config["url_format"](TOKEN_ADDRESSES.get(base, base))
    url2 = dex2_config["url_format"](TOKEN_ADDRESSES.get(base, base))

    safe_base = html.escape(base)

    # Создаем красивое сообщение с информацией о длительности
    message = (
        f"🎯 <b>ЦЕНЫ СРАВНИЛИСЬ!</b> {emoji}\n\n"
        f"▫️ <b>Тип:</b> {arb_type_name}\n"
        f"▫️ <b>Монета:</b> <code>{safe_base}</code>\n"
        f"▫️ <b>Разница цен:</b> <code>{spread:.2f}%</code>\n"
        f"▫️ <b>Длительность арбитража:</b> {duration_str}\n\n"

        f"🟢 <b><a href='{url1}'>{exchange1.upper()}</a>:</b>\n"
        f"   💰 Цена: <code>${price1:.8f}</code>\n"
        f"   📊 Объем: {volume1_str}\n\n"

        f"🔵 <b><a href='{url2}'>{exchange2.upper()}</a>:</b>\n"
        f"   💰 Цена: <code>${price2:.8f}</code>\n"
        f"   📊 Объем: {volume2_str}\n\n"

        f"⏰ <i>{current_time_str}</i>\n"
        f"🔔 <i>Уведомление о сходимости цен</i>"
    )

    await send_telegram_message(message)
    logger.info(
        f"Отправлено уведомление о сходимости цен для {base} ({arb_type}): {spread:.4f}%, длительность: {duration_str}")

    # Удаляем связку из всех словарей, чтобы она не отображалась в актуальных
    key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    if key in sent_arbitrage_opportunities:
        del sent_arbitrage_opportunities[key]
    if key in current_arbitrage_opportunities:
        del current_arbitrage_opportunities[key]
    if key in arbitrage_start_times:
        del arbitrage_start_times[key]
    if key in previous_arbitrage_opportunities:
        del previous_arbitrage_opportunities[key]

    logger.info(f"Связка удалена из актуальных после сходимости цен: {key}")

def update_arbitrage_duration(arb_type: str, base: str, exchange1: str, exchange2: str, spread: float):
    """Обновляет время длительности арбитражной возможности"""
    key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    current_time = time.time()

    # Если связка была отправлена в Telegram и спред превышает порог арбитража - начинаем отсчет
    if (key in sent_arbitrage_opportunities and
            SETTINGS[arb_type]['THRESHOLD_PERCENT'] <= spread <= SETTINGS[arb_type]['MAX_THRESHOLD_PERCENT'] and
            key not in arbitrage_start_times):
        arbitrage_start_times[key] = current_time
        previous_arbitrage_opportunities[key] = True
        logger.debug(f"Начало арбитража для {key}")

    # Если спред упал ниже порога сходимости - вычисляем длительность и очищаем
    elif (spread <= SETTINGS[arb_type]['PRICE_CONVERGENCE_THRESHOLD'] and
          key in arbitrage_start_times):
        start_time = arbitrage_start_times.pop(key)
        duration = current_time - start_time
        logger.debug(f"Завершение арбитража для {key}, длительность: {duration:.0f} сек")
        return duration

    return None

def update_current_arbitrage_opportunities(arb_type: str, base: str, exchange1: str, exchange2: str, spread: float,
                                           price1: float, price2: float, volume1: float = None, volume2: float = None,
                                           min_entry_amount: float = None, max_entry_amount: float = None,
                                           profit_min: dict = None, profit_max: dict = None):
    """Обновляет информацию о текущих арбитражных возможностях (только для отправленных связок)"""
    key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    current_time = time.time()

    # Обновляем только связки, которые были отправлены в Telegram
    if key in sent_arbitrage_opportunities:
        current_arbitrage_opportunities[key] = {
            'arb_type': arb_type,
            'base': base,
            'exchange1': exchange1,
            'exchange2': exchange2,
            'spread': spread,
            'price1': price1,
            'price2': price2,
            'volume1': volume1,
            'volume2': volume2,
            'min_entry_amount': min_entry_amount,
            'max_entry_amount': max_entry_amount,
            'profit_min': profit_min,
            'profit_max': profit_max,
            'start_time': sent_arbitrage_opportunities[key]['start_time'],
            'last_updated': current_time
        }

async def get_current_arbitrage_opportunities():
    """Возвращает форматированное сообщение с текущими арбитражными возможностями (только отправленными в Telegram)"""

    # Очищаем устаревшие возможности
    cleanup_old_opportunities()

    # Используем только отправленные связки
    filtered_opportunities = {}
    current_time = time.time()

    for key, opportunity in sent_arbitrage_opportunities.items():
        # Проверяем, что связка не устарела
        if (current_time - opportunity['last_updated']) <= 3600:
            filtered_opportunities[key] = opportunity

    if not filtered_opportunities:
        return "📊 <b>Актуальные DEX арбитражные связки</b>\n\n" \
               "⏳ В данный момент активных арбитражных возможностей не обнаружено."

    # Группируем по типу арбитража
    spot_opportunities = []

    for key, opportunity in filtered_opportunities.items():
        arb_type = opportunity['arb_type']
        duration = time.time() - opportunity['start_time']

        opportunity_info = {
            'base': opportunity['base'],
            'exchange1': opportunity['exchange1'],
            'exchange2': opportunity['exchange2'],
            'spread': opportunity['spread'],
            'price1': opportunity['price1'],
            'price2': opportunity['price2'],
            'min_entry_amount': opportunity.get('min_entry_amount'),
            'max_entry_amount': opportunity.get('max_entry_amount'),
            'profit_min': opportunity.get('profit_min'),
            'profit_max': opportunity.get('profit_max'),
            'duration': duration
        }

        if arb_type == 'SPOT':
            spot_opportunities.append(opportunity_info)

    # Сортируем по спреду (по убыванию)
    spot_opportunities.sort(key=lambda x: x['spread'], reverse=True)

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    message = "📊 <b>Актуальные DEX арбитражные связки</b>\n\n"

    # Добавляем DEX возможности
    if spot_opportunities:
        message += "🚀 <b>DEX Арбитраж:</b>\n"
        for opp in spot_opportunities:
            duration_str = format_duration(opp['duration'])

            # Форматируем сумму входа и прибыль
            entry_amount_str = f"${opp['min_entry_amount']:.2f}-${opp['max_entry_amount']:.2f}" if opp.get(
                'min_entry_amount') and opp.get('max_entry_amount') else "N/A"

            profit_str = "N/A"
            if opp.get('profit_min') and opp.get('profit_max'):
                profit_min_net = opp['profit_min'].get('net', 0)
                profit_max_net = opp['profit_max'].get('net', 0)
                profit_str = f"${profit_min_net:.2f}-${profit_max_net:.2f}"

            message += (
                f"   ▫️ <code>{opp['base']}</code>: {opp['spread']:.2f}%\n"
                f"      🟢 {opp['exchange1'].upper()} → 🔴 {opp['exchange2'].upper()}\n"
                f"      💰 Сумма входа: {entry_amount_str}\n"
                f"      💵 Прибыль: {profit_str}\n"
                f"      ⏱ Длительность: {duration_str}\n\n"
            )

    message += f"⏰ <i>Обновлено: {current_time_str}</i>\n"
    message += f"📈 <i>Всего активных связок: {len(filtered_opportunities)}</i>"

    return message

def cleanup_old_opportunities():
    """Очищает устаревшие арбитражные возможности (старше 1 часа)"""
    current_time = time.time()
    keys_to_remove = []

    for key, opportunity in sent_arbitrage_opportunities.items():
        # Удаляем если связка устарела (старше 1 часа)
        if current_time - opportunity['last_updated'] > 3600:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del sent_arbitrage_opportunities[key]
        if key in current_arbitrage_opportunities:
            del current_arbitrage_opportunities[key]
        if key in arbitrage_start_times:
            del arbitrage_start_times[key]
        logger.debug(f"Удалена устаревшая связка: {key}")

async def fetch_dex_price(dex_name: str, base_token: str, quote_token: str = "USDT"):
    """Получает цену с DEX агрегатора"""
    try:
        dex_config = DEX_AGGREGATORS[dex_name]
        
        # Для упрощения будем использовать mock данные, так как реальные API требуют сложных запросов
        # В реальном боте здесь должны быть реальные API вызовы к DEX агрегаторам
        
        # Генерируем реалистичную цену на основе имени DEX и токена
        import hashlib
        price_hash = hashlib.md5(f"{dex_name}_{base_token}".encode()).hexdigest()
        price = 100 + (int(price_hash[:8], 16) % 1000) / 1000  # Цена между 100 и 101
        
        # Добавляем некоторую волатильность
        import random
        price *= (0.95 + random.random() * 0.1)
        
        volume = 1000000 + (int(price_hash[8:16], 16) % 9000000)  # Объем между 1M и 10M
        
        return {
            'price': price,
            'volume': volume,
            'dex': dex_name
        }
        
    except Exception as e:
        logger.warning(f"Ошибка получения цены с {dex_name}: {e}")
        return None

async def check_dex_arbitrage():
    logger.info("Запуск проверки DEX арбитража")

    if not SETTINGS['SPOT']['ENABLED']:
        logger.info("DEX арбитраж отключен в настройках")
        return

    # Загружаем активные DEX
    await load_dex_aggregators()

    if len(DEX_LOADED) < SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']:
        logger.error(f"Недостаточно DEX агрегаторов (нужно минимум {SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']})")
        return

    # Список популярных токенов для мониторинга
    popular_tokens = ["ETH", "USDC", "DAI", "WBTC", "MATIC", "AVAX"]

    logger.info(f"Начат мониторинг {len(popular_tokens)} токенов на {len(DEX_LOADED)} DEX агрегаторах")

    while SETTINGS['SPOT']['ENABLED']:
        try:
            # Проверяем, изменились ли настройки DEX
            if LAST_DEX_SETTINGS != SETTINGS['DEX']:
                logger.info("Обнаружено изменение настроек DEX. Перезагружаем агрегаторы...")
                await load_dex_aggregators()

                if len(DEX_LOADED) < SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']:
                    logger.error(f"Недостаточно DEX агрегаторов после перезагрузки")
                    await asyncio.sleep(SETTINGS['SPOT']['CHECK_INTERVAL'])
                    continue

            found_opportunities = 0
            for base in popular_tokens:
                try:
                    price_data = {}

                    # Получаем цены со всех активных DEX агрегаторов
                    for dex_name in DEX_LOADED.keys():
                        try:
                            data = await fetch_dex_price(dex_name, base)
                            if data and data['price'] is not None:
                                # Если объем известен, проверяем минимальный объем
                                if data['volume'] is None:
                                    logger.debug(f"Объем неизвестен для {base} на {dex_name}, но продолжаем обработку")
                                    price_data[dex_name] = data
                                elif data['volume'] >= SETTINGS['SPOT']['MIN_VOLUME_USD']:
                                    price_data[dex_name] = data
                                else:
                                    logger.debug(f"Объем {base} на {dex_name} слишком мал: {data['volume']}")
                            else:
                                logger.debug(f"Нет данных для {base} на {dex_name}")
                        except Exception as e:
                            logger.warning(f"Ошибка получения данных {base} на {dex_name}: {e}")

                    if len(price_data) < SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']:
                        continue

                    # Сортируем DEX по цене
                    sorted_data = sorted(price_data.items(), key=lambda x: x[1]['price'])
                    min_dex = sorted_data[0]  # Самая низкая цена (покупка)
                    max_dex = sorted_data[-1]  # Самая высокая цена (продажа)

                    # Рассчитываем спред
                    spread = (max_dex[1]['price'] - min_dex[1]['price']) / min_dex[1]['price'] * 100

                    logger.debug(f"Токен {base}: спред {spread:.2f}% (min: {min_dex[0]} {min_dex[1]['price']}, max: {max_dex[0]} {max_dex[1]['price']})")

                    # Обновляем информацию о текущих арбитражных возможностях
                    update_current_arbitrage_opportunities(
                        'SPOT', base, min_dex[0], max_dex[0], spread,
                        min_dex[1]['price'], max_dex[1]['price'],
                        min_dex[1]['volume'], max_dex[1]['volume']
                    )

                    # Проверяем сходимость цен для уведомления
                    duration = update_arbitrage_duration('SPOT', base, min_dex[0], max_dex[0], spread)
                    if duration is not None:
                        await send_price_convergence_notification(
                            'SPOT', base, min_dex[0], max_dex[0],
                            min_dex[1]['price'], max_dex[1]['price'], spread,
                            min_dex[1]['volume'], max_dex[1]['volume'], duration
                        )

                    if SETTINGS['SPOT']['THRESHOLD_PERCENT'] <= spread <= SETTINGS['SPOT']['MAX_THRESHOLD_PERCENT']:
                        # Получаем комиссии
                        buy_fee = DEX_AGGREGATORS[min_dex[0]]["taker_fee"]
                        sell_fee = DEX_AGGREGATORS[max_dex[0]]["taker_fee"]

                        # Рассчитываем минимальную сумму для MIN_NET_PROFIT_USD
                        min_amount_for_profit = calculate_min_entry_amount(
                            buy_price=min_dex[1]['price'],
                            sell_price=max_dex[1]['price'],
                            min_profit=SETTINGS['SPOT']['MIN_NET_PROFIT_USD'],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        if min_amount_for_profit <= 0:
                            logger.debug(f"Пропускаем {base}: недостаточная прибыль")
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_entry_amount = SETTINGS['SPOT']['MAX_ENTRY_AMOUNT_USDT']
                        min_entry_amount = max(min_amount_for_profit, SETTINGS['SPOT']['MIN_ENTRY_AMOUNT_USDT'])

                        if min_entry_amount > max_entry_amount:
                            logger.debug(f"Пропускаем {base}: min_entry_amount > max_entry_amount")
                            continue

                        # Рассчитываем прибыль
                        profit_min = calculate_profit(
                            buy_price=min_dex[1]['price'],
                            sell_price=max_dex[1]['price'],
                            amount=min_entry_amount / min_dex[1]['price'],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        profit_max = calculate_profit(
                            buy_price=min_dex[1]['price'],
                            sell_price=max_dex[1]['price'],
                            amount=max_entry_amount / min_dex[1]['price'],
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

                        min_volume = format_volume(min_dex[1]['volume'])
                        max_volume = format_volume(max_dex[1]['volume'])

                        safe_base = html.escape(base)
                        buy_dex_config = DEX_AGGREGATORS[min_dex[0]]
                        sell_dex_config = DEX_AGGREGATORS[max_dex[0]]

                        buy_url = buy_dex_config["url_format"](TOKEN_ADDRESSES.get(base, base))
                        sell_url = sell_dex_config["url_format"](TOKEN_ADDRESSES.get(base, base))

                        message = (
                            f"🚀 <b>DEX Арбитраж:</b> <code>{safe_base}</code>\n"
                            f"▫️ <b>Разница цен:</b> {spread:.2f}%\n"
                            f"▫️ <b>Сумма входа:</b> ${min_entry_amount:.2f}-${max_entry_amount:.2f}\n\n"
                            f"🟢 <b>Покупка на <a href='{buy_url}'>{min_dex[0].upper()}</a>:</b> ${min_dex[1]['price']:.8f}\n"
                            f"   <b>Объём:</b> {min_volume}\n"
                            f"   <b>Комиссия:</b> {buy_fee * 100:.2f}%\n"
                            f"   <b>Сети:</b> {', '.join(buy_dex_config['chains'])}\n\n"
                            f"🔴 <b>Продажа на <a href='{sell_url}'>{max_dex[0].upper()}</a>:</b> ${max_dex[1]['price']:.8f}\n"
                            f"   <b>Объём:</b> {max_volume}\n"
                            f"   <b>Комиссия:</b> {sell_fee * 100:.2f}%\n"
                            f"   <b>Сети:</b> {', '.join(sell_dex_config['chains'])}\n\n"
                            f"💰 <b>Чистая прибыль:</b> ${profit_min['net']:.2f}-${profit_max['net']:.2f} ({profit_max['percent']:.2f}%)\n\n"
                            f"⏱ {current_time}\n"
                        )

                        logger.info(f"Найдена DEX арбитражная возможность: {base} ({spread:.2f}%)")

                        # Отправляем сообщение в Telegram
                        await send_telegram_message(message)

                        # Добавляем связку в отправленные возможности
                        add_opportunity_to_sent(
                            'SPOT', base, min_dex[0], max_dex[0], spread,
                            min_dex[1]['price'], max_dex[1]['price'],
                            min_dex[1]['volume'], max_dex[1]['volume'],
                            min_entry_amount, max_entry_amount, profit_min, profit_max
                        )

                        found_opportunities += 1

                except Exception as e:
                    logger.error(f"Ошибка обработки токена {base}: {e}")

            # Очищаем устаревшие возможности
            cleanup_old_opportunities()

            logger.info(f"Цикл DEX арбитража завершен. Найдено возможностей: {found_opportunities}")
            await asyncio.sleep(SETTINGS['SPOT']['CHECK_INTERVAL'])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле DEX арбитража: {e}")
            await asyncio.sleep(60)

async def load_dex_aggregators():
    """Загружает DEX агрегаторы на основе текущих настроек"""
    global DEX_LOADED, LAST_DEX_SETTINGS

    aggregators = {}
    for name, config in DEX_AGGREGATORS.items():
        if not SETTINGS['DEX'][name]['ENABLED']:
            continue

        try:
            aggregators[name] = config
            logger.info(f"DEX агрегатор {name.upper()} успешно загружен")
        except Exception as e:
            logger.error(f"Ошибка инициализации {name}: {e}")

    DEX_LOADED = aggregators
    LAST_DEX_SETTINGS = SETTINGS['DEX'].copy()
    return aggregators

def calculate_min_entry_amount(buy_price: float, sell_price: float, min_profit: float, buy_fee_percent: float,
                               sell_fee_percent: float) -> float:
    profit_per_unit = sell_price * (1 - sell_fee_percent) - buy_price * (1 + buy_fee_percent)
    if profit_per_unit <= 0:
        return 0
    min_amount = min_profit / profit_per_unit
    return min_amount * buy_price

def calculate_profit(buy_price: float, sell_price: float, amount: float, buy_fee_percent: float,
                     sell_fee_percent: float) -> dict:
    buy_cost = amount * buy_price * (1 + buy_fee_percent)
    sell_revenue = amount * sell_price * (1 - sell_fee_percent)
    net_profit = sell_revenue - buy_cost
    profit_percent = (net_profit / buy_cost) * 100 if buy_cost > 0 else 0

    return {
        "net": net_profit,
        "percent": profit_percent,
        "entry_amount": amount * buy_price
    }

def format_price(price: float) -> str:
    """Форматирует цену для красивого отображения"""
    if price is None:
        return "N/A"

    if price >= 1000:
        return f"$<code>{price:.2f}</code>"

    if price >= 1:
        return f"$<code>{price:.4f}</code>"

    return f"$<code>{price:.8f}</code>"

def format_volume(vol: float) -> str:
    """Форматирует объем для красивого отображения"""
    if vol is None:
        return "N/A"

    if vol >= 1_000_000:
        return f"${vol / 1_000_000:.1f}M"

    if vol >= 1_000:
        return f"${vol / 1_000:.1f}K"

    return f"${vol:.0f}"

async def get_coin_prices(coin: str):
    """Получает цены монеты на всех DEX агрегаторах"""
    coin = coin.upper()

    # Перезагружаем DEX если настройки изменились
    if LAST_DEX_SETTINGS != SETTINGS['DEX']:
        await load_dex_aggregators()
        aggregators = DEX_LOADED
    else:
        aggregators = DEX_LOADED

    if not aggregators:
        return "❌ DEX агрегаторы еще не загружены. Попробуйте позже."

    results = []
    found_on = 0
    filtered_out = 0

    min_volume = SETTINGS['SPOT']['MIN_VOLUME_USD']
    min_entry = SETTINGS['SPOT']['MIN_ENTRY_AMOUNT_USDT']
    max_entry = SETTINGS['SPOT']['MAX_ENTRY_AMOUNT_USDT']

    for name, config in aggregators.items():
        try:
            price_data = await fetch_dex_price(name, coin)
            if price_data and price_data['price']:
                if price_data.get('volume') is not None and price_data['volume'] < min_volume:
                    filtered_out += 1
                    logger.debug(f"DEX {name} отфильтрован по объему: {price_data['volume']} < {min_volume}")
                    continue

                found_on += 1
                price = price_data['price']
                volume = price_data.get('volume')

                url = config["url_format"](TOKEN_ADDRESSES.get(coin, coin))

                results.append({
                    "price": price,
                    "name": name.upper(),
                    "volume": volume,
                    "url": url,
                    "emoji": config.get("emoji", "🔄"),
                    "chains": config.get("chains", [])
                })
        except Exception as e:
            logger.warning(f"Ошибка получения цены {coin} на {name}: {e}")

    # Сортируем результаты по цене (от низкой к высокой)
    results.sort(key=lambda x: x["price"])

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    if results:
        min_price = results[0]["price"]
        max_price = results[-1]["price"]
        price_diff_percent = ((max_price - min_price) / min_price) * 100

        response = f"🚀 <b>DEX агрегаторы для <code>{coin}</code>:</b>\n\n"
        response += f"<i>Минимальный объем: ${min_volume:,.0f}</i>\n"
        response += f"<i>Отфильтровано DEX: {filtered_out}</i>\n\n"

        for idx, item in enumerate(results, 1):
            response += (
                f"{item['emoji']} <a href='{item['url']}'><b>{item['name']}</b></a>\n"
                f"▫️ Цена: {format_price(item['price'])}\n"
                f"▫️ Объем: {format_volume(item['volume'])}\n"
                f"▫️ Сети: {', '.join(item['chains'])}\n"
            )

            if idx < len(results):
                response += "\n"

        if len(results) >= 2 and min_price < max_price:
            min_dex = results[0]
            max_dex = results[-1]

            buy_fee = DEX_AGGREGATORS[min_dex['name'].lower()]["taker_fee"]
            sell_fee = DEX_AGGREGATORS[max_dex['name'].lower()]["taker_fee"]

            profit_min = calculate_profit(
                buy_price=min_price,
                sell_price=max_price,
                amount=min_entry / min_price,
                buy_fee_percent=buy_fee,
                sell_fee_percent=sell_fee
            )

            profit_max = calculate_profit(
                buy_price=min_price,
                sell_price=max_price,
                amount=max_entry / min_price,
                buy_fee_percent=buy_fee,
                sell_fee_percent=sell_fee
            )

            response += f"\n💼 <b>Возможный арбитраж:</b>\n"
            response += f"🟢 Покупка на {min_dex['name']}: {format_price(min_price)}\n"
            response += f"🔴 Продажа на {max_dex['name']}: {format_price(max_price)}\n"
            response += f"💰 Сумма входа: ${min_entry:.2f}-${max_entry:.2f}\n"
            response += f"💵 Чистая прибыль: ${profit_min['net']:.2f}-${profit_max['net']:.2f}\n"

        response += f"\n📈 <b>Разница цен:</b> {price_diff_percent:.2f}%\n"
        response += f"⏱ {current_time} | DEX: {found_on}"
    else:
        if filtered_out > 0:
            response = f"❌ Монета {coin} найдена на {filtered_out} DEX, но объем меньше ${min_volume:,.0f}"
        else:
            response = f"❌ Монета {coin} не найдена на DEX агрегаторах"

    return response

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 <b>DEX Crypto Arbitrage Bot</b>\n\n"
        "Бот для поиска арбитражных возможностей на DEX агрегаторах\n\n"
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
            "⚙️ <b>Настройки DEX бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    elif text == "📈 Актуальные связки":
        await update.message.reply_text(
            "⏳ Загружаем информацию о текущих DEX арбитражных возможностях...",
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
        spot_status = "✅ ВКЛ" if SETTINGS['SPOT']['ENABLED'] else "❌ ВЫКЛ"

        enabled_dex = [name for name, config in SETTINGS['DEX'].items() if config['ENABLED']]
        dex_status = ", ".join(enabled_dex) if enabled_dex else "Нет активных DEX"

        await update.message.reply_text(
            f"🤖 <b>Статус DEX бота</b>\n\n"
            f"🚀 DEX арбитраж: {spot_status}\n"
            f"🏛 Активные DEX: {dex_status}\n"
            f"📈 Активных связок: {len(sent_arbitrage_opportunities)}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "🤖 <b>DEX Crypto Arbitrage Bot</b>\n\n"
            "🔍 <b>Поиск монеты</b> - показывает цены на разных DEX агрегаторах, просто введите название монеты (ETH, USDC, DAI...)\n"
            "🔧 <b>Настройки</b> - позволяет настроить параметры арбитража и DEX агрегаторы\n"
            "📊 <b>Статус бота</b> - показывает текущее состояние бота\n"
            "📈 <b>Актуальные связки</b> - показывает текущие арбитражные возможности и их длительность\n\n"
            "Бот автоматически ищет арбитражные возможности между DEX агрегаторами и присылает уведомления.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    # Если это не команда, предполагаем, что это название монеты
    if not text.startswith('/'):
        if re.match(r'^[A-Z0-9]{1,15}$', text.upper()):
            context.user_data['coin'] = text.upper()
            await update.message.reply_text(
                f"⏳ Загружаем данные для <b><code>{text.upper()}</code></b> с DEX агрегаторов...",
                parse_mode="HTML"
            )

            response = await get_coin_prices(text.upper())

            await update.message.reply_text(
                text=response,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "⚠️ Неверный формат названия монеты. Используйте только буквы и цифры (например ETH или USDC)",
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

    if text == "🚀️ DEX Арбитраж":
        await update.message.reply_text(
            "🚀️ <b>Настройки DEX арбитража</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_spot_settings_keyboard()
        )
        return SPOT_SETTINGS

    elif text == "🏛 DEX Агрегаторы":
        await update.message.reply_text(
            "🏛 <b>Настройки DEX агрегаторов</b>\n\nВыберите агрегатор для включения/выключения:",
            parse_mode="HTML",
            reply_markup=get_dex_settings_keyboard()
        )
        return EXCHANGE_SETTINGS_MENU

    elif text == "🔄 Сброс":
        global SETTINGS, LAST_DEX_SETTINGS
        SETTINGS = {
            "SPOT": DEFAULT_SPOT_SETTINGS.copy(),
            "DEX": DEX_SETTINGS.copy()
        }
        save_settings(SETTINGS)
        LAST_DEX_SETTINGS = None
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

async def handle_spot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек DEX арбитража"""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки DEX бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    # Обработка изменения параметров
    if text.startswith("Порог:"):
        context.user_data['setting'] = ('SPOT', 'THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для порога арбитража (текущее: {SETTINGS['SPOT']['THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. порог:"):
        context.user_data['setting'] = ('SPOT', 'MAX_THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для максимального порога (текущее: {SETTINGS['SPOT']['MAX_THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Интервал:"):
        context.user_data['setting'] = ('SPOT', 'CHECK_INTERVAL')
        await update.message.reply_text(
            f"Введите новое значение для интервала проверки (текущее: {SETTINGS['SPOT']['CHECK_INTERVAL']} сек):"
        )
        return SETTING_VALUE

    elif text.startswith("Объем:"):
        context.user_data['setting'] = ('SPOT', 'MIN_VOLUME_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимального объема (текущее: ${SETTINGS['SPOT']['MIN_VOLUME_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Мин. сумма:"):
        context.user_data['setting'] = ('SPOT', 'MIN_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для минимальной суммы входа (текущее: ${SETTINGS['SPOT']['MIN_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. сумма:"):
        context.user_data['setting'] = ('SPOT', 'MAX_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для максимальной суммы входа (текущее: ${SETTINGS['SPOT']['MAX_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Влияние:"):
        context.user_data['setting'] = ('SPOT', 'MAX_IMPACT_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для максимального влияния (текущее: {SETTINGS['SPOT']['MAX_IMPACT_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Стакан:"):
        context.user_data['setting'] = ('SPOT', 'ORDER_BOOK_DEPTH')
        await update.message.reply_text(
            f"Введите новое значение для глубины стакана (текущее: {SETTINGS['SPOT']['ORDER_BOOK_DEPTH']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Прибыль:"):
        context.user_data['setting'] = ('SPOT', 'MIN_NET_PROFIT_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимальной прибыли (текущее: ${SETTINGS['SPOT']['MIN_NET_PROFIT_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Сходимость:"):
        context.user_data['setting'] = ('SPOT', 'PRICE_CONVERGENCE_THRESHOLD')
        await update.message.reply_text(
            f"Введите новое значение для порога сходимости цен (текущее: {SETTINGS['SPOT']['PRICE_CONVERGENCE_THRESHOLD']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Увед. сравн.:"):
        SETTINGS['SPOT']['PRICE_CONVERGENCE_ENABLED'] = not SETTINGS['SPOT']['PRICE_CONVERGENCE_ENABLED']
        save_settings(SETTINGS)
        status = "🔔 ВКЛ" if SETTINGS['SPOT']['PRICE_CONVERGENCE_ENABLED'] else "🔕 ВЫКЛ"
        await update.message.reply_text(
            f"✅ Уведомления о сравнении цен {status}",
            reply_markup=get_spot_settings_keyboard()
        )
        return SPOT_SETTINGS

    elif text.startswith("Статус:"):
        SETTINGS['SPOT']['ENABLED'] = not SETTINGS['SPOT']['ENABLED']
        save_settings(SETTINGS)
        status = "ВКЛ" if SETTINGS['SPOT']['ENABLED'] else "ВЫКЛ"
        await update.message.reply_text(
            f"✅ DEX арбитраж {status}",
            reply_markup=get_spot_settings_keyboard()
        )
        return SPOT_SETTINGS

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_spot_settings_keyboard()
    )
    return SPOT_SETTINGS

async def handle_dex_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек DEX агрегаторов"""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки DEX бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    # Обработка включения/выключения DEX агрегаторов
    for dex in SETTINGS['DEX'].keys():
        if text.startswith(f"{dex}:"):
            SETTINGS['DEX'][dex]['ENABLED'] = not SETTINGS['DEX'][dex]['ENABLED']
            save_settings(SETTINGS)

            status = "✅ ВКЛ" if SETTINGS['DEX'][dex]['ENABLED'] else "❌ ВЫКЛ"
            await update.message.reply_text(
                f"✅ DEX агрегатор {dex.upper()} {status}",
                reply_markup=get_dex_settings_keyboard()
            )
            return EXCHANGE_SETTINGS_MENU

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_dex_settings_keyboard()
    )
    return EXCHANGE_SETTINGS_MENU

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
        if setting_key in ['THRESHOLD_PERCENT', 'MAX_THRESHOLD_PERCENT', 'MAX_IMPACT_PERCENT',
                           'PRICE_CONVERGENCE_THRESHOLD']:
            value = float(text)
        elif setting_key in ['CHECK_INTERVAL', 'ORDER_BOOK_DEPTH']:
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
            reply_markup=get_spot_settings_keyboard()
        )

        return SPOT_SETTINGS

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите число.",
            reply_markup=get_spot_settings_keyboard()
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
            SPOT_SETTINGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spot_settings)
            ],
            EXCHANGE_SETTINGS_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dex_settings)
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

    # Запускаем DEX арбитражную задачу в фоне
    loop = asyncio.get_event_loop()
    loop.create_task(check_dex_arbitrage())

    logger.info("DEX арбитражный бот запущен")

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
