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
TELEGRAM_TOKEN = "8357883688:AAG5E-IwqpbTn7hJ_320wpvKQpNfkm_QQeo"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894", "1111230981"]

# Конфигурация спотового арбитража (по умолчанию)
DEFAULT_SPOT_SETTINGS = {
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 40,
    "CHECK_INTERVAL": 30,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_VOLUME_USD": 1000000,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 350,
    "MAX_IMPACT_PERCENT": 0.5,
    "ORDER_BOOK_DEPTH": 10,
    "MIN_NET_PROFIT_USD": 4,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True
}

# Настройки DEX бирж
DEX_EXCHANGES = {
    "1inch": {"ENABLED": True},
    "Matcha": {"ENABLED": True},
    "ParaSwap": {"ENABLED": True},
    "Uniswap": {"ENABLED": True},
    "Curve Finance": {"ENABLED": True},
    "Balancer": {"ENABLED": True},
    "SushiSwap": {"ENABLED": True},
    "QuickSwap": {"ENABLED": True},
    "Camelot DEX": {"ENABLED": True},
    "Trader Joe": {"ENABLED": True},
    "Raydium": {"ENABLED": True},
    "Orca": {"ENABLED": True},
    "Jupiter": {"ENABLED": True},
    "STON.fi": {"ENABLED": True},
    "DeDust.io": {"ENABLED": True},
    "Pangolin": {"ENABLED": True},
    "Osmosis": {"ENABLED": True},
    "Maverick Protocol": {"ENABLED": True},
    "THORSwap": {"ENABLED": True}
}

# Состояния для ConversationHandler
SETTINGS_MENU, SPOT_SETTINGS, SETTING_VALUE, COIN_SELECTION = range(4)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("DEXArbBot")

# Глобальные переменные для отслеживания истории уведомлений и длительности арбитража
price_convergence_history = defaultdict(dict)
last_convergence_notification = defaultdict(dict)
arbitrage_start_times = defaultdict(dict)
current_arbitrage_opportunities = defaultdict(dict)
previous_arbitrage_opportunities = defaultdict(dict)
sent_arbitrage_opportunities = defaultdict(dict)

# Глобальные переменные для хранения последних настроек бирж
LAST_DEX_SETTINGS = None

# DEX Screener API конфигурация
DEX_SCREENER_API = "https://api.dexscreener.com/latest/dex"
DEX_SCREENER_SEARCH_API = "https://api.dexscreener.com/latest/dex/search"

# Популярные токены для мониторинга с их адресами
POPULAR_TOKENS = {
    'ETH': '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',
    'BTC': '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',  # WBTC
    'USDC': '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
    'DAI': '0x6b175474e89094c44da98b954eedeac495271d0f',
    'LINK': '0x514910771af9ca656af840dff83e8264ecf986ca',
    'UNI': '0x1f9840a85d5af5bf1d1762f925bdaddc4201f984',
    'AAVE': '0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9',
    'MATIC': '0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0',
    'AVAX': '0x85f138bfee4ef8e540890cfb48f620571d67eda3',
    'SOL': '0xd31a59c85ae9d8edefec411d448f90841571b89c',
    'DOT': '0x43dfc4159d86f3a37a5a4b3d4580b888ad7d4ddd',
    'ADA': '0x3ee2200efb3400fabb9aacf31297cbdd1d435d47',
    'XRP': '0x39fbbabf11738317a448031930706cd3e612e1b9',
    'DOGE': '0x4206931337dc273a630d328da6441786bfad668f',
    'SHIB': '0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce',
    'PEPE': '0x6982508145454ce325ddbe47a25d4ec3d2311933',
    'ARB': '0x912ce59144191c1204e64559fe8253a0e49e6548',
    'OP': '0x4200000000000000000000000000000000000042',
    'SUI': '0x2e9d63788249371f1dfc918a52f8d799f4a38c94',
    'APT': '0x1::aptos_coin::AptosCoin'
}

# Конфигурация DEX бирж для DEX Screener
DEX_CONFIGS = {
    "1inch": {
        "api_url": "https://api.1inch.io/v4.0/1/quote",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.1inch.io/#/1/swap/{s.replace('/', '-')}",
        "emoji": "🦄",
        "dex_screener_id": "1inch"
    },
    "Matcha": {
        "api_url": "https://api.matcha.xyz/markets",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://matcha.xyz/markets/1/{s.replace('/', '-')}",
        "emoji": "🍵",
        "dex_screener_id": "matcha"
    },
    "ParaSwap": {
        "api_url": "https://apiv5.paraswap.io/prices",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.paraswap.io/#/{s.replace('/', '-')}",
        "emoji": "🔄",
        "dex_screener_id": "paraswap"
    },
    "Uniswap": {
        "api_url": "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.uniswap.org/#/swap?inputCurrency={s.split('/')[0]}&outputCurrency=USDT",
        "emoji": "🦄",
        "dex_screener_id": "uniswap"
    },
    "Curve Finance": {
        "api_url": "https://api.curve.fi/api/getPools/ethereum",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.004,
        "maker_fee": 0.004,
        "url_format": lambda s: f"https://curve.fi/#/ethereum/swap",
        "emoji": "📈",
        "dex_screener_id": "curve"
    },
    "Balancer": {
        "api_url": "https://api.thegraph.com/subgraphs/name/balancer-labs/balancer-v2",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.balancer.fi/#/trade",
        "emoji": "⚖️",
        "dex_screener_id": "balancer"
    },
    "SushiSwap": {
        "api_url": "https://api.thegraph.com/subgraphs/name/sushiswap/exchange",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.sushi.com/swap?inputCurrency={s.split('/')[0]}&outputCurrency=USDT",
        "emoji": "🍣",
        "dex_screener_id": "sushiswap"
    },
    "QuickSwap": {
        "api_url": "https://api.thegraph.com/subgraphs/name/sameepsi/quickswap",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda
            s: f"https://quickswap.exchange/#/swap?inputCurrency={s.split('/')[0]}&outputCurrency=USDT",
        "emoji": "⚡",
        "dex_screener_id": "quickswap"
    },
    "Camelot DEX": {
        "api_url": "https://api.camelot.exchange/swap",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.camelot.exchange/",
        "emoji": "🐫",
        "dex_screener_id": "camelot"
    },
    "Trader Joe": {
        "api_url": "https://api.traderjoexyz.com/priceusd",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://traderjoexyz.com/trade",
        "emoji": "👨‍💼",
        "dex_screener_id": "traderjoe"
    },
    "Raydium": {
        "api_url": "https://api.raydium.io/v2/main/price",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.0025,
        "maker_fee": 0.0025,
        "url_format": lambda s: f"https://raydium.io/swap/",
        "emoji": "☀️",
        "dex_screener_id": "raydium"
    },
    "Orca": {
        "api_url": "https://api.orca.so/prices",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://www.orca.so/swap",
        "emoji": "🐋",
        "dex_screener_id": "orca"
    },
    "Jupiter": {
        "api_url": "https://quote-api.jup.ag/v6/quote",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://jup.ag/swap/{s.replace('/', '-')}",
        "emoji": "🪐",
        "dex_screener_id": "jupiter"
    },
    "STON.fi": {
        "api_url": "https://api.ston.fi/v1/price",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.ston.fi/swap",
        "emoji": "💎",
        "dex_screener_id": "stonfi"
    },
    "DeDust.io": {
        "api_url": "https://api.dedust.io/v1/prices",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://dedust.io/swap",
        "emoji": "💨",
        "dex_screener_id": "dedust"
    },
    "Pangolin": {
        "api_url": "https://api.pangolin.exchange/api/v1/price",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.pangolin.exchange/swap",
        "emoji": "🦎",
        "dex_screener_id": "pangolin"
    },
    "Osmosis": {
        "api_url": "https://api-osmosis.imperator.co/tokens/v2/price",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.osmosis.zone/swap",
        "emoji": "🔬",
        "dex_screener_id": "osmosis"
    },
    "Maverick Protocol": {
        "api_url": "https://api.mav.xyz/api/prices",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.mav.xyz/swap",
        "emoji": "🐎",
        "dex_screener_id": "mav"
    },
    "THORSwap": {
        "api_url": "https://api.thorswap.com/price",
        "symbol_format": lambda s: f"{s}/USDT",
        "taker_fee": 0.003,
        "maker_fee": 0.003,
        "url_format": lambda s: f"https://app.thorswap.finance/swap",
        "emoji": "⚡",
        "dex_screener_id": "thorswap"
    }
}


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
        "DEX": DEX_EXCHANGES.copy()
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
DEX_EXCHANGES_LOADED = {}
SETTINGS = load_settings()


# Reply-клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📈 Актуальные связки")], [KeyboardButton("🔧 Настройки")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)


def get_settings_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀️ Спот Арбитраж"), KeyboardButton("🏛 DEX Биржи")],
        [KeyboardButton("🔄 Сброс"), KeyboardButton("🔙 Главное меню")]
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
        [KeyboardButton(f"Прибыль: ${spot['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if spot['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"Сходимость: {spot['PRICE_CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if spot['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)


def get_dex_settings_keyboard():
    keyboard = []
    row = []
    for i, (exchange, config) in enumerate(SETTINGS['DEX'].items()):
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

    current_arbitrage_opportunities[key] = sent_arbitrage_opportunities[key].copy()
    arbitrage_start_times[key] = current_time
    previous_arbitrage_opportunities[key] = True

    logger.info(f"Связка добавлена в отправленные: {key}")


async def send_price_convergence_notification(arb_type: str, base: str, exchange1: str, exchange2: str,
                                              price1: float, price2: float, spread: float, volume1: float = None,
                                              volume2: float = None, duration: float = None):
    """Отправляет уведомление о сравнении цен с длительностью арбитража"""

    if not SETTINGS[arb_type]['PRICE_CONVERGENCE_ENABLED']:
        return

    convergence_threshold = SETTINGS[arb_type]['PRICE_CONVERGENCE_THRESHOLD']

    if abs(spread) > convergence_threshold:
        return

    previous_key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    if previous_key not in sent_arbitrage_opportunities:
        return

    current_time = time.time()
    notification_key = f"{arb_type}_{base}_{exchange1}_{exchange2}"

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

    volume1_str = format_volume(volume1)
    volume2_str = format_volume(volume2)
    duration_str = format_duration(duration) if duration is not None else "N/A"

    exchange1_config = DEX_CONFIGS[exchange1]
    exchange2_config = DEX_CONFIGS[exchange2]
    symbol1 = exchange1_config["symbol_format"](base)
    symbol2 = exchange2_config["symbol_format"](base)
    url1 = exchange1_config["url_format"](symbol1)
    url2 = exchange2_config["url_format"](symbol2)

    safe_base = html.escape(base)

    message = (
        f"🎯 <b>ЦЕНЫ СРАВНИЛИСЬ!</b> 🚀\n\n"
        f"▫️ <b>Тип:</b> DEX арбитраж\n"
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
    logger.info(f"Отправлено уведомление о сходимости цен для {base}: {spread:.4f}%, длительность: {duration_str}")

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

    if (key in sent_arbitrage_opportunities and
            SETTINGS[arb_type]['THRESHOLD_PERCENT'] <= spread <= SETTINGS[arb_type]['MAX_THRESHOLD_PERCENT'] and
            key not in arbitrage_start_times):
        arbitrage_start_times[key] = current_time
        previous_arbitrage_opportunities[key] = True
        logger.debug(f"Начало арбитража для {key}")

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
    """Обновляет информацию о текущих арбитражных возможностях"""
    key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    current_time = time.time()

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
    """Возвращает форматированное сообщение с текущими арбитражными возможностями"""

    cleanup_old_opportunities()

    filtered_opportunities = {}
    current_time = time.time()

    for key, opportunity in sent_arbitrage_opportunities.items():
        if (current_time - opportunity['last_updated']) <= 3600:
            filtered_opportunities[key] = opportunity

    if not filtered_opportunities:
        return "📊 <b>Актуальные DEX арбитражные связки</b>\n\n" \
               "⏳ В данный момент активных арбитражных возможностей не обнаружено."

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

    spot_opportunities.sort(key=lambda x: x['spread'], reverse=True)

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    message = "📊 <b>Актуальные DEX арбитражные связки</b>\n\n"

    if spot_opportunities:
        message += "🚀 <b>DEX арбитраж:</b>\n"
        for opp in spot_opportunities:
            duration_str = format_duration(opp['duration'])

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


async def fetch_dex_screener_data(token_address: str):
    """Получает данные о токене с DEX Screener API"""
    try:
        url = f"{DEX_SCREENER_API}/tokens/{token_address}"
        logger.info(f"Запрос к DEX Screener: {url}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Успешно получены данные для токена {token_address}")
                    return data
                else:
                    logger.warning(f"DEX Screener API error: {response.status} - {await response.text()}")
                    return None
    except asyncio.TimeoutError:
        logger.error(f"Таймаут при запросе к DEX Screener для токена {token_address}")
        return None
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка клиента при запросе к DEX Screener: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при получении данных с DEX Screener: {e}")
        return None


async def search_dex_screener(query: str):
    """Поиск токенов на DEX Screener"""
    try:
        url = f"{DEX_SCREENER_SEARCH_API}?q={query}"
        logger.info(f"Поиск на DEX Screener: {url}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Успешный поиск для запроса: {query}")
                    return data
                else:
                    logger.warning(f"DEX Screener Search API error: {response.status} - {await response.text()}")
                    return None
    except asyncio.TimeoutError:
        logger.error(f"Таймаут при поиске на DEX Screener для запроса: {query}")
        return None
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка клиента при поиске на DEX Screener: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при поиске на DEX Screener: {e}")
        return None


async def get_token_data_from_dex_screener(token_symbol: str):
    """Получает данные токена с DEX Screener"""
    # Сначала пытаемся найти по известному адресу
    if token_symbol.upper() in POPULAR_TOKENS:
        token_address = POPULAR_TOKENS[token_symbol.upper()]
        logger.info(f"Поиск токена {token_symbol} по адресу: {token_address}")
        data = await fetch_dex_screener_data(token_address)
        if data and 'pairs' in data and data['pairs']:
            logger.info(f"Найдены данные для {token_symbol} по адресу")
            return data
        else:
            logger.warning(f"Не найдены данные для {token_symbol} по адресу {token_address}")

    # Если не нашли по адресу, ищем по символу
    logger.info(f"Поиск токена {token_symbol} по символу")
    search_data = await search_dex_screener(token_symbol)
    if search_data and 'pairs' in search_data and search_data['pairs']:
        logger.info(f"Найдены данные для {token_symbol} по символу")
        return search_data

    logger.warning(f"Не удалось найти данные для токена {token_symbol}")
    return None


async def fetch_dex_price(dex_name: str, symbol: str):
    """Получает цену с DEX биржи через DEX Screener"""
    try:
        # Извлекаем символ токена (убираем /USDT)
        token_symbol = symbol.replace('/USDT', '')

        logger.info(f"Получение цены для {token_symbol} на {dex_name}")

        # Получаем данные токена
        token_data = await get_token_data_from_dex_screener(token_symbol)

        if not token_data or 'pairs' not in token_data or not token_data['pairs']:
            logger.warning(f"Нет данных для {symbol} на DEX Screener")
            return None

        pairs = token_data['pairs']

        # Фильтруем пары по DEX и USDT паре
        dex_config = DEX_CONFIGS[dex_name]
        dex_screener_id = dex_config.get("dex_screener_id", "").lower()

        relevant_pairs = []
        for pair in pairs:
            try:
                # Проверяем, что это USDT пара и подходящий DEX
                quote_token_symbol = pair.get('quoteToken', {}).get('symbol', '')
                dex_id = pair.get('dexId', '').lower()

                if (quote_token_symbol == 'USDT' and
                        dex_screener_id in dex_id):
                    relevant_pairs.append(pair)
            except Exception as e:
                logger.warning(f"Ошибка обработки пары: {e}")
                continue

        if not relevant_pairs:
            logger.debug(f"Нет подходящих пар для {symbol} на {dex_name}")
            return None

        # Выбираем пару с наибольшим объемом
        best_pair = max(relevant_pairs, key=lambda x: float(x.get('volume', {}).get('h24', 0)))

        price_str = best_pair.get('priceUsd')
        if not price_str:
            logger.warning(f"Нет цены для пары {symbol} на {dex_name}")
            return None

        price = float(price_str)
        volume_24h = float(best_pair.get('volume', {}).get('h24', 0))
        liquidity = float(best_pair.get('liquidity', {}).get('usd', 0))

        if price <= 0:
            logger.warning(f"Некорректная цена для {symbol} на {dex_name}: {price}")
            return None

        logger.info(f"Успешно получена цена {price} для {symbol} на {dex_name}")

        return {
            'price': price,
            'volume': volume_24h,
            'liquidity': liquidity,
            'symbol': symbol,
            'pair_address': best_pair.get('pairAddress'),
            'dex_id': best_pair.get('dexId')
        }

    except Exception as e:
        logger.error(f"Ошибка получения цены {symbol} на {dex_name}: {e}")
        return None


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


async def load_dex_exchanges():
    """Загружает DEX биржи на основе текущих настроек"""
    global DEX_EXCHANGES_LOADED, LAST_DEX_SETTINGS

    exchanges = {}
    for name in DEX_CONFIGS.keys():
        if not SETTINGS['DEX'][name]['ENABLED']:
            continue

        try:
            exchanges[name] = {"config": DEX_CONFIGS[name]}
            logger.info(f"{name.upper()} успешно загружена")
        except Exception as e:
            logger.error(f"Ошибка инициализации {name}: {e}")

    DEX_EXCHANGES_LOADED = exchanges
    LAST_DEX_SETTINGS = SETTINGS['DEX'].copy()
    return exchanges


async def check_spot_arbitrage():
    logger.info("Запуск проверки DEX арбитража с использованием DEX Screener")

    if not SETTINGS['SPOT']['ENABLED']:
        logger.info("DEX арбитраж отключен в настройках")
        return

    # Инициализация бирж
    await load_dex_exchanges()

    if len(DEX_EXCHANGES_LOADED) < SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']:
        logger.error(f"Недостаточно DEX бирж (нужно минимум {SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']})")
        return

    # Список популярных токенов для анализа
    popular_tokens = list(POPULAR_TOKENS.keys())

    logger.info(f"Начинаем анализ {len(popular_tokens)} популярных токенов через DEX Screener")

    while SETTINGS['SPOT']['ENABLED']:
        try:
            # Проверяем, изменились ли настройки бирж
            if LAST_DEX_SETTINGS != SETTINGS['DEX']:
                logger.info("Обнаружено изменение настроек DEX бирж. Перезагружаем...")
                await load_dex_exchanges()

                if len(DEX_EXCHANGES_LOADED) < SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']:
                    logger.error("Недостаточно DEX бирж после перезагрузки")
                    await asyncio.sleep(SETTINGS['SPOT']['CHECK_INTERVAL'])
                    continue

            found_opportunities = 0
            for base in popular_tokens:
                try:
                    ticker_data = {}

                    # Получаем данные тикеров для всех DEX бирж через DEX Screener
                    for name, data in DEX_EXCHANGES_LOADED.items():
                        try:
                            symbol = data["config"]["symbol_format"](base)
                            data_result = await fetch_dex_price(name, symbol)
                            if data_result and data_result['price'] is not None:
                                if data_result['volume'] is None or data_result['volume'] >= SETTINGS['SPOT'][
                                    'MIN_VOLUME_USD']:
                                    ticker_data[name] = data_result
                                else:
                                    logger.debug(f"Объем {symbol} на {name} слишком мал: {data_result['volume']}")
                            else:
                                logger.debug(f"Нет данных для {symbol} на {name}")
                        except Exception as e:
                            logger.warning(f"Ошибка получения данных {base} на {name}: {e}")

                    if len(ticker_data) < SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']:
                        continue

                    # Сортируем биржи по цене
                    sorted_data = sorted(ticker_data.items(), key=lambda x: x[1]['price'])
                    min_ex = sorted_data[0]  # Самая низкая цена (покупка)
                    max_ex = sorted_data[-1]  # Самая высокая цена (продажа)

                    # Рассчитываем спред
                    spread = (max_ex[1]['price'] - min_ex[1]['price']) / min_ex[1]['price'] * 100

                    logger.info(
                        f"Токен {base}: спред {spread:.2f}% (min: {min_ex[0]} {min_ex[1]['price']}, max: {max_ex[0]} {max_ex[1]['price']})")

                    # Обновляем информацию о текущих арбитражных возможностях
                    update_current_arbitrage_opportunities(
                        'SPOT', base, min_ex[0], max_ex[0], spread,
                        min_ex[1]['price'], max_ex[1]['price'],
                        min_ex[1]['volume'], max_ex[1]['volume']
                    )

                    # Проверяем сходимость цен для уведомления
                    duration = update_arbitrage_duration('SPOT', base, min_ex[0], max_ex[0], spread)
                    if duration is not None:
                        await send_price_convergence_notification(
                            'SPOT', base, min_ex[0], max_ex[0],
                            min_ex[1]['price'], max_ex[1]['price'], spread,
                            min_ex[1]['volume'], max_ex[1]['volume'], duration
                        )

                    if SETTINGS['SPOT']['THRESHOLD_PERCENT'] <= spread <= SETTINGS['SPOT']['MAX_THRESHOLD_PERCENT']:
                        # Получаем комиссии
                        buy_fee = DEX_EXCHANGES_LOADED[min_ex[0]]["config"]["taker_fee"]
                        sell_fee = DEX_EXCHANGES_LOADED[max_ex[0]]["config"]["taker_fee"]

                        # Рассчитываем минимальную сумму для MIN_NET_PROFIT_USD
                        min_amount_for_profit = calculate_min_entry_amount(
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
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
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
                            amount=min_entry_amount / min_ex[1]['price'],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        profit_max = calculate_profit(
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
                            amount=max_entry_amount / min_ex[1]['price'],
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

                        min_volume = format_volume(min_ex[1]['volume'])
                        max_volume = format_volume(max_ex[1]['volume'])

                        safe_base = html.escape(base)
                        buy_exchange_config = DEX_CONFIGS[min_ex[0]]
                        sell_exchange_config = DEX_CONFIGS[max_ex[0]]

                        # Получаем прямые ссылки на пары из DEX Screener
                        buy_url = f"https://dexscreener.com/{min_ex[1].get('dex_id', 'ethereum')}/{min_ex[1].get('pair_address', '')}"
                        sell_url = f"https://dexscreener.com/{max_ex[1].get('dex_id', 'ethereum')}/{max_ex[1].get('pair_address', '')}"

                        message = (
                            f"🚀 <b>DEX Арбитраж (Real-time):</b> <code>{safe_base}</code>\n"
                            f"▫️ <b>Разница цен:</b> {spread:.2f}%\n"
                            f"▫️ <b>Сумма входа:</b> ${min_entry_amount:.2f}-${max_entry_amount:.2f}\n\n"
                            f"🟢 <b>Покупка на <a href='{buy_url}'>{min_ex[0].upper()}</a>:</b> ${min_ex[1]['price']:.8f}\n"
                            f"   <b>Объём 24h:</b> {min_volume}\n"
                            f"   <b>Комиссия:</b> {buy_fee * 100:.2f}%\n\n"
                            f"🔴 <b>Продажа на <a href='{sell_url}'>{max_ex[0].upper()}</a>:</b> ${max_ex[1]['price']:.8f}\n"
                            f"   <b>Объём 24h:</b> {max_volume}\n"
                            f"   <b>Комиссия:</b> {sell_fee * 100:.2f}%\n\n"
                            f"💰 <b>Чистая прибыль:</b> ${profit_min['net']:.2f}-${profit_max['net']:.2f} ({profit_max['percent']:.2f}%)\n\n"
                            f"⏱ {current_time}\n"
                            f"📡 <i>Данные через DEX Screener</i>"
                        )

                        logger.info(f"Найдена DEX арбитражная возможность: {base} ({spread:.2f}%)")

                        # Отправляем сообщение в Telegram
                        await send_telegram_message(message)

                        # Добавляем связку в отправленные возможности
                        add_opportunity_to_sent(
                            'SPOT', base, min_ex[0], max_ex[0], spread,
                            min_ex[1]['price'], max_ex[1]['price'],
                            min_ex[1]['volume'], max_ex[1]['volume'],
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
    """Получает цены монеты на всех DEX биржах через DEX Screener"""
    coin = coin.upper()

    # Получаем данные токена с DEX Screener
    token_data = await get_token_data_from_dex_screener(coin)

    if not token_data or 'pairs' not in token_data or not token_data['pairs']:
        return f"❌ Монета {coin} не найдена на DEX Screener или нет данных о парах"

    pairs = token_data['pairs']

    # Фильтруем только USDT пары с достаточным объемом
    min_volume = SETTINGS['SPOT']['MIN_VOLUME_USD']
    usdt_pairs = [
        pair for pair in pairs
        if pair.get('quoteToken', {}).get('symbol') == 'USDT'
           and float(pair.get('volume', {}).get('h24', 0)) >= min_volume
    ]

    if not usdt_pairs:
        return f"❌ Монета {coin} не имеет USDT пар с объемом > ${min_volume:,.0f}"

    # Сортируем по цене
    usdt_pairs.sort(key=lambda x: float(x.get('priceUsd', 0)))

    results = []
    for pair in usdt_pairs:
        dex_name = pair.get('dexId', 'Unknown').title()
        price_str = pair.get('priceUsd')
        if not price_str:
            continue

        price = float(price_str)
        volume_24h = float(pair.get('volume', {}).get('h24', 0))
        liquidity = float(pair.get('liquidity', {}).get('usd', 0))

        pair_address = pair.get('pairAddress')
        url = f"https://dexscreener.com/{pair.get('chainId', 'ethereum')}/{pair_address}"

        # Находим эмодзи для DEX
        emoji = "🦄"  # по умолчанию
        for config_name, config in DEX_CONFIGS.items():
            if config.get("dex_screener_id", "").lower() in dex_name.lower():
                emoji = config.get("emoji", "🦄")
                dex_name = config_name  # Используем наше стандартное название
                break

        results.append({
            "price": price,
            "name": dex_name.upper(),
            "volume": volume_24h,
            "liquidity": liquidity,
            "url": url,
            "emoji": emoji,
            "pair_address": pair_address
        })

    results.sort(key=lambda x: x["price"])

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    if results:
        min_price = results[0]["price"]
        max_price = results[-1]["price"]
        price_diff_percent = ((max_price - min_price) / min_price) * 100

        response = f"🦄 <b>DEX рынки для <code>{coin}</code> (Real-time):</b>\n\n"
        response += f"<i>Минимальный объем: ${min_volume:,.0f}</i>\n"
        response += f"<i>Найдено DEX: {len(results)}</i>\n\n"

        for idx, item in enumerate(results, 1):
            response += (
                f"{item['emoji']} <a href='{item['url']}'><b>{item['name']}</b></a>\n"
                f"▫️ Цена: {format_price(item['price'])}\n"
                f"▫️ Объем 24h: {format_volume(item['volume'])}\n"
                f"▫️ Ликвидность: {format_volume(item['liquidity'])}\n"
            )

            if idx < len(results):
                response += "\n"

        if len(results) >= 2 and min_price < max_price:
            min_exchange = results[0]
            max_exchange = results[-1]

            # Получаем комиссии для DEX
            buy_fee = 0.003  # по умолчанию
            sell_fee = 0.003  # по умолчанию

            for config_name, config in DEX_CONFIGS.items():
                if config_name.lower() == min_exchange['name'].lower():
                    buy_fee = config["taker_fee"]
                if config_name.lower() == max_exchange['name'].lower():
                    sell_fee = config["taker_fee"]

            min_entry = SETTINGS['SPOT']['MIN_ENTRY_AMOUNT_USDT']
            max_entry = SETTINGS['SPOT']['MAX_ENTRY_AMOUNT_USDT']

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
            response += f"🟢 Покупка на {min_exchange['name']}: {format_price(min_price)}\n"
            response += f"🔴 Продажа на {max_exchange['name']}: {format_price(max_price)}\n"
            response += f"💰 Сумма входа: ${min_entry:.2f}-${max_entry:.2f}\n"
            response += f"💵 Чистая прибыль: ${profit_min['net']:.2f}-${profit_max['net']:.2f}\n"

        response += f"\n📈 <b>Разница цен:</b> {price_diff_percent:.2f}%\n"
        response += f"⏱ {current_time} | DEX: {len(results)}"
        response += f"\n📡 <i>Данные через DEX Screener</i>"
    else:
        response = f"❌ Монета {coin} не найдена на DEX рынках с достаточным объемом"

    return response


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 <b>DEX Arbitrage Bot v2.0</b>\n\n"
        "Бот для поиска арбитражных возможностей на децентрализованных биржах\n"
        "📡 <i>Теперь с реальными данными через DEX Screener API</i>\n\n"
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
            "⚙️ <b>Настройки DEX бота v2.0</b>\n\nВыберите категорию:",
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
            f"🤖 <b>Статус DEX бота v2.0</b>\n\n"
            f"🚀 DEX арбитраж: {spot_status}\n"
            f"🦄 Активные DEX: {dex_status}\n"
            f"📈 Активных связок: {len(sent_arbitrage_opportunities)}\n"
            f"📡 Источник данных: DEX Screener API",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "🤖 <b>DEX Arbitrage Bot v2.0</b>\n\n"
            "🔍 <b>Поиск монеты</b> - показывает реальные цены на разных DEX через DEX Screener, просто введите название монеты (ETH, BTC, USDC...)\n"
            "🔧 <b>Настройки</b> - позволяет настроить параметры арбитража и DEX биржи\n"
            "📊 <b>Статус бота</b> - показывает текущее состояние бота\n"
            "📈 <b>Актуальные связки</b> - показывает текущие арбитражные возможности\n\n"
            "🦄 <b>Поддерживаемые DEX:</b>\n"
            "1inch, Matcha, ParaSwap, Uniswap, Curve, Balancer, SushiSwap, QuickSwap,\n"
            "Camelot, Trader Joe, Raydium, Orca, Jupiter, STON.fi, DeDust, Pangolin,\n"
            "Osmosis, Maverick, THORSwap\n\n"
            "📡 <b>Источник данных:</b> DEX Screener API (реальные данные)",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    # Если это не команда, предполагаем, что это название монеты
    if not text.startswith('/'):
        if re.match(r'^[A-Z0-9]{1,15}$', text.upper()):
            context.user_data['coin'] = text.upper()

            # Показываем "Загрузка..."
            await update.message.reply_text(
                f"⏳ Загружаем реальные данные для <b><code>{text.upper()}</code></b> через DEX Screener...",
                parse_mode="HTML"
            )

            # Получаем данные
            response = await get_coin_prices(text.upper())

            # Отправляем результаты
            await update.message.reply_text(
                text=response,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=get_main_keyboard()
            )
            return
        else:
            await update.message.reply_text(
                "⚠️ Неверный формат названия монеты. Используйте только буквы и цифры (например ETH или BTC)",
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

    if text == "🚀️ Спот Арбитраж":
        await update.message.reply_text(
            "🚀️ <b>Настройки DEX арбитража v2.0</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_spot_settings_keyboard()
        )
        return SPOT_SETTINGS

    elif text == "🏛 DEX Биржи":
        await update.message.reply_text(
            "🏛 <b>Настройки DEX бирж v2.0</b>\n\nВыберите DEX для включения/выключения:",
            parse_mode="HTML",
            reply_markup=get_dex_settings_keyboard()
        )
        return SETTINGS_MENU

    elif text == "🔄 Сброс":
        global SETTINGS, LAST_DEX_SETTINGS
        SETTINGS = {
            "SPOT": DEFAULT_SPOT_SETTINGS.copy(),
            "DEX": DEX_EXCHANGES.copy()
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
            "⚙️ <b>Настройки DEX бота v2.0</b>\n\nВыберите категорию:",
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
    """Обработка настроек DEX бирж"""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки DEX бота v2.0</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    # Обработка включения/выключения DEX бирж
    for dex in SETTINGS['DEX'].keys():
        if text.startswith(f"{dex}:"):
            SETTINGS['DEX'][dex]['ENABLED'] = not SETTINGS['DEX'][dex]['ENABLED']
            save_settings(SETTINGS)

            status = "✅ ВКЛ" if SETTINGS['DEX'][dex]['ENABLED'] else "❌ ВЫКЛ"
            await update.message.reply_text(
                f"✅ DEX {dex.upper()} {status}",
                reply_markup=get_dex_settings_keyboard()
            )
            return SETTINGS_MENU

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_dex_settings_keyboard()
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
        if setting_key in ['THRESHOLD_PERCENT', 'MAX_THRESHOLD_PERCENT', 'PRICE_CONVERGENCE_THRESHOLD']:
            value = float(text)
        elif setting_key in ['CHECK_INTERVAL']:
            value = int(text)
        elif setting_key in ['MIN_VOLUME_USD', 'MIN_ENTRY_AMOUNT_USDT', 'MAX_ENTRY_AMOUNT_USDT', 'MIN_NET_PROFIT_USD']:
            value = float(text)
        else:
            value = text

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
    loop.create_task(check_spot_arbitrage())

    logger.info("DEX арбитраж бот v2.0 запущен с DEX Screener API")

    # Запускаем бота
    application.run_polling()


if __name__ == '__main__':
    main()
