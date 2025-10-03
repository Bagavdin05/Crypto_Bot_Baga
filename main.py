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

# Общая конфигурация
TELEGRAM_TOKEN = "8357883688:AAG5E-IwqpbTn7hJ_320wpvKQpNfkm_QQeo"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894", "1111230981", "912731125"]

# Конфигурация спотового арбитража (по умолчанию)
DEFAULT_SPOT_SETTINGS = {
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 40,
    "CHECK_INTERVAL": 30,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_VOLUME_USD": 10000000,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 350,
    "MAX_IMPACT_PERCENT": 0.5,
    "ORDER_BOOK_DEPTH": 10,
    "MIN_NET_PROFIT_USD": 6,
    "ENABLED": True
}

# Конфигурация фьючерсного арбитража (по умолчанию)
DEFAULT_FUTURES_SETTINGS = {
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 20,
    "CHECK_INTERVAL": 30,
    "MIN_VOLUME_USD": 10000000,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 170,
    "MIN_NET_PROFIT_USD": 5,
    "ENABLED": True
}

# Конфигурация спот-фьючерсного арбитража (по умолчанию)
DEFAULT_SPOT_FUTURES_SETTINGS = {
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 20,
    "CHECK_INTERVAL": 30,
    "MIN_VOLUME_USD": 10000000,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 170,
    "MIN_NET_PROFIT_USD": 5,
    "ENABLED": True
}

# Настройки бирж
EXCHANGE_SETTINGS = {
    "bybit": {"ENABLED": True},
    "mexc": {"ENABLED": True},
    "okx": {"ENABLED": True},
    "gate": {"ENABLED": True},
    "bitget": {"ENABLED": True},
    "kucoin": {"ENABLED": True},
    "htx": {"ENABLED": True},
    "bingx": {"ENABLED": True},
    "phemex": {"ENABLED": True},
    "coinex": {"ENABLED": True},
    "xt": {"ENABLED": True},
    "ascendex": {"ENABLED": True},
    "bitrue": {"ENABLED": True},
    "blofin": {"ENABLED": True}
}

# Состояния для ConversationHandler
SETTINGS_MENU, SPOT_SETTINGS, FUTURES_SETTINGS, SPOT_FUTURES_SETTINGS, EXCHANGE_SETTINGS_MENU, SETTING_VALUE, COIN_SELECTION = range(
    7)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("CryptoArbBot")


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
        "FUTURES": DEFAULT_FUTURES_SETTINGS.copy(),
        "SPOT_FUTURES": DEFAULT_SPOT_FUTURES_SETTINGS.copy(),
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
SPOT_EXCHANGES_LOADED = {}
FUTURES_EXCHANGES_LOADED = {}
SETTINGS = load_settings()

# Конфигурация бирж для спота
SPOT_EXCHANGES = {
    "bybit": {
        "api": ccxt.bybit({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.bybit.com/trade/spot/{s.replace('/', '')}",
        "withdraw_url": lambda c: f"https://www.bybit.com/user/assets/withdraw",
        "deposit_url": lambda c: f"https://www.bybit.com/user/assets/deposit",
        "emoji": "🏛"
    },
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.mexc.com/exchange/{s.replace('/', '_')}",
        "withdraw_url": lambda c: f"https://www.mexc.com/ru-RU/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.mexc.com/ru-RU/assets/deposit/{c}",
        "emoji": "🏛"
    },
    "okx": {
        "api": ccxt.okx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.0008,
        "url_format": lambda s: f"https://www.okx.com/trade-spot/{s.replace('/', '-').lower()}",
        "withdraw_url": lambda c: f"https://www.okx.com/ru/balance/withdrawal/{c.lower()}-chain",
        "deposit_url": lambda c: f"https://www.okx.com/ru/balance/recharge/{c.lower()}",
        "emoji": "🏛"
    },
    "gate": {
        "api": ccxt.gateio({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.gate.io/trade/{s.replace('/', '_')}",
        "withdraw_url": lambda c: f"https://www.gate.io/myaccount/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.gate.io/myaccount/deposit/{c}",
        "emoji": "🏛"
    },
    "bitget": {
        "api": ccxt.bitget({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.bitget.com/spot/{s.replace('/', '')}_SPBL",
        "withdraw_url": lambda c: f"https://www.bitget.com/ru/asset/withdraw?coinId={c}",
        "deposit_url": lambda c: f"https://www.bitget.com/ru/asset/recharge?coinId={c}",
        "emoji": "🏛"
    },
    "kucoin": {
        "api": ccxt.kucoin({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.kucoin.com/trade/{s.replace('/', '-')}",
        "withdraw_url": lambda c: f"https://www.kucoin.com/ru/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.kucoin.com/ru/assets/coin/{c}",
        "emoji": "🏛"
    },
    "htx": {
        "api": ccxt.htx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.htx.com/trade/{s.replace('/', '_').lower()}",
        "withdraw_url": lambda c: f"https://www.htx.com/ru-ru/finance/withdraw/{c.lower()}",
        "deposit_url": lambda c: f"https://www.htx.com/ru-ru/finance/deposit/{c.lower()}",
        "emoji": "🏛"
    },
    "bingx": {
        "api": ccxt.bingx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://bingx.com/en-us/spot/{s.replace('/', '')}",
        "withdraw_url": lambda c: f"https://bingx.com/en-us/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://bingx.com/en-us/assets/deposit/{c}",
        "emoji": "🏛"
    },
    "phemex": {
        "api": ccxt.phemex({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://phemex.com/spot/trade/{s.replace('/', '')}",
        "withdraw_url": lambda c: f"https://phemex.com/assets/withdraw?asset={c}",
        "deposit_url": lambda c: f"https://phemex.com/assets/deposit?asset={c}",
        "emoji": "🏛"
    },
    "coinex": {
        "api": ccxt.coinex({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.coinex.com/exchange/{s.replace('/', '-')}",
        "withdraw_url": lambda c: f"https://www.coinex.com/asset/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.coinex.com/asset/deposit/{c}",
        "emoji": "🏛"
    },
    "xt": {
        "api": ccxt.xt({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.xt.com/trade/{s.replace('/', '_')}",
        "withdraw_url": lambda c: f"https://www.xt.com/asset/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.xt.com/asset/deposit/{c}",
        "emoji": "🏛"
    },
    "ascendex": {
        "api": ccxt.ascendex({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://ascendex.com/en/cashtrade-spot/{s.replace('/', '-')}",
        "withdraw_url": lambda c: f"https://ascendex.com/en/asset/withdraw/{c}",
        "deposit_url": lambda c: f"https://ascendex.com/en/asset/deposit/{c}",
        "emoji": "🏛"
    },
    "bitrue": {
        "api": ccxt.bitrue({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.bitrue.com/trade/{s.replace('/', '_')}",
        "withdraw_url": lambda c: f"https://www.bitrue.com/asset/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.bitrue.com/asset/deposit/{c}",
        "emoji": "🏛"
    },
    "blofin": {
        "api": ccxt.blofin({
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot"
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('type') == 'spot' and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.blofin.com/spot/{s.replace('/', '-')}",
        "withdraw_url": lambda c: f"https://www.blofin.com/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.blofin.com/assets/deposit/{c}",
        "emoji": "🏛"
    }
}

# Конфигурация бирж для фьючерсов
FUTURES_EXCHANGES = {
    "bybit": {
        "api": ccxt.bybit({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0006,
        "maker_fee": 0.0001,
        "url_format": lambda s: f"https://www.bybit.com/trade/usdt/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": ["BTC", "ETH"],
        "emoji": "📊"
    },
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://futures.mexc.com/exchange/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "okx": {
        "api": ccxt.okx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.okx.com/trade-swap/{s.replace('/', '-').replace(':USDT', '').lower()}",
        "blacklist": [],
        "emoji": "📊"
    },
    "gate": {
        "api": ccxt.gateio({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and '_USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.gate.io/futures_trade/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "bitget": {
        "api": ccxt.bitget({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.bitget.com/ru/futures/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "kucoin": {
        "api": ccxt.kucoin({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.kucoin.com/futures/trade/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "htx": {
        "api": ccxt.htx({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
                "fetchMarkets": ["swap"]
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and m.get('linear', False),
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.htx.com/futures/exchange/{s.split(':')[0].replace('/', '_').lower()}",
        "blacklist": [],
        "emoji": "📊"
    },
    "bingx": {
        "api": ccxt.bingx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://bingx.com/en-us/futures/{s.replace('/', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "phemex": {
        "api": ccxt.phemex({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and m['settle'] == 'USDT',
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://phemex.com/futures/trade/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "coinex": {
        "api": ccxt.coinex({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.coinex.com/perpetual/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "xt": {
        "api": ccxt.xt({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.xt.com/futures/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "ascendex": {
        "api": ccxt.ascendex({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",  # Явно указываем тип по умолчанию
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (
                m.get('type') in ['swap', 'future'] and
                m.get('settle') == 'USDT' and
                m.get('linear', False)  # Убедимся что это линейный контракт
        ),
        "taker_fee": 0.0006,  # Обновленная комиссия
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://ascendex.com/en/futures/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "bitrue": {
        "api": ccxt.bitrue({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.bitrue.com/futures/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "blofin": {
        "api": ccxt.blofin({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap"
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.blofin.com/futures/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    }
}


# Reply-клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔧 Настройки")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)


def get_settings_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀️ Спот"), KeyboardButton("📊 Фьючерсы"), KeyboardButton("↔️ Спот-Фьючерсы")],
        [KeyboardButton("🏛 Биржи"), KeyboardButton("🔄 Сброс")],
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
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)


def get_futures_settings_keyboard():
    futures = SETTINGS['FUTURES']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {futures['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {futures['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {futures['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${futures['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Мин. сумма: ${futures['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${futures['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Прибыль: ${futures['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if futures['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)


def get_spot_futures_settings_keyboard():
    spot_futures = SETTINGS['SPOT_FUTURES']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {spot_futures['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {spot_futures['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {spot_futures['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${spot_futures['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Мин. сумма: ${spot_futures['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${spot_futures['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Прибыль: ${spot_futures['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if spot_futures['ENABLED'] else 'ВЫКЛ'}")],
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


def load_markets_sync(exchange):
    try:
        exchange.load_markets()
        logger.info(f"Рынки загружены для {exchange.id}")
        return exchange
    except Exception as e:
        logger.error(f"Ошибка загрузки {exchange.id}: {e}")
        return None


async def fetch_ticker_data(exchange, symbol: str):
    try:
        # Для AscendEX используем альтернативный метод если основной не работает
        if exchange.id == "ascendex":
            try:
                # Пробуем альтернативный метод получения данных
                ticker = await asyncio.get_event_loop().run_in_executor(
                    None, exchange.fetch_ticker, symbol.replace(':USDT', '-USDT')
                )
            except:
                ticker = await asyncio.get_event_loop().run_in_executor(
                    None, exchange.fetch_ticker, symbol
                )
        else:
            ticker = await asyncio.get_event_loop().run_in_executor(
                None, exchange.fetch_ticker, symbol
            )

        if ticker:
            price = float(ticker['last']) if ticker.get('last') else None

            # Пытаемся получить объем из разных источников
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


async def fetch_order_book(exchange, symbol: str, depth: int = SETTINGS['SPOT']['ORDER_BOOK_DEPTH']):
    try:
        order_book = await asyncio.get_event_loop().run_in_executor(
            None, exchange.fetch_order_book, symbol, depth)
        logger.debug(f"Стакан загружен для {symbol} на {exchange.id}")
        return order_book
    except Exception as e:
        logger.warning(f"Ошибка стакана {symbol} на {exchange.id}: {e}")
        return None


def calculate_available_volume(order_book, side: str, max_impact_percent: float):
    if not order_book:
        return 0

    if side == 'buy':
        asks = order_book['asks']
        if not asks:
            return 0
        best_ask = asks[0][0]
        max_allowed_price = best_ask * (1 + max_impact_percent / 100)
        total_volume = 0
        for price, volume in asks:
            if price > max_allowed_price:
                break
            total_volume += volume
        return total_volume
    elif side == 'sell':
        bids = order_book['bids']
        if not bids:
            return 0
        best_bid = bids[0][0]
        min_allowed_price = best_bid * (1 - max_impact_percent / 100)
        total_volume = 0
        for price, volume in bids:
            if price < min_allowed_price:
                break
            total_volume += volume
        return total_volume
    return 0


async def check_deposit_withdrawal_status(exchange, currency: str, check_type: str = 'deposit'):
    try:
        try:
            currencies = await asyncio.get_event_loop().run_in_executor(
                None, exchange.fetch_currencies)
            if currency in currencies:
                currency_info = currencies[currency]
                if check_type == 'deposit':
                    status = currency_info.get('deposit', False)
                else:
                    status = currency_info.get('withdraw', False)
                logger.debug(
                    f"Статус {check_type} для {currency} на {exchange.id}: {status} (через fetch_currencies)"
                )
                return status
        except (ccxt.NotSupported, AttributeError) as e:
            logger.debug(
                f"fetch_currencies не поддерживается на {exchange.id}: {e}")

        try:
            symbol = f"{currency}/USDT"
            market = exchange.market(symbol)
            if market:
                if check_type == 'deposit':
                    status = market.get('deposit', True)
                else:
                    status = market.get('withdraw', True)
                logger.debug(
                    f"Статус {check_type} для {currency} на {exchange.id}: {status} (через market)"
                )
                return status
        except (ccxt.BadSymbol, KeyError) as e:
            logger.debug(
                f"Ошибка проверки market для {currency} на {exchange.id}: {e}")

        try:
            currency_info = exchange.currency(currency)
            if check_type == 'deposit':
                status = currency_info.get(
                    'active', False) and currency_info.get('deposit', True)
            else:
                status = currency_info.get(
                    'active', False) and currency_info.get('withdraw', True)
            logger.debug(
                f"Статус {check_type} для {currency} на {exchange.id}: {status} (через currency)"
            )
            return status
        except (KeyError, AttributeError) as e:
            logger.debug(
                f"Ошибка проверки currency для {currency} на {exchange.id}: {e}"
            )

        logger.debug(
            f"Не удалось проверить статус {check_type} для {currency} на {exchange.id}, предполагаем True"
        )
        return True
    except Exception as e:
        logger.warning(
            f"Ошибка проверки {check_type} {currency} на {exchange.id}: {e}")
        return True


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


async def check_spot_arbitrage():
    logger.info("Запуск проверки спотового арбитража")

    if not SETTINGS['SPOT']['ENABLED']:
        logger.info("Спотовый арбитраж отключен в настройках")
        return

    # Инициализация бирж
    global SPOT_EXCHANGES_LOADED
    exchanges = {}
    for name, config in SPOT_EXCHANGES.items():
        if not SETTINGS['EXCHANGES'][name]['ENABLED']:
            continue

        try:
            # Для BloFin устанавливаем правильный тип рынка
            if name == "blofin":
                config["api"].options['defaultType'] = 'spot'

            exchange = await asyncio.get_event_loop().run_in_executor(
                None, load_markets_sync, config["api"])
            if exchange:
                exchanges[name] = {"api": exchange, "config": config}
                logger.info(f"{name.upper()} успешно загружена")

                # Дополнительная проверка для BloFin
                if name == "blofin":
                    spot_markets = [m for m in exchange.markets.values() if config["is_spot"](m)]
                    logger.info(f"BloFin спотовые рынки: {len(spot_markets)}")
                    for market in spot_markets[:5]:  # Показать первые 5 рынков для проверки
                        logger.info(f"BloFin рынок: {market['symbol']}")
        except Exception as e:
            logger.error(f"Ошибка инициализации {name}: {e}")

    SPOT_EXCHANGES_LOADED = exchanges

    if len(exchanges) < SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']:
        logger.error(
            f"Недостаточно бирж (нужно минимум {SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']})")
        return

    # Сбор всех торговых пар
    all_pairs = defaultdict(set)
    for name, data in exchanges.items():
        exchange = data["api"]
        config = data["config"]
        for symbol, market in exchange.markets.items():
            try:
                if config["is_spot"](market):
                    base = market['base']
                    all_pairs[base].add((name, symbol))
            except Exception as e:
                logger.warning(
                    f"Ошибка обработки пары {symbol} на {name}: {e}")

    valid_pairs = {
        base: list(pairs)
        for base, pairs in all_pairs.items()
        if len(pairs) >= SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']
    }

    if not valid_pairs:
        logger.error("Нет пар, торгуемых хотя бы на двух биржах")
        return

    logger.info(f"Найдено {len(valid_pairs)} пар для анализа")

    while SETTINGS['SPOT']['ENABLED']:
        try:
            found_opportunities = 0
            for base, exchange_symbols in valid_pairs.items():
                try:
                    ticker_data = {}

                    # Получаем данные тикеров для всех бирж
                    for name, symbol in exchange_symbols:
                        try:
                            data = await fetch_ticker_data(
                                exchanges[name]["api"], symbol)
                            if data and data['price'] is not None:
                                # Если объем известен, проверяем минимальный объем
                                if data['volume'] is None:
                                    logger.debug(f"Объем неизвестен для {symbol} на {name}, но продолжаем обработку")
                                    ticker_data[name] = data
                                elif data['volume'] >= SETTINGS['SPOT']['MIN_VOLUME_USD']:
                                    ticker_data[name] = data
                                else:
                                    logger.debug(
                                        f"Объем {symbol} на {name} слишком мал: {data['volume']}"
                                    )
                            else:
                                logger.debug(
                                    f"Нет данных для {symbol} на {name}")
                        except Exception as e:
                            logger.warning(
                                f"Ошибка получения данных {base} на {name}: {e}"
                            )

                    if len(ticker_data) < SETTINGS['SPOT']['MIN_EXCHANGES_FOR_PAIR']:
                        continue

                    # Сортируем биржи по цене
                    sorted_data = sorted(ticker_data.items(),
                                         key=lambda x: x[1]['price'])
                    min_ex = sorted_data[0]  # Самая низкая цена (покупка)
                    max_ex = sorted_data[-1]  # Самая высокая цена (продажа)

                    # Рассчитываем спред
                    spread = (max_ex[1]['price'] -
                              min_ex[1]['price']) / min_ex[1]['price'] * 100

                    logger.debug(
                        f"Пара {base}: спред {spread:.2f}% (min: {min_ex[0]} {min_ex[1]['price']}, max: {max_ex[0]} {max_ex[1]['price']})"
                    )

                    if SETTINGS['SPOT']['THRESHOLD_PERCENT'] <= spread <= SETTINGS['SPOT']['MAX_THRESHOLD_PERCENT']:
                        # Проверяем доступность депозита и вывода
                        deposit_available = await check_deposit_withdrawal_status(
                            exchanges[max_ex[0]]["api"], base, 'deposit')
                        withdrawal_available = await check_deposit_withdrawal_status(
                            exchanges[min_ex[0]]["api"], base, 'withdrawal')

                        logger.debug(
                            f"Пара {base}: депозит={deposit_available}, вывод={withdrawal_available}"
                        )

                        if not (deposit_available and withdrawal_available):
                            logger.debug(
                                f"Пропускаем {base}: депозит или вывод недоступен"
                            )
                            continue

                        # Получаем стаканы ордеров
                        buy_exchange = exchanges[min_ex[0]]["api"]
                        sell_exchange = exchanges[max_ex[0]]["api"]
                        buy_symbol = min_ex[1]['symbol']
                        sell_symbol = max_ex[1]['symbol']

                        buy_order_book, sell_order_book = await asyncio.gather(
                            fetch_order_book(buy_exchange, buy_symbol),
                            fetch_order_book(sell_exchange, sell_symbol))

                        if not buy_order_book or not sell_order_book:
                            logger.debug(
                                f"Пропускаем {base}: нет данных стакана")
                            continue

                        # Рассчитываем доступный объем
                        buy_volume = calculate_available_volume(
                            buy_order_book, 'buy', SETTINGS['SPOT']['MAX_IMPACT_PERCENT'])
                        sell_volume = calculate_available_volume(
                            sell_order_book, 'sell', SETTINGS['SPOT']['MAX_IMPACT_PERCENT'])
                        available_volume = min(buy_volume, sell_volume)

                        logger.debug(
                            f"Пара {base}: доступный объем {available_volume}")

                        if available_volume <= 0:
                            continue

                        # Получаем комиссии
                        buy_fee = exchanges[min_ex[0]]["config"]["taker_fee"]
                        sell_fee = exchanges[max_ex[0]]["config"]["taker_fee"]

                        # Рассчитываем минимальную сумму для MIN_NET_PROFIT_USD
                        min_amount_for_profit = calculate_min_entry_amount(
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
                            min_profit=SETTINGS['SPOT']['MIN_NET_PROFIT_USD'],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee)

                        if min_amount_for_profit <= 0:
                            logger.debug(
                                f"Пропускаем {base}: недостаточная прибыль")
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_possible_amount = min(
                            available_volume,
                            SETTINGS['SPOT']['MAX_ENTRY_AMOUNT_USDT'] / min_ex[1]['price'])

                        max_entry_amount = max_possible_amount * min_ex[1][
                            'price']
                        min_entry_amount = max(min_amount_for_profit,
                                               SETTINGS['SPOT']['MIN_ENTRY_AMOUNT_USDT'])

                        if min_entry_amount > max_entry_amount:
                            logger.debug(
                                f"Пропускаем {base}: min_entry_amount > max_entry_amount"
                            )
                            continue

                        # Рассчитываем прибыль
                        profit_min = calculate_profit(
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
                            amount=min_entry_amount / min_ex[1]['price'],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee)

                        profit_max = calculate_profit(
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
                            amount=max_possible_amount,
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee)

                        # Форматируем сообщение
                        utc_plus_3 = timezone(timedelta(hours=3))
                        current_time = datetime.now(utc_plus_3).strftime(
                            '%H:%M:%S')

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
                        buy_exchange_config = SPOT_EXCHANGES[min_ex[0]]
                        sell_exchange_config = SPOT_EXCHANGES[max_ex[0]]

                        buy_url = buy_exchange_config["url_format"](buy_symbol)
                        sell_url = sell_exchange_config["url_format"](
                            sell_symbol)
                        withdraw_url = buy_exchange_config["withdraw_url"](
                            base)
                        deposit_url = sell_exchange_config["deposit_url"](base)

                        message = (
                            f"🚀 <b>Спотовый арбитраж:</b> <code>{safe_base}</code>\n"
                            f"▫️ <b>Разница цен:</b> {spread:.2f}%\n"
                            f"▫️ <b>Доступный объем:</b> {available_volume:.6f} {safe_base}\n"
                            f"▫️ <b>Сумма входа:</b> ${min_entry_amount:.2f}-${max_entry_amount:.2f}\n\n"
                            f"🟢 <b>Покупка на <a href='{buy_url}'>{min_ex[0].upper()}</a>:</b> ${min_ex[1]['price']:.8f}\n"
                            f"   <b>Объём:</b> {min_volume}\n"
                            f"   <b>Комиссия:</b> {buy_fee * 100:.2f}%\n"
                            f"   <b><a href='{withdraw_url}'>Вывод</a></b>\n\n"
                            f"🔴 <b>Продажа на <a href='{sell_url}'>{max_ex[0].upper()}</a>:</b> ${max_ex[1]['price']:.8f}\n"
                            f"   <b>Объём:</b> {max_volume}\n"
                            f"   <b>Комиссия:</b> {sell_fee * 100:.2f}%\n"
                            f"   <b><a href='{deposit_url}'>Депозит</a></b>\n\n"
                            f"💰️ <b>Чистая прибыль:</b> ${profit_min['net']:.2f}-${profit_max['net']:.2f} ({profit_max['percent']:.2f}%)\n\n"
                            f"⏱ {current_time}\n")

                        logger.info(
                            f"Найдена арбитражная возможность: {base} ({spread:.2f}%)"
                        )
                        await send_telegram_message(message)
                        found_opportunities += 1

                except Exception as e:
                    logger.error(f"Ошибка обработки пары {base}: {e}")

            logger.info(
                f"Цикл спотового арбитража завершен. Найдено возможностей: {found_opportunities}")
            await asyncio.sleep(SETTINGS['SPOT']['CHECK_INTERVAL'])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле спотового арбитража: {e}")
            await asyncio.sleep(60)


async def check_futures_arbitrage():
    logger.info("Запуск проверки фьючерсного арбитража")

    if not SETTINGS['FUTURES']['ENABLED']:
        logger.info("Фьючерсный арбитраж отключен в настройках")
        return

    # Инициализация бирж
    global FUTURES_EXCHANGES_LOADED
    exchanges = {}
    for name, config in FUTURES_EXCHANGES.items():
        if not SETTINGS['EXCHANGES'][name]['ENABLED']:
            continue

        try:
            # Для BloFin устанавливаем правильный тип рынка
            if name == "blofin":
                config["api"].options['defaultType'] = 'swap'

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

    if len(exchanges) < SETTINGS['FUTURES']['MIN_EXCHANGES_FOR_PAIR']:
        logger.error(f"Недостаточно бирж (нужно минимум {SETTINGS['FUTURES']['MIN_EXCHANGES_FOR_PAIR']})")
        return

    # Сбор всех торговых пар USDT
    all_pairs = defaultdict(set)
    for name, data in exchanges.items():
        exchange = data["api"]
        config = data["config"]
        for symbol, market in exchange.markets.items():
            try:
                if config["is_futures"](market):
                    base = market['base']
                    if base not in config["blacklist"]:
                        all_pairs[base].add((name, symbol))
            except Exception as e:
                logger.warning(f"Ошибка обработки пары {symbol} на {name}: {e}")

    valid_pairs = {
        base: list(pairs) for base, pairs in all_pairs.items()
        if len(pairs) >= SETTINGS['FUTURES']['MIN_EXCHANGES_FOR_PAIR']
    }

    if not valid_pairs:
        logger.error("Нет фьючерсных USDT пар, торгуемых хотя бы на двух биржах")
        return

    logger.info(f"Найдено {len(valid_pairs)} фьючерсных USDT пар для анализа")

    while SETTINGS['FUTURES']['ENABLED']:
        try:
            found_opportunities = 0
            for base, exchange_symbols in valid_pairs.items():
                try:
                    ticker_data = {}

                    # Получаем данные тикеров для всех бирж
                    for name, symbol in exchange_symbols:
                        try:
                            data = await fetch_ticker_data(exchanges[name]["api"], symbol)
                            if data and data['price'] is not None:
                                # Если объем известен, проверяем минимальный объем
                                if data['volume'] is None:
                                    logger.debug(f"Объем неизвестен для {symbol} на {name}, но продолжаем обработку")
                                    ticker_data[name] = data
                                elif data['volume'] >= SETTINGS['FUTURES']['MIN_VOLUME_USD']:
                                    ticker_data[name] = data
                                else:
                                    logger.debug(f"Объем {symbol} на {name} слишком мал: {data['volume']}")
                            else:
                                logger.debug(f"Нет данных для {symbol} на {name}")
                        except Exception as e:
                            logger.warning(f"Ошибка получения данных {base} на {name}: {e}")

                    if len(ticker_data) < SETTINGS['FUTURES']['MIN_EXCHANGES_FOR_PAIR']:
                        continue

                    # Сортируем биржи по цене
                    sorted_data = sorted(ticker_data.items(), key=lambda x: x[1]['price'])
                    min_ex = sorted_data[0]  # Самая низкая цена (покупка)
                    max_ex = sorted_data[-1]  # Самая высокая цена (продажа)

                    # Рассчитываем спред
                    spread = (max_ex[1]['price'] - min_ex[1]['price']) / min_ex[1]['price'] * 100

                    logger.debug(
                        f"Пара {base}: спред {spread:.2f}% (min: {min_ex[0]} {min_ex[1]['price']}, max: {max_ex[0]} {max_ex[1]['price']})")

                    if SETTINGS['FUTURES']['THRESHOLD_PERCENT'] <= spread <= SETTINGS['FUTURES'][
                        'MAX_THRESHOLD_PERCENT']:
                        # Получаем комиссии
                        buy_fee = exchanges[min_ex[0]]["config"]["taker_fee"]
                        sell_fee = exchanges[max_ex[0]]["config"]["taker_fee"]

                        # Рассчитываем минимальную сумму для MIN_NET_PROFIT_USD
                        min_amount_for_profit = calculate_min_entry_amount(
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
                            min_profit=SETTINGS['FUTURES']['MIN_NET_PROFIT_USD'],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        if min_amount_for_profit <= 0:
                            logger.debug(f"Пропускаем {base}: недостаточная прибыль")
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_entry_amount = SETTINGS['FUTURES']['MAX_ENTRY_AMOUNT_USDT']
                        min_entry_amount = max(min_amount_for_profit, SETTINGS['FUTURES']['MIN_ENTRY_AMOUNT_USDT'])

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
                        buy_exchange_config = FUTURES_EXCHANGES[min_ex[0]]
                        sell_exchange_config = FUTURES_EXCHANGES[max_ex[0]]

                        buy_url = buy_exchange_config["url_format"](min_ex[1]['symbol'].replace(':USDT', ''))
                        sell_url = sell_exchange_config["url_format"](max_ex[1]['symbol'].replace(':USDT', ''))

                        message = (
                            f"📊 <b>Фьючерсный арбитраж:</b> <code>{safe_base}</code>\n"
                            f"▫️ <b>Разница цен:</b> {spread:.2f}%\n"
                            f"▫️ <b>Сумма входа:</b> ${min_entry_amount:.2f}-${max_entry_amount:.2f}\n\n"
                            f"🟢 <b>Лонг на <a href='{buy_url}'>{min_ex[0].upper()}</a>:</b> ${min_ex[1]['price']:.8f}\n"
                            f"   <b>Объём:</b> {min_volume}\n"
                            f"   <b>Комиссия:</b> {buy_fee * 100:.3f}%\n\n"
                            f"🔴 <b>Шорт на <a href='{sell_url}'>{max_ex[0].upper()}</a>:</b> ${max_ex[1]['price']:.8f}\n"
                            f"   <b>Объём:</b> {max_volume}\n"
                            f"   <b>Комиссия:</b> {sell_fee * 100:.3f}%\n\n"
                            f"💰 <b>Чистая прибыль:</b> ${profit_min['net']:.2f}-${profit_max['net']:.2f} ({profit_max['percent']:.2f}%)\n\n"
                            f"⏱ {current_time}\n"
                        )

                        logger.info(f"Найдена арбитражная возможность: {base} ({spread:.2f}%)")
                        await send_telegram_message(message)
                        found_opportunities += 1

                except Exception as e:
                    logger.error(f"Ошибка обработки пары {base}: {e}")

            logger.info(f"Цикл фьючерсного арбитража завершен. Найдено возможностей: {found_opportunities}")
            await asyncio.sleep(SETTINGS['FUTURES']['CHECK_INTERVAL'])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле фьючерсного арбитража: {e}")
            await asyncio.sleep(60)


async def check_spot_futures_arbitrage():
    """Проверка спот-фьючерсного арбитража"""
    logger.info("Запуск проверки спот-фьючерсного арбитража")

    if not SETTINGS['SPOT_FUTURES']['ENABLED']:
        logger.info("Спот-фьючерсный арбитраж отключен в настройках")
        return

    # Инициализация бирж
    global SPOT_EXCHANGES_LOADED, FUTURES_EXCHANGES_LOADED

    # Загружаем спотовые биржи, если еще не загружены
    if not SPOT_EXCHANGES_LOADED:
        spot_exchanges = {}
        for name, config in SPOT_EXCHANGES.items():
            if not SETTINGS['EXCHANGES'][name]['ENABLED']:
                continue
            try:
                if name == "blofin":
                    config["api"].options['defaultType'] = 'spot'
                exchange = await asyncio.get_event_loop().run_in_executor(
                    None, load_markets_sync, config["api"])
                if exchange:
                    spot_exchanges[name] = {"api": exchange, "config": config}
            except Exception as e:
                logger.error(f"Ошибка инициализации спотовой биржи {name}: {e}")
        SPOT_EXCHANGES_LOADED = spot_exchanges

    # Загружаем фьючерсные биржи, если еще не загружены
    if not FUTURES_EXCHANGES_LOADED:
        futures_exchanges = {}
        for name, config in FUTURES_EXCHANGES.items():
            if not SETTINGS['EXCHANGES'][name]['ENABLED']:
                continue
            try:
                if name == "blofin":
                    config["api"].options['defaultType'] = 'swap'
                exchange = await asyncio.get_event_loop().run_in_executor(
                    None, load_markets_sync, config["api"])
                if exchange:
                    futures_exchanges[name] = {"api": exchange, "config": config}
            except Exception as e:
                logger.error(f"Ошибка инициализации фьючерсной биржи {name}: {e}")
        FUTURES_EXCHANGES_LOADED = futures_exchanges

    if len(SPOT_EXCHANGES_LOADED) < 1 or len(FUTURES_EXCHANGES_LOADED) < 1:
        logger.error("Недостаточно бирж для спот-фьючерсного арбитража")
        return

    # Собираем все торговые пары
    spot_pairs = defaultdict(set)
    futures_pairs = defaultdict(set)

    # Собираем спотовые пары
    for name, data in SPOT_EXCHANGES_LOADED.items():
        exchange = data["api"]
        config = data["config"]
        for symbol, market in exchange.markets.items():
            try:
                if config["is_spot"](market):
                    base = market['base']
                    spot_pairs[base].add((name, symbol))
            except Exception as e:
                logger.warning(f"Ошибка обработки спотовой пары {symbol} на {name}: {e}")

    # Собираем фьючерсные пары
    for name, data in FUTURES_EXCHANGES_LOADED.items():
        exchange = data["api"]
        config = data["config"]
        for symbol, market in exchange.markets.items():
            try:
                if config["is_futures"](market):
                    base = market['base']
                    if base not in config["blacklist"]:
                        futures_pairs[base].add((name, symbol))
            except Exception as e:
                logger.warning(f"Ошибка обработки фьючерсной пары {symbol} на {name}: {e}")

    # Находим общие пары
    common_pairs = set(spot_pairs.keys()) & set(futures_pairs.keys())

    if not common_pairs:
        logger.error("Нет общих пар для спот-фьючерсного арбитража")
        return

    logger.info(f"Найдено {len(common_pairs)} общих пар для анализа")

    while SETTINGS['SPOT_FUTURES']['ENABLED']:
        try:
            found_opportunities = 0
            for base in common_pairs:
                try:
                    spot_ticker_data = {}
                    futures_ticker_data = {}

                    # Получаем данные тикеров для спотовых бирж
                    for name, symbol in spot_pairs[base]:
                        try:
                            data = await fetch_ticker_data(SPOT_EXCHANGES_LOADED[name]["api"], symbol)
                            if data and data['price'] is not None:
                                if data['volume'] is None or data['volume'] >= SETTINGS['SPOT_FUTURES'][
                                    'MIN_VOLUME_USD']:
                                    spot_ticker_data[name] = data
                        except Exception as e:
                            logger.warning(f"Ошибка получения спотовых данных {base} на {name}: {e}")

                    # Получаем данные тикеров для фьючерсных бирж
                    for name, symbol in futures_pairs[base]:
                        try:
                            data = await fetch_ticker_data(FUTURES_EXCHANGES_LOADED[name]["api"], symbol)
                            if data and data['price'] is not None:
                                if data['volume'] is None or data['volume'] >= SETTINGS['SPOT_FUTURES'][
                                    'MIN_VOLUME_USD']:
                                    futures_ticker_data[name] = data
                        except Exception as e:
                            logger.warning(f"Ошибка получения фьючерсных данных {base} на {name}: {e}")

                    if not spot_ticker_data or not futures_ticker_data:
                        continue

                    # Находим лучшие цены
                    min_spot = min(spot_ticker_data.items(), key=lambda x: x[1]['price'])
                    max_futures = max(futures_ticker_data.items(), key=lambda x: x[1]['price'])

                    # Рассчитываем спред
                    spread = (max_futures[1]['price'] - min_spot[1]['price']) / min_spot[1]['price'] * 100

                    logger.debug(
                        f"Пара {base}: спред {spread:.2f}% (spot: {min_spot[0]} {min_spot[1]['price']}, futures: {max_futures[0]} {max_futures[1]['price']})")

                    if SETTINGS['SPOT_FUTURES']['THRESHOLD_PERCENT'] <= spread <= SETTINGS['SPOT_FUTURES'][
                        'MAX_THRESHOLD_PERCENT']:
                        # Проверяем доступность депозита и вывода для спота
                        deposit_available = await check_deposit_withdrawal_status(
                            SPOT_EXCHANGES_LOADED[min_spot[0]]["api"], base, 'deposit')
                        withdrawal_available = await check_deposit_withdrawal_status(
                            SPOT_EXCHANGES_LOADED[min_spot[0]]["api"], base, 'withdrawal')

                        if not (deposit_available and withdrawal_available):
                            logger.debug(f"Пропускаем {base}: депозит или вывод недоступен")
                            continue

                        # Получаем комиссии
                        spot_fee = SPOT_EXCHANGES[min_spot[0]]["taker_fee"]
                        futures_fee = FUTURES_EXCHANGES[max_futures[0]]["taker_fee"]

                        # Рассчитываем минимальную сумму для MIN_NET_PROFIT_USD
                        min_amount_for_profit = calculate_min_entry_amount(
                            buy_price=min_spot[1]['price'],
                            sell_price=max_futures[1]['price'],
                            min_profit=SETTINGS['SPOT_FUTURES']['MIN_NET_PROFIT_USD'],
                            buy_fee_percent=spot_fee,
                            sell_fee_percent=futures_fee
                        )

                        if min_amount_for_profit <= 0:
                            logger.debug(f"Пропускаем {base}: недостаточная прибыль")
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_entry_amount = SETTINGS['SPOT_FUTURES']['MAX_ENTRY_AMOUNT_USDT']
                        min_entry_amount = max(min_amount_for_profit, SETTINGS['SPOT_FUTURES']['MIN_ENTRY_AMOUNT_USDT'])

                        if min_entry_amount > max_entry_amount:
                            logger.debug(f"Пропускаем {base}: min_entry_amount > max_entry_amount")
                            continue

                        # Рассчитываем прибыль
                        profit_min = calculate_profit(
                            buy_price=min_spot[1]['price'],
                            sell_price=max_futures[1]['price'],
                            amount=min_entry_amount / min_spot[1]['price'],
                            buy_fee_percent=spot_fee,
                            sell_fee_percent=futures_fee
                        )

                        profit_max = calculate_profit(
                            buy_price=min_spot[1]['price'],
                            sell_price=max_futures[1]['price'],
                            amount=max_entry_amount / min_spot[1]['price'],
                            buy_fee_percent=spot_fee,
                            sell_fee_percent=futures_fee
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

                        spot_volume = format_volume(min_spot[1]['volume'])
                        futures_volume = format_volume(max_futures[1]['volume'])

                        safe_base = html.escape(base)
                        spot_exchange_config = SPOT_EXCHANGES[min_spot[0]]
                        futures_exchange_config = FUTURES_EXCHANGES[max_futures[0]]

                        spot_url = spot_exchange_config["url_format"](min_spot[1]['symbol'])
                        futures_url = futures_exchange_config["url_format"](
                            max_futures[1]['symbol'].replace(':USDT', ''))
                        withdraw_url = spot_exchange_config["withdraw_url"](base)
                        deposit_url = spot_exchange_config["deposit_url"](base)

                        message = (
                            f"↔️ <b>Спот-Фьючерсный арбитраж:</b> <code>{safe_base}</code>\n"
                            f"▫️ <b>Разница цен:</b> {spread:.2f}%\n"
                            f"▫️ <b>Сумма входа:</b> ${min_entry_amount:.2f}-${max_entry_amount:.2f}\n\n"
                            f"🟢 <b>Покупка на споте <a href='{spot_url}'>{min_spot[0].upper()}</a>:</b> ${min_spot[1]['price']:.8f}\n"
                            f"   <b>Объём:</b> {spot_volume}\n"
                            f"   <b>Комиссия:</b> {spot_fee * 100:.2f}%\n"
                            f"   <b><a href='{withdraw_url}'>Вывод</a> | <a href='{deposit_url}'>Депозит</a></b>\n\n"
                            f"🔴 <b>Шорт на фьючерсах <a href='{futures_url}'>{max_futures[0].upper()}</a>:</b> ${max_futures[1]['price']:.8f}\n"
                            f"   <b>Объём:</b> {futures_volume}\n"
                            f"   <b>Комиссия:</b> {futures_fee * 100:.3f}%\n\n"
                            f"💰 <b>Чистая прибыль:</b> ${profit_min['net']:.2f}-${profit_max['net']:.2f} ({profit_max['percent']:.2f}%)\n\n"
                            f"⏱ {current_time}\n"
                        )

                        logger.info(f"Найдена спот-фьючерсная арбитражная возможность: {base} ({spread:.2f}%)")
                        await send_telegram_message(message)
                        found_opportunities += 1

                except Exception as e:
                    logger.error(f"Ошибка обработки пары {base}: {e}")

            logger.info(f"Цикл спот-фьючерсного арбитража завершен. Найдено возможностей: {found_opportunities}")
            await asyncio.sleep(SETTINGS['SPOT_FUTURES']['CHECK_INTERVAL'])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле спот-фьючерсного арбитража: {e}")
            await asyncio.sleep(60)


def format_price(price: float) -> str:
    """Форматирует цену для красивого отображения"""
    if price is None:
        return "N/A"

    # Для цен > 1000 используем запятые как разделители тысяч
    if price >= 1000:
        return f"${price:,.2f}"

    # Для цен > 1 используем 4 знака после запятой
    if price >= 1:
        return f"${price:.4f}"

    # Для цен < 1 используем 8 знаков после запятой
    return f"${price:.8f}"


def format_volume(vol: float) -> str:
    """Форматирует объем для красивого отображения"""
    if vol is None:
        return "N/A"

    # Для объемов > 1 миллиона
    if vol >= 1_000_000:
        return f"${vol / 1_000_000:,.1f}M"

    # Для объемов > 1000
    if vol >= 1_000:
        return f"${vol / 1_000:,.1f}K"

    # Для объемов < 1000
    return f"${vol:,.0f}"


async def get_coin_prices(coin: str, market_type: str):
    """Получает цены монеты на всех биржах для указанного рынка"""
    coin = coin.upper()
    exchanges = SPOT_EXCHANGES_LOADED if market_type == "spot" else FUTURES_EXCHANGES_LOADED

    if not exchanges:
        return "❌ Биржи еще не загружены. Попробуйте позже."

    results = []
    found_on = 0

    for name, data in exchanges.items():
        exchange = data["api"]
        config = data["config"]

        # Формируем символ в зависимости от типа рынка
        symbol = config["symbol_format"](coin)

        try:
            market = exchange.market(symbol)
            if (market_type == "spot" and config["is_spot"](market)) or \
                    (market_type == "futures" and config["is_futures"](market)):

                ticker = await fetch_ticker_data(exchange, symbol)
                if ticker and ticker['price']:
                    found_on += 1
                    price = ticker['price']
                    volume = ticker.get('volume')

                    # Получаем URL для биржи
                    url = config["url_format"](symbol)

                    # Добавляем данные для сортировки
                    results.append({
                        "price": price,
                        "name": name.upper(),
                        "volume": volume,
                        "url": url,
                        "emoji": config.get("emoji", "🏛")
                    })
        except Exception as e:
            logger.warning(f"Ошибка получения цены {symbol} на {name}: {e}")

    # Сортируем результаты по цене (от низкой к высокой)
    results.sort(key=lambda x: x["price"])

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    market_name = "Спот" if market_type == "spot" else "Фьючерсы"
    market_color = "🚀" if market_type == "spot" else "📊"

    if results:
        # Рассчитываем разницу в процентах между самой низкой и высокой ценой
        min_price = results[0]["price"]
        max_price = results[-1]["price"]
        price_diff_percent = ((max_price - min_price) / min_price) * 100

        # Формируем заголовок
        response = f"{market_color} <b>{market_name} рынки для <code>{coin}</code>:</b>\n\n"

        # Добавляем данные по каждой бирже
        for idx, item in enumerate(results, 1):
            # Сделаем название биржи кликабельной ссылкой
            response += (
                f"{item['emoji']} <a href='{item['url']}'><b>{item['name']}</b></a>\n"
                f"▫️ Цена: {format_price(item['price'])}\n"
                f"▫️ Объем: {format_volume(item['volume'])}\n"
            )

            # Добавляем разделитель, если это не последний элемент
            if idx < len(results):
                response += "\n"

        # Добавляем разницу цен и время
        response += f"\n📈 <b>Разница цен:</b> {price_diff_percent:.2f}%\n"
        response += f"⏱ {current_time} | Бирж: {found_on}"
    else:
        response = f"❌ Монета {coin} не найдена на {market_name} рынке"

    return response


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 <b>Crypto Arbitrage Bot</b>\n\n"
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

    elif text == "📊 Статус бота":
        spot_status = "✅ ВКЛ" if SETTINGS['SPOT']['ENABLED'] else "❌ ВЫКЛ"
        futures_status = "✅ ВКЛ" if SETTINGS['FUTURES']['ENABLED'] else "❌ ВЫКЛ"
        spot_futures_status = "✅ ВКЛ" if SETTINGS['SPOT_FUTURES']['ENABLED'] else "❌ ВЫКЛ"

        enabled_exchanges = [name for name, config in SETTINGS['EXCHANGES'].items() if config['ENABLED']]
        exchanges_status = ", ".join(enabled_exchanges) if enabled_exchanges else "Нет активных бирж"

        await update.message.reply_text(
            f"🤖 <b>Статус бота</b>\n\n"
            f"🚀 Спотовый арбитраж: {spot_status}\n"
            f"📊 Фьючерсный арбитраж: {futures_status}\n"
            f"↔️ Спот-Фьючерсный арбитраж: {spot_futures_status}\n"
            f"🏛 Активные биржи: {exchanges_status}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "🤖 <b>Crypto Arbitrage Bot</b>\n\n"
            "🔍 <b>Поиск монеты</b> - показывает цены на разных биржах, просто введите название монеты (BTC, ETH...)\n"
            "🔧 <b>Настройки</b> - позволяет настроить параметры арбитража\n"
            "📊 <b>Статус бота</b> - показывает текущее состояние бота\n\n"
            "Бот автоматически ищет арбитражные возможности и присылает уведомления.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    # Если это не команда, предполагаем, что это название монеты
    if not text.startswith('/'):
        # Проверяем, что введен допустимый символ (только буквы и цифры)
        if re.match(r'^[A-Z0-9]{1,15}$', text.upper()):
            # Сохраняем монету в контексте и предлагаем выбрать тип рынка
            context.user_data['coin'] = text.upper()
            await update.message.reply_text(
                f"🔍 Выберите тип рынка для <b><code>{text.upper()}</code></b>:",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton(f"🚀 {text.upper()} Спот"), KeyboardButton(f"📊 {text.upper()} Фьючерсы")],
                    [KeyboardButton("🔙 Главное меню")]
                ], resize_keyboard=True)
            )
            return COIN_SELECTION
        else:
            await update.message.reply_text(
                "⚠️ Неверный формат названия монеты. Используйте только буквы и цифры (например BTC или ETH)",
                reply_markup=get_main_keyboard()
            )
            return

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_main_keyboard()
    )


async def handle_coin_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа рынка для монеты"""
    text = update.message.text
    coin = context.user_data.get('coin')

    if text == "🔙 Главное меню":
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    if not coin:
        await update.message.reply_text(
            "Не удалось определить монету. Попробуйте снова.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    if "Спот" in text:
        market_type = "spot"
    elif "Фьючерсы" in text:
        market_type = "futures"
    else:
        await update.message.reply_text(
            "Пожалуйста, выберите тип рынка с помощью кнопок.",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton(f"🚀 {coin} Спот"), KeyboardButton(f"📊 {coin} Фьючерсы")],
                [KeyboardButton("🔙 Главное меню")]
            ], resize_keyboard=True)
        )
        return COIN_SELECTION

    # Показываем "Загрузка..."
    await update.message.reply_text(
        f"⏳ Загружаем данные для <b><code>{coin}</code></b> на {'споте' if market_type == 'spot' else 'фьючерсах'}...",
        parse_mode="HTML"
    )

    # Получаем данные
    response = await get_coin_prices(coin, market_type)

    # Отправляем результаты
    await update.message.reply_text(
        text=response,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка меню настроек"""
    text = update.message.text

    if text == "🚀️ Спот":
        await update.message.reply_text(
            "🚀️ <b>Настройки спотового арбитража</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_spot_settings_keyboard()
        )
        return SPOT_SETTINGS

    elif text == "📊 Фьючерсы":
        await update.message.reply_text(
            "📊 <b>Настройки фьючерсного арбитража</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_futures_settings_keyboard()
        )
        return FUTURES_SETTINGS

    elif text == "↔️ Спот-Фьючерсы":
        await update.message.reply_text(
            "↔️ <b>Настройки спот-фьючерсного арбитража</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_spot_futures_settings_keyboard()
        )
        return SPOT_FUTURES_SETTINGS

    elif text == "🏛 Биржи":
        await update.message.reply_text(
            "🏛 <b>Настройки бирж</b>\n\nВыберите биржу для включения/выключения:",
            parse_mode="HTML",
            reply_markup=get_exchange_settings_keyboard()
        )
        return EXCHANGE_SETTINGS_MENU

    elif text == "🔄 Сброс":
        global SETTINGS
        SETTINGS = {
            "SPOT": DEFAULT_SPOT_SETTINGS.copy(),
            "FUTURES": DEFAULT_FUTURES_SETTINGS.copy(),
            "SPOT_FUTURES": DEFAULT_SPOT_FUTURES_SETTINGS.copy(),
            "EXCHANGES": EXCHANGE_SETTINGS.copy()
        }
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


async def handle_spot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек спота"""
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

    elif text.startswith("Статус:"):
        SETTINGS['SPOT']['ENABLED'] = not SETTINGS['SPOT']['ENABLED']
        save_settings(SETTINGS)
        status = "ВКЛ" if SETTINGS['SPOT']['ENABLED'] else "ВЫКЛ"
        await update.message.reply_text(
            f"✅ Спотовый арбитраж {status}",
            reply_markup=get_spot_settings_keyboard()
        )
        return SPOT_SETTINGS

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_spot_settings_keyboard()
    )
    return SPOT_SETTINGS


async def handle_futures_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек фьючерсов"""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки бота</b>\n\nВыберите категориу:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    # Обработка изменения параметров
    if text.startswith("Порог:"):
        context.user_data['setting'] = ('FUTURES', 'THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для порога арбитража (текущее: {SETTINGS['FUTURES']['THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. порог:"):
        context.user_data['setting'] = ('FUTURES', 'MAX_THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для максимального порога (текущее: {SETTINGS['FUTURES']['MAX_THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Интервал:"):
        context.user_data['setting'] = ('FUTURES', 'CHECK_INTERVAL')
        await update.message.reply_text(
            f"Введите новое значение для интервала проверки (текущее: {SETTINGS['FUTURES']['CHECK_INTERVAL']} сек):"
        )
        return SETTING_VALUE

    elif text.startswith("Объем:"):
        context.user_data['setting'] = ('FUTURES', 'MIN_VOLUME_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимального объема (текущее: ${SETTINGS['FUTURES']['MIN_VOLUME_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Мин. сумма:"):
        context.user_data['setting'] = ('FUTURES', 'MIN_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для минимальной суммы входа (текущее: ${SETTINGS['FUTURES']['MIN_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. сумма:"):
        context.user_data['setting'] = ('FUTURES', 'MAX_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для максимальной суммы входа (текущее: ${SETTINGS['FUTURES']['MAX_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Прибыль:"):
        context.user_data['setting'] = ('FUTURES', 'MIN_NET_PROFIT_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимальной прибыли (текущее: ${SETTINGS['FUTURES']['MIN_NET_PROFIT_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Статус:"):
        SETTINGS['FUTURES']['ENABLED'] = not SETTINGS['FUTURES']['ENABLED']
        save_settings(SETTINGS)
        status = "ВКЛ" if SETTINGS['FUTURES']['ENABLED'] else "ВЫКЛ"
        await update.message.reply_text(
            f"✅ Фьючерсный арбитраж {status}",
            reply_markup=get_futures_settings_keyboard()
        )
        return FUTURES_SETTINGS

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_futures_settings_keyboard()
    )
    return FUTURES_SETTINGS


async def handle_spot_futures_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек спот-фьючерсов"""
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
        context.user_data['setting'] = ('SPOT_FUTURES', 'THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для порога арбитража (текущее: {SETTINGS['SPOT_FUTURES']['THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. порог:"):
        context.user_data['setting'] = ('SPOT_FUTURES', 'MAX_THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для максимального порога (текущее: {SETTINGS['SPOT_FUTURES']['MAX_THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Интервал:"):
        context.user_data['setting'] = ('SPOT_FUTURES', 'CHECK_INTERVAL')
        await update.message.reply_text(
            f"Введите новое значение для интервала проверки (текущее: {SETTINGS['SPOT_FUTURES']['CHECK_INTERVAL']} сек):"
        )
        return SETTING_VALUE

    elif text.startswith("Объем:"):
        context.user_data['setting'] = ('SPOT_FUTURES', 'MIN_VOLUME_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимального объема (текущее: ${SETTINGS['SPOT_FUTURES']['MIN_VOLUME_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Мин. сумма:"):
        context.user_data['setting'] = ('SPOT_FUTURES', 'MIN_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для минимальной суммы входа (текущее: ${SETTINGS['SPOT_FUTURES']['MIN_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. сумма:"):
        context.user_data['setting'] = ('SPOT_FUTURES', 'MAX_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для максимальной суммы входа (текущее: ${SETTINGS['SPOT_FUTURES']['MAX_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Прибыль:"):
        context.user_data['setting'] = ('SPOT_FUTURES', 'MIN_NET_PROFIT_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимальной прибыли (текущее: ${SETTINGS['SPOT_FUTURES']['MIN_NET_PROFIT_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Статус:"):
        SETTINGS['SPOT_FUTURES']['ENABLED'] = not SETTINGS['SPOT_FUTURES']['ENABLED']
        save_settings(SETTINGS)
        status = "ВКЛ" if SETTINGS['SPOT_FUTURES']['ENABLED'] else "ВЫКЛ"
        await update.message.reply_text(
            f"✅ Спот-Фьючерсный арбитраж {status}",
            reply_markup=get_spot_futures_settings_keyboard()
        )
        return SPOT_FUTURES_SETTINGS

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_spot_futures_settings_keyboard()
    )
    return SPOT_FUTURES_SETTINGS


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
        if text.startswith(exchange):
            SETTINGS['EXCHANGES'][exchange]['ENABLED'] = not SETTINGS['EXCHANGES'][exchange]['ENABLED']
            save_settings(SETTINGS)
            status = "✅" if SETTINGS['EXCHANGES'][exchange]['ENABLED'] else "❌"
            await update.message.reply_text(
                f"{exchange} {'включена' if SETTINGS['EXCHANGES'][exchange]['ENABLED'] else 'выключена'}",
                reply_markup=get_exchange_settings_keyboard()
            )
            return EXCHANGE_SETTINGS_MENU

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_exchange_settings_keyboard()
    )
    return EXCHANGE_SETTINGS_MENU


async def handle_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода значения настройки"""
    try:
        new_value = float(update.message.text)
        category, setting = context.user_data['setting']

        if setting in ['THRESHOLD_PERCENT', 'MAX_THRESHOLD_PERCENT', 'MAX_IMPACT_PERCENT']:
            # Процентные значения
            if new_value <= 0 or new_value > 100:
                await update.message.reply_text("❌ Значение должно быть между 0 и 100. Попробуйте снова:")
                return SETTING_VALUE
        elif setting in ['MIN_VOLUME_USD', 'MIN_ENTRY_AMOUNT_USDT', 'MAX_ENTRY_AMOUNT_USDT', 'MIN_NET_PROFIT_USD']:
            # Денежные значения
            if new_value <= 0:
                await update.message.reply_text("❌ Значение должно быть положительным. Попробуйте снова:")
                return SETTING_VALUE
        elif setting == 'CHECK_INTERVAL':
            # Интервал в секундах
            if new_value < 5 or new_value > 3600:
                await update.message.reply_text("❌ Интервал должен быть между 5 и 3600 секунд. Попробуйте снова:")
                return SETTING_VALUE
        elif setting == 'ORDER_BOOK_DEPTH':
            # Глубина стакана
            if new_value < 1 or new_value > 50:
                await update.message.reply_text("❌ Глубина стакана должна быть между 1 и 50. Попробуйте снова:")
                return SETTING_VALUE

        SETTINGS[category][setting] = new_value
        save_settings(SETTINGS)

        if category == 'SPOT':
            await update.message.reply_text(
                f"✅ Параметр {setting} изменен на {new_value}",
                reply_markup=get_spot_settings_keyboard()
            )
            return SPOT_SETTINGS
        elif category == 'FUTURES':
            await update.message.reply_text(
                f"✅ Параметр {setting} изменен на {new_value}",
                reply_markup=get_futures_settings_keyboard()
            )
            return FUTURES_SETTINGS
        elif category == 'SPOT_FUTURES':
            await update.message.reply_text(
                f"✅ Параметр {setting} изменен на {new_value}",
                reply_markup=get_spot_futures_settings_keyboard()
            )
            return SPOT_FUTURES_SETTINGS

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите числовое значение:")
        return SETTING_VALUE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущей операции"""
    await update.message.reply_text(
        "Операция отменена.",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END


async def start_bot():
    """Запуск Telegram бота с обработчиками команд"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Добавляем обработчики
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SETTINGS_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings)],
            SPOT_SETTINGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spot_settings)],
            FUTURES_SETTINGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_futures_settings)],
            SPOT_FUTURES_SETTINGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spot_futures_settings)],
            EXCHANGE_SETTINGS_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exchange_settings)],
            SETTING_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_setting_value)],
            COIN_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coin_selection)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    # Инициализация и запуск
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    return application


async def main():
    global SHARED_BOT
    SHARED_BOT = Bot(token=TELEGRAM_TOKEN)

    logger.info("Запуск объединенного арбитражного бота")
    try:
        # Запускаем телеграм-бот
        app = await start_bot()

        # Запускаем арбитражные задачи параллельно
        spot_task = asyncio.create_task(check_spot_arbitrage())
        futures_task = asyncio.create_task(check_futures_arbitrage())
        spot_futures_task = asyncio.create_task(check_spot_futures_arbitrage())

        # Отправляем сообщение о запуске
        await send_telegram_message("🤖 <b>Бот успешно запущен!</b>\n\n"
                                  "🚀 Спотовый арбитраж: " + ("✅ ВКЛ" if SETTINGS['SPOT']['ENABLED'] else "❌ ВЫКЛ") + "\n"
                                  "📊 Фьючерсный арбитраж: " + ("✅ ВКЛ" if SETTINGS['FUTURES']['ENABLED'] else "❌ ВЫКЛ") + "\n"
                                  "↔️ Спот-Фьючерсный арбитраж: " + ("✅ ВКЛ" if SETTINGS['SPOT_FUTURES']['ENABLED'] else "❌ ВЫКЛ") + "\n\n"
                                  "Используйте /start для просмотра меню")

        # Бесконечное ожидание
        while True:
            await asyncio.sleep(3600)

    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}")
        await send_telegram_message(f"❌ <b>Бот остановлен из-за ошибки:</b>\n{str(e)}")
    finally:
        logger.info("Бот остановлен")


if __name__ == "__main__":
    # Настройка логирования
    logging.getLogger("CryptoArbBot").setLevel(logging.DEBUG)
    logging.getLogger("ccxt").setLevel(logging.INFO)

    # Запуск асинхронного приложения
    asyncio.run(main())
