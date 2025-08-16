import ccxt
import asyncio
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)
from telegram.error import TelegramError
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import html
import re

# Конфигурация
ADMIN_USER_ID = "1167694150"  # ID администратора
TELEGRAM_TOKEN = "8357883688:AAG5E-IwqpbTn7hJ_320wpvKQpNfkm_QQeo"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894"]  # ID пользователей с доступом

# Конфигурация по умолчанию
DEFAULT_SETTINGS = {
    # Спот
    "SPOT_THRESHOLD_PERCENT": 0.5,
    "SPOT_MAX_THRESHOLD_PERCENT": 40,
    "SPOT_CHECK_INTERVAL": 30,
    "SPOT_MIN_EXCHANGES_FOR_PAIR": 2,
    "SPOT_MIN_VOLUME_USD": 800000,
    "SPOT_MIN_ENTRY_AMOUNT_USDT": 5,
    "SPOT_MAX_ENTRY_AMOUNT_USDT": 120,
    "SPOT_MAX_IMPACT_PERCENT": 0.5,
    "SPOT_ORDER_BOOK_DEPTH": 10,
    "SPOT_MIN_NET_PROFIT_USD": 4,

    # Фьючерсы
    "FUTURES_THRESHOLD_PERCENT": 0.5,
    "FUTURES_MAX_THRESHOLD_PERCENT": 20,
    "FUTURES_CHECK_INTERVAL": 30,
    "FUTURES_MIN_VOLUME_USD": 800000,
    "FUTURES_MIN_EXCHANGES_FOR_PAIR": 2,
    "FUTURES_MIN_ENTRY_AMOUNT_USDT": 5,
    "FUTURES_MAX_ENTRY_AMOUNT_USDT": 60,
    "FUTURES_MIN_NET_PROFIT_USD": 2.5
}

# Текущие настройки (инициализируются значениями по умолчанию)
CURRENT_SETTINGS = DEFAULT_SETTINGS.copy()

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("CryptoArbBot")

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
        "url_format": lambda s: f"https://phemex.com/spot/trade/{s.replace('/', '').replace(':USDT', '')}",
        "withdraw_url": lambda c: f"https://phemex.com/assets/withdraw?asset={c}",
        "deposit_url": lambda c: f"https://phemex.com/assets/deposit?asset={c}",
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
        "emoji": "🏛"
    },
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://futures.mexc.com/exchange/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "🏛"
    },
    "okx": {
        "api": ccxt.okx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.okx.com/trade-swap/{s.replace('/', '-').replace(':USDT', '').lower()}",
        "blacklist": [],
        "emoji": "🏛"
    },
    "gate": {
        "api": ccxt.gateio({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and '_USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.gate.io/futures_trade/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "🏛"
    },
    "bitget": {
        "api": ccxt.bitget({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.bitget.com/ru/futures/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "🏛"
    },
    "kucoin": {
        "api": ccxt.kucoin({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.kucoin.com/futures/trade/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "🏛"
    },
    "htx": {
        "api": ccxt.htx({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",  # Исправление для фьючерсов
                "fetchMarkets": ["swap"]  # Загружаем только swap-рынки
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and m.get('linear', False),
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.htx.com/futures/exchange/{s.split(':')[0].replace('/', '_').lower()}",
        "blacklist": [],
        "emoji": "🏛"
    },
    "bingx": {
        "api": ccxt.bingx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://bingx.com/en-us/futures/{s.replace('/', '')}",
        "blacklist": [],
        "emoji": "🏛"
    },
    "phemex": {
        "api": ccxt.phemex({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",  # Исправление для фьючерсов
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and m['settle'] == 'USDT',
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://phemex.com/futures/trade/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "🏛"
    }
}

# Глобальные переменные
SHARED_BOT = None
SPOT_EXCHANGES_LOADED = {}
FUTURES_EXCHANGES_LOADED = {}


async def send_telegram_message(message: str, chat_id: str = None, reply_markup: InlineKeyboardMarkup = None):
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


async def fetch_order_book(exchange, symbol: str, depth: int = CURRENT_SETTINGS["SPOT_ORDER_BOOK_DEPTH"]):
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

    # Инициализация бирж
    global SPOT_EXCHANGES_LOADED
    exchanges = {}
    for name, config in SPOT_EXCHANGES.items():
        try:
            exchange = await asyncio.get_event_loop().run_in_executor(
                None, load_markets_sync, config["api"])
            if exchange:
                exchanges[name] = {"api": exchange, "config": config}
                logger.info(f"{name.upper()} успешно загружена")
        except Exception as e:
            logger.error(f"Ошибка инициализации {name}: {e}")

    SPOT_EXCHANGES_LOADED = exchanges

    if len(exchanges) < CURRENT_SETTINGS["SPOT_MIN_EXCHANGES_FOR_PAIR"]:
        logger.error(
            f"Недостаточно бирж (нужно минимум {CURRENT_SETTINGS['SPOT_MIN_EXCHANGES_FOR_PAIR']})")
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
        if len(pairs) >= CURRENT_SETTINGS["SPOT_MIN_EXCHANGES_FOR_PAIR"]
    }

    if not valid_pairs:
        logger.error("Нет пар, торгуемых хотя бы на двух биржах")
        return

    logger.info(f"Найдено {len(valid_pairs)} пар для анализа")

    while True:
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
                                elif data['volume'] >= CURRENT_SETTINGS["SPOT_MIN_VOLUME_USD"]:
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

                    if len(ticker_data) < CURRENT_SETTINGS["SPOT_MIN_EXCHANGES_FOR_PAIR"]:
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

                    if CURRENT_SETTINGS["SPOT_THRESHOLD_PERCENT"] <= spread <= CURRENT_SETTINGS[
                        "SPOT_MAX_THRESHOLD_PERCENT"]:
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
                            buy_order_book, 'buy', CURRENT_SETTINGS["SPOT_MAX_IMPACT_PERCENT"])
                        sell_volume = calculate_available_volume(
                            sell_order_book, 'sell', CURRENT_SETTINGS["SPOT_MAX_IMPACT_PERCENT"])
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
                            min_profit=CURRENT_SETTINGS["SPOT_MIN_NET_PROFIT_USD"],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee)

                        if min_amount_for_profit <= 0:
                            logger.debug(
                                f"Пропускаем {base}: недостаточная прибыль")
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_possible_amount = min(
                            available_volume,
                            CURRENT_SETTINGS["SPOT_MAX_ENTRY_AMOUNT_USDT"] / min_ex[1]['price'])

                        max_entry_amount = max_possible_amount * min_ex[1][
                            'price']
                        min_entry_amount = max(min_amount_for_profit,
                                               CURRENT_SETTINGS["SPOT_MIN_ENTRY_AMOUNT_USDT"])

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
            await asyncio.sleep(CURRENT_SETTINGS["SPOT_CHECK_INTERVAL"])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле спотового арбитража: {e}")
            await asyncio.sleep(60)


async def check_futures_arbitrage():
    logger.info("Запуск проверки фьючерсного арбитража")

    # Инициализация бирж
    global FUTURES_EXCHANGES_LOADED
    exchanges = {}
    for name, config in FUTURES_EXCHANGES.items():
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

    if len(exchanges) < CURRENT_SETTINGS["FUTURES_MIN_EXCHANGES_FOR_PAIR"]:
        logger.error(f"Недостаточно бирж (нужно минимум {CURRENT_SETTINGS['FUTURES_MIN_EXCHANGES_FOR_PAIR']})")
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
        if len(pairs) >= CURRENT_SETTINGS["FUTURES_MIN_EXCHANGES_FOR_PAIR"]
    }

    if not valid_pairs:
        logger.error("Нет фьючерсных USDT пар, торгуемых хотя бы на двух биржах")
        return

    logger.info(f"Найдено {len(valid_pairs)} фьючерсных USDT пар для анализа")

    while True:
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
                                elif data['volume'] >= CURRENT_SETTINGS["FUTURES_MIN_VOLUME_USD"]:
                                    ticker_data[name] = data
                                else:
                                    logger.debug(f"Объем {symbol} на {name} слишком мал: {data['volume']}")
                            else:
                                logger.debug(f"Нет данных для {symbol} на {name}")
                        except Exception as e:
                            logger.warning(f"Ошибка получения данных {base} на {name}: {e}")

                    if len(ticker_data) < CURRENT_SETTINGS["FUTURES_MIN_EXCHANGES_FOR_PAIR"]:
                        continue

                    # Сортируем биржи по цене
                    sorted_data = sorted(ticker_data.items(), key=lambda x: x[1]['price'])
                    min_ex = sorted_data[0]  # Самая низкая цена (покупка)
                    max_ex = sorted_data[-1]  # Самая высокая цена (продажа)

                    # Рассчитываем спред
                    spread = (max_ex[1]['price'] - min_ex[1]['price']) / min_ex[1]['price'] * 100

                    logger.debug(
                        f"Пара {base}: спред {spread:.2f}% (min: {min_ex[0]} {min_ex[1]['price']}, max: {max_ex[0]} {max_ex[1]['price']})")

                    if CURRENT_SETTINGS["FUTURES_THRESHOLD_PERCENT"] <= spread <= CURRENT_SETTINGS[
                        "FUTURES_MAX_THRESHOLD_PERCENT"]:
                        # Получаем комиссии
                        buy_fee = exchanges[min_ex[0]]["config"]["taker_fee"]
                        sell_fee = exchanges[max_ex[0]]["config"]["taker_fee"]

                        # Рассчитываем минимальную сумму для MIN_NET_PROFIT_USD
                        min_amount_for_profit = calculate_min_entry_amount(
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
                            min_profit=CURRENT_SETTINGS["FUTURES_MIN_NET_PROFIT_USD"],
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        if min_amount_for_profit <= 0:
                            logger.debug(f"Пропускаем {base}: недостаточная прибыль")
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_entry_amount = CURRENT_SETTINGS["FUTURES_MAX_ENTRY_AMOUNT_USDT"]
                        min_entry_amount = max(min_amount_for_profit, CURRENT_SETTINGS["FUTURES_MIN_ENTRY_AMOUNT_USDT"])

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
            await asyncio.sleep(CURRENT_SETTINGS["FUTURES_CHECK_INTERVAL"])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле фьючерсного арбитража: {e}")
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

        # Добавляем время и количество бирж
        response += f"\n⏱ {current_time} | Бирж: {found_on}"
    else:
        response = f"❌ Монета {coin} не найдена на {market_name} рынке"

    return response


async def handle_coin_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поиска монеты по названию"""
    user_id = str(update.effective_user.id)

    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    coin = update.message.text.strip().upper()
    if not coin:
        await update.message.reply_text("ℹ️ Введите название монеты (например BTC)")
        return

    # Проверяем, что введен допустимый символ (только буквы и цифры)
    if not re.match(r'^[A-Z0-9]{2,8}$', coin):
        await update.message.reply_text(
            "⚠️ Неверный формат названия монеты. Используйте только буквы и цифры (например BTC или ETH)")
        return

    # Создаем клавиатуру с кнопками выбора
    keyboard = [
        [
            InlineKeyboardButton("🚀 Спот", callback_data=f"spot_{coin}"),
            InlineKeyboardButton("📊 Фьючерсы", callback_data=f"futures_{coin}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🔍 Выберите тип рынка для <b><code>{coin}</code></b>:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )


async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await query.edit_message_text("⛔ У вас нет доступа к этому боту.")
        return

    data = query.data.split("_")
    if len(data) < 2:
        await query.edit_message_text("❌ Ошибка запроса")
        return

    # Обработка админских кнопок
    if data[0] == "admin":
        if user_id != ADMIN_USER_ID:
            await query.answer("⛔ Только администратор может использовать эту функцию", show_alert=True)
            return
            
        if data[1] == "panel":
            await show_admin_panel(query)
        elif data[1] == "spot":
            await show_spot_settings_help(query)
        elif data[1] == "futures":
            await show_futures_settings_help(query)
        elif data[1] == "reset":
            await reset_settings_callback(query)
        elif data[1] == "view":
            await show_settings_callback(query)
        elif data[1] == "back":
            await query.edit_message_text("🔙 Возврат в главное меню")
        return

    market_type = data[0]
    coin = "_".join(data[1:])  # На случай если coin содержит _

    # Показываем "Загрузка..."
    await query.edit_message_text(
        text=f"⏳ Загружаем данные для <b><code>{coin}</code></b> на {'споте' if market_type == 'spot' else 'фьючерсах'}...",
        parse_mode="HTML"
    )

    # Получаем данные
    response = await get_coin_prices(coin, market_type)

    # Обновляем сообщение с результатами
    await query.edit_message_text(
        text=response,
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def show_admin_panel(query: CallbackQuery):
    """Показывает панель администратора"""
    keyboard = [
        [InlineKeyboardButton("⚙️ Настройки спота", callback_data="admin_spot")],
        [InlineKeyboardButton("⚙️ Настройки фьючерсов", callback_data="admin_futures")],
        [InlineKeyboardButton("🔄 Сбросить настройки", callback_data="admin_reset")],
        [InlineKeyboardButton("👁 Просмотр настроек", callback_data="admin_view")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="👑 <b>Панель администратора</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )


async def show_spot_settings_help(query: CallbackQuery):
    """Показывает помощь по настройкам спота"""
    help_text = (
        "⚙️ <b>Настройки спотового арбитража</b>\n\n"
        "Используйте команду в формате:\n"
        "<code>/set_spot min_threshold=0.5 max_threshold=40 interval=30 min_exchanges=2 "
        "min_volume=800000 min_entry=5 max_entry=120 max_impact=0.5 depth=10 min_profit=4</code>\n\n"
        "🔹 <b>Параметры:</b>\n"
        "min_threshold - Минимальный спред (%)\n"
        "max_threshold - Максимальный спред (%)\n"
        "interval - Интервал проверки (сек)\n"
        "min_exchanges - Минимальное количество бирж\n"
        "min_volume - Минимальный объем (USD)\n"
        "min_entry - Минимальная сумма входа (USDT)\n"
        "max_entry - Максимальная сумма входа (USDT)\n"
        "max_impact - Максимальное влияние на цену (%)\n"
        "depth - Глубина стакана\n"
        "min_profit - Минимальная прибыль (USD)\n\n"
        "Пример: <code>/set_spot min_threshold=1.0 max_threshold=30 interval=45 min_volume=1000000</code>"
    )
    
    await query.edit_message_text(
        text=help_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]])
    )


async def show_futures_settings_help(query: CallbackQuery):
    """Показывает помощь по настройкам фьючерсов"""
    help_text = (
        "⚙️ <b>Настройки фьючерсного арбитража</b>\n\n"
        "Используйте команду в формате:\n"
        "<code>/set_futures min_threshold=0.5 max_threshold=20 interval=30 "
        "min_volume=800000 min_exchanges=2 min_entry=5 max_entry=60 min_profit=2.5</code>\n\n"
        "🔹 <b>Параметры:</b>\n"
        "min_threshold - Минимальный спред (%)\n"
        "max_threshold - Максимальный спред (%)\n"
        "interval - Интервал проверки (сек)\n"
        "min_volume - Минимальный объем (USD)\n"
        "min_exchanges - Минимальное количество бирж\n"
        "min_entry - Минимальная сумма входа (USDT)\n"
        "max_entry - Максимальная сумма входа (USDT)\n"
        "min_profit - Минимальная прибыль (USD)\n\n"
        "Пример: <code>/set_futures min_threshold=0.8 max_threshold=25 interval=40 min_volume=1500000</code>"
    )
    
    await query.edit_message_text(
        text=help_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]])
    )


async def reset_settings_callback(query: CallbackQuery):
    """Сбрасывает настройки к значениям по умолчанию"""
    global CURRENT_SETTINGS
    CURRENT_SETTINGS = DEFAULT_SETTINGS.copy()
    
    await query.edit_message_text(
        text="✅ Все настройки сброшены к значениям по умолчанию!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]])
    )


async def show_settings_callback(query: CallbackQuery):
    """Показывает текущие настройки"""
    settings_message = (
        "⚙️ <b>Текущие настройки арбитража</b>\n\n"
        "<b>Спотовый арбитраж:</b>\n"
        f"Минимальный спред: {CURRENT_SETTINGS['SPOT_THRESHOLD_PERCENT']}%\n"
        f"Максимальный спред: {CURRENT_SETTINGS['SPOT_MAX_THRESHOLD_PERCENT']}%\n"
        f"Интервал проверки: {CURRENT_SETTINGS['SPOT_CHECK_INTERVAL']} сек\n"
        f"Минимальное кол-во бирж: {CURRENT_SETTINGS['SPOT_MIN_EXCHANGES_FOR_PAIR']}\n"
        f"Минимальный объем: ${CURRENT_SETTINGS['SPOT_MIN_VOLUME_USD']:,.0f}\n"
        f"Минимальная сумма входа: ${CURRENT_SETTINGS['SPOT_MIN_ENTRY_AMOUNT_USDT']}\n"
        f"Максимальная сумма входа: ${CURRENT_SETTINGS['SPOT_MAX_ENTRY_AMOUNT_USDT']}\n"
        f"Максимальное влияние на цену: {CURRENT_SETTINGS['SPOT_MAX_IMPACT_PERCENT']}%\n"
        f"Глубина стакана: {CURRENT_SETTINGS['SPOT_ORDER_BOOK_DEPTH']}\n"
        f"Минимальная прибыль: ${CURRENT_SETTINGS['SPOT_MIN_NET_PROFIT_USD']}\n\n"
        "<b>Фьючерсный арбитраж:</b>\n"
        f"Минимальный спред: {CURRENT_SETTINGS['FUTURES_THRESHOLD_PERCENT']}%\n"
        f"Максимальный спред: {CURRENT_SETTINGS['FUTURES_MAX_THRESHOLD_PERCENT']}%\n"
        f"Интервал проверки: {CURRENT_SETTINGS['FUTURES_CHECK_INTERVAL']} сек\n"
        f"Минимальный объем: ${CURRENT_SETTINGS['FUTURES_MIN_VOLUME_USD']:,.0f}\n"
        f"Минимальное кол-во бирж: {CURRENT_SETTINGS['FUTURES_MIN_EXCHANGES_FOR_PAIR']}\n"
        f"Минимальная сумма входа: ${CURRENT_SETTINGS['FUTURES_MIN_ENTRY_AMOUNT_USDT']}\n"
        f"Максимальная сумма входа: ${CURRENT_SETTINGS['FUTURES_MAX_ENTRY_AMOUNT_USDT']}\n"
        f"Минимальная прибыль: ${CURRENT_SETTINGS['FUTURES_MIN_NET_PROFIT_USD']}"
    )
    
    await query.edit_message_text(
        text=settings_message,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]])
    )


async def handle_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех сообщений и команд от пользователей"""
    user_id = str(update.effective_user.id)
    message_text = update.message.text.strip()

    # Проверка доступа
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    # Обработка команд администратора
    if user_id == ADMIN_USER_ID:
        if message_text.startswith('/set_spot'):
            await set_spot_settings(update, context)
            return
        elif message_text.startswith('/set_futures'):
            await set_futures_settings(update, context)
            return
        elif message_text.startswith('/reset_settings'):
            await reset_settings(update, context)
            return
        elif message_text == '/admin':
            keyboard = [[InlineKeyboardButton("👑 Открыть панель администратора", callback_data="admin_panel")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Панель администратора:",
                reply_markup=reply_markup
            )
            return

    # Основные команды для всех пользователей
    if message_text in ['/start', '/help']:
        response = (
            "🤖 <b>Crypto Arbitrage Bot</b>\n\n"
            "🔍 Для поиска цен на монету просто введите ее название (например <code>BTC</code> или <code>ETH</code>)\n\n"
            "⚙️ Доступные команды:\n"
            "/settings - Текущие настройки\n\n"
            "📊 Бот автоматически ищет арбитражные возможности на спотовом и фьючерсном рынках и присылает уведомления"
        )
        await update.message.reply_text(response, parse_mode="HTML")
    elif message_text == '/settings':
        await show_settings(update, context)
    else:
        # Обработка текстовых сообщений (поиск монеты)
        await handle_coin_search(update, context)


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущие настройки"""
    settings_message = (
        "⚙️ <b>Текущие настройки арбитража</b>\n\n"
        "<b>Спотовый арбитраж:</b>\n"
        f"Минимальный спред: {CURRENT_SETTINGS['SPOT_THRESHOLD_PERCENT']}%\n"
        f"Максимальный спред: {CURRENT_SETTINGS['SPOT_MAX_THRESHOLD_PERCENT']}%\n"
        f"Интервал проверки: {CURRENT_SETTINGS['SPOT_CHECK_INTERVAL']} сек\n"
        f"Минимальное кол-во бирж: {CURRENT_SETTINGS['SPOT_MIN_EXCHANGES_FOR_PAIR']}\n"
        f"Минимальный объем: ${CURRENT_SETTINGS['SPOT_MIN_VOLUME_USD']:,.0f}\n"
        f"Минимальная сумма входа: ${CURRENT_SETTINGS['SPOT_MIN_ENTRY_AMOUNT_USDT']}\n"
        f"Максимальная сумма входа: ${CURRENT_SETTINGS['SPOT_MAX_ENTRY_AMOUNT_USDT']}\n"
        f"Максимальное влияние на цену: {CURRENT_SETTINGS['SPOT_MAX_IMPACT_PERCENT']}%\n"
        f"Глубина стакана: {CURRENT_SETTINGS['SPOT_ORDER_BOOK_DEPTH']}\n"
        f"Минимальная прибыль: ${CURRENT_SETTINGS['SPOT_MIN_NET_PROFIT_USD']}\n\n"
        "<b>Фьючерсный арбитраж:</b>\n"
        f"Минимальный спред: {CURRENT_SETTINGS['FUTURES_THRESHOLD_PERCENT']}%\n"
        f"Максимальный спред: {CURRENT_SETTINGS['FUTURES_MAX_THRESHOLD_PERCENT']}%\n"
        f"Интервал проверки: {CURRENT_SETTINGS['FUTURES_CHECK_INTERVAL']} сек\n"
        f"Минимальный объем: ${CURRENT_SETTINGS['FUTURES_MIN_VOLUME_USD']:,.0f}\n"
        f"Минимальное кол-во бирж: {CURRENT_SETTINGS['FUTURES_MIN_EXCHANGES_FOR_PAIR']}\n"
        f"Минимальная сумма входа: ${CURRENT_SETTINGS['FUTURES_MIN_ENTRY_AMOUNT_USDT']}\n"
        f"Максимальная сумма входа: ${CURRENT_SETTINGS['FUTURES_MAX_ENTRY_AMOUNT_USDT']}\n"
        f"Минимальная прибыль: ${CURRENT_SETTINGS['FUTURES_MIN_NET_PROFIT_USD']}"
    )

    await update.message.reply_text(settings_message, parse_mode="HTML")


async def set_spot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Устанавливает новые настройки для спотового арбитража"""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Использование: /set_spot min_threshold=0.5 max_threshold=40 interval=30 "
            "min_exchanges=2 min_volume=800000 min_entry=5 max_entry=120 max_impact=0.5 depth=10 min_profit=4"
        )
        return

    # Парсинг аргументов
    params = {}
    for arg in context.args:
        if '=' not in arg:
            continue

        key, value = arg.split('=', 1)
        key = key.lower()

        try:
            # Преобразование числовых параметров
            if key in ['min_threshold', 'max_threshold', 'max_impact']:
                params[key] = float(value)
            elif key in ['min_volume', 'min_entry', 'max_entry', 'min_profit']:
                params[key] = float(value)
            elif key in ['interval', 'min_exchanges', 'depth']:
                params[key] = int(value)
        except ValueError:
            await update.message.reply_text(f"⚠️ Ошибка в значении параметра {key}")
            return

    # Обновление настроек
    if 'min_threshold' in params:
        CURRENT_SETTINGS["SPOT_THRESHOLD_PERCENT"] = params['min_threshold']
    if 'max_threshold' in params:
        CURRENT_SETTINGS["SPOT_MAX_THRESHOLD_PERCENT"] = params['max_threshold']
    if 'interval' in params:
        CURRENT_SETTINGS["SPOT_CHECK_INTERVAL"] = params['interval']
    if 'min_exchanges' in params:
        CURRENT_SETTINGS["SPOT_MIN_EXCHANGES_FOR_PAIR"] = params['min_exchanges']
    if 'min_volume' in params:
        CURRENT_SETTINGS["SPOT_MIN_VOLUME_USD"] = params['min_volume']
    if 'min_entry' in params:
        CURRENT_SETTINGS["SPOT_MIN_ENTRY_AMOUNT_USDT"] = params['min_entry']
    if 'max_entry' in params:
        CURRENT_SETTINGS["SPOT_MAX_ENTRY_AMOUNT_USDT"] = params['max_entry']
    if 'max_impact' in params:
        CURRENT_SETTINGS["SPOT_MAX_IMPACT_PERCENT"] = params['max_impact']
    if 'depth' in params:
        CURRENT_SETTINGS["SPOT_ORDER_BOOK_DEPTH"] = params['depth']
    if 'min_profit' in params:
        CURRENT_SETTINGS["SPOT_MIN_NET_PROFIT_USD"] = params['min_profit']

    await update.message.reply_text("✅ Настройки спотового арбитража обновлены!")


async def set_futures_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Устанавливает новые настройки для фьючерсного арбитража"""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Использование: /set_futures min_threshold=0.5 max_threshold=20 interval=30 "
            "min_volume=800000 min_exchanges=2 min_entry=5 max_entry=60 min_profit=2.5"
        )
        return

    # Парсинг аргументов
    params = {}
    for arg in context.args:
        if '=' not in arg:
            continue

        key, value = arg.split('=', 1)
        key = key.lower()

        try:
            # Преобразование числовых параметров
            if key in ['min_threshold', 'max_threshold']:
                params[key] = float(value)
            elif key in ['min_volume', 'min_entry', 'max_entry', 'min_profit']:
                params[key] = float(value)
            elif key in ['interval', 'min_exchanges']:
                params[key] = int(value)
        except ValueError:
            await update.message.reply_text(f"⚠️ Ошибка в значении параметра {key}")
            return

    # Обновление настроек
    if 'min_threshold' in params:
        CURRENT_SETTINGS["FUTURES_THRESHOLD_PERCENT"] = params['min_threshold']
    if 'max_threshold' in params:
        CURRENT_SETTINGS["FUTURES_MAX_THRESHOLD_PERCENT"] = params['max_threshold']
    if 'interval' in params:
        CURRENT_SETTINGS["FUTURES_CHECK_INTERVAL"] = params['interval']
    if 'min_volume' in params:
        CURRENT_SETTINGS["FUTURES_MIN_VOLUME_USD"] = params['min_volume']
    if 'min_exchanges' in params:
        CURRENT_SETTINGS["FUTURES_MIN_EXCHANGES_FOR_PAIR"] = params['min_exchanges']
    if 'min_entry' in params:
        CURRENT_SETTINGS["FUTURES_MIN_ENTRY_AMOUNT_USDT"] = params['min_entry']
    if 'max_entry' in params:
        CURRENT_SETTINGS["FUTURES_MAX_ENTRY_AMOUNT_USDT"] = params['max_entry']
    if 'min_profit' in params:
        CURRENT_SETTINGS["FUTURES_MIN_NET_PROFIT_USD"] = params['min_profit']

    await update.message.reply_text("✅ Настройки фьючерсного арбитража обновлены!")


async def reset_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает настройки к значениям по умолчанию"""
    global CURRENT_SETTINGS
    CURRENT_SETTINGS = DEFAULT_SETTINGS.copy()
    await update.message.reply_text("✅ Все настройки сброшены к значениям по умолчанию!")


async def start_bot():
    """Запуск Telegram бота с обработчиками команд"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрируем обработчики:
    application.add_handler(CommandHandler("start", handle_any_message))
    application.add_handler(CommandHandler("help", handle_any_message))
    application.add_handler(CommandHandler("settings", show_settings))
    application.add_handler(CommandHandler("admin", handle_any_message))

    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.COMMAND, handle_any_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_any_message))
    application.add_handler(CallbackQueryHandler(handle_button_click))

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

        # Бесконечное ожидание
        while True:
            await asyncio.sleep(3600)

    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}")
    finally:
        logger.info("Бот остановлен")


if __name__ == "__main__":
    # Настройка логирования
    logging.getLogger("CryptoArbBot").setLevel(logging.DEBUG)
    logging.getLogger("ccxt").setLevel(logging.INFO)

    # Запуск асинхронного приложения
    asyncio.run(main())