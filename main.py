import ccxt
import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import TelegramError
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import html

# Общая конфигурация
TELEGRAM_TOKEN = "7574157588:AAEcrPchVsKoyLlxV53HTuQ3bgOZjPlvaOQ"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894"]  # ID пользователей с доступом

# Конфигурация спотового арбитража
SPOT_THRESHOLD_PERCENT = 0.5
SPOT_MAX_THRESHOLD_PERCENT = 40
SPOT_CHECK_INTERVAL = 30
SPOT_MIN_EXCHANGES_FOR_PAIR = 2
SPOT_MIN_VOLUME_USD = 150000
SPOT_MIN_ENTRY_AMOUNT_USDT = 5
SPOT_MAX_ENTRY_AMOUNT_USDT = 100
SPOT_MAX_IMPACT_PERCENT = 0.5
SPOT_ORDER_BOOK_DEPTH = 5
SPOT_MIN_NET_PROFIT_USD = 3

# Конфигурация фьючерсного арбитража
FUTURES_THRESHOLD_PERCENT = 0.5
FUTURES_MAX_THRESHOLD_PERCENT = 20
FUTURES_CHECK_INTERVAL = 30
FUTURES_MIN_VOLUME_USD = 150000
FUTURES_MIN_EXCHANGES_FOR_PAIR = 2
FUTURES_MIN_ENTRY_AMOUNT_USDT = 5
FUTURES_MAX_ENTRY_AMOUNT_USDT = 50
FUTURES_MIN_NET_PROFIT_USD = 1.5

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
        "deposit_url": lambda c: f"https://www.bybit.com/user/assets/deposit"
    },
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.mexc.com/exchange/{s.replace('/', '_')}",
        "withdraw_url": lambda c: f"https://www.mexc.com/ru-RU/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.mexc.com/ru-RU/assets/deposit/{c}"
    },
    "okx": {
        "api": ccxt.okx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.0008,
        "url_format": lambda s: f"https://www.okx.com/trade-spot/{s.replace('/', '-').lower()}",
        "withdraw_url": lambda c: f"https://www.okx.com/ru/balance/withdrawal/{c.lower()}-chain",
        "deposit_url": lambda c: f"https://www.okx.com/ru/balance/recharge/{c.lower()}"
    },
    "gate": {
        "api": ccxt.gateio({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.gate.io/trade/{s.replace('/', '_')}",
        "withdraw_url": lambda c: f"https://www.gate.io/myaccount/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.gate.io/myaccount/deposit/{c}"
    },
    "bitget": {
        "api": ccxt.bitget({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.bitget.com/spot/{s.replace('/', '')}_SPBL",
        "withdraw_url": lambda c: f"https://www.bitget.com/ru/asset/withdraw?coinId={c}",
        "deposit_url": lambda c: f"https://www.bitget.com/ru/asset/recharge?coinId={c}"
    },
    "kucoin": {
        "api": ccxt.kucoin({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.kucoin.com/trade/{s.replace('/', '-')}",
        "withdraw_url": lambda c: f"https://www.kucoin.com/ru/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.kucoin.com/ru/assets/coin/{c}"
    },
    "htx": {
        "api": ccxt.htx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.htx.com/trade/{s.replace('/', '_').lower()}",
        "withdraw_url": lambda c: f"https://www.htx.com/ru-ru/finance/withdraw/{c.lower()}",
        "deposit_url": lambda c: f"https://www.htx.com/ru-ru/finance/deposit/{c.lower()}"
    },
    "bingx": {
        "api": ccxt.bingx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://bingx.com/spot/{s.replace('/', '')}",
        "withdraw_url": lambda c: f"https://bingx.com/en-us/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://bingx.com/en-us/assets/deposit/{c}"
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
        "blacklist": ["BTC", "ETH"]
    },
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://futures.mexc.com/exchange/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": []
    },
    "okx": {
        "api": ccxt.okx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.okx.com/trade-swap/{s.replace('/', '-').replace(':USDT', '').lower()}",
        "blacklist": []
    },
    "gate": {
        "api": ccxt.gateio({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and '_USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.gate.io/futures_trade/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": []
    },
    "bitget": {
        "api": ccxt.bitget({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.bitget.com/ru/futures/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": []
    },
    "kucoin": {
        "api": ccxt.kucoin({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.kucoin.com/futures/trade/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": []
    },
    "htx": {
        "api": ccxt.htx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.htx.com/futures/exchange/{s.replace('/', '_').lower()}",
        "blacklist": []
    },
    "bingx": {
        "api": ccxt.bingx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://bingx.com/en-us/futures/{s.replace('/', '')}",
        "blacklist": []
    }
}

# Глобальные переменные
SHARED_BOT = None


async def send_telegram_message(message: str):
    global SHARED_BOT
    if not SHARED_BOT:
        SHARED_BOT = Bot(token=TELEGRAM_TOKEN)

    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            await SHARED_BOT.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"Сообщение отправлено в чат {chat_id}")
        except TelegramError as e:
            logger.error(f"Ошибка отправки в {chat_id}: {e}")


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
            volume = float(ticker['quoteVolume']) if ticker.get('quoteVolume') else None

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


async def fetch_order_book(exchange, symbol: str, depth: int = SPOT_ORDER_BOOK_DEPTH):
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

    if len(exchanges) < SPOT_MIN_EXCHANGES_FOR_PAIR:
        logger.error(
            f"Недостаточно бирж (нужно минимум {SPOT_MIN_EXCHANGES_FOR_PAIR})")
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
        if len(pairs) >= SPOT_MIN_EXCHANGES_FOR_PAIR
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
                            if data and data['price'] is not None and data[
                                'volume'] is not None:
                                if data['volume'] >= SPOT_MIN_VOLUME_USD:
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

                    if len(ticker_data) < SPOT_MIN_EXCHANGES_FOR_PAIR:
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

                    if SPOT_THRESHOLD_PERCENT <= spread <= SPOT_MAX_THRESHOLD_PERCENT:
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
                            buy_order_book, 'buy', SPOT_MAX_IMPACT_PERCENT)
                        sell_volume = calculate_available_volume(
                            sell_order_book, 'sell', SPOT_MAX_IMPACT_PERCENT)
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
                            min_profit=SPOT_MIN_NET_PROFIT_USD,
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee)

                        if min_amount_for_profit <= 0:
                            logger.debug(
                                f"Пропускаем {base}: недостаточная прибыль")
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_possible_amount = min(
                            available_volume,
                            SPOT_MAX_ENTRY_AMOUNT_USDT / min_ex[1]['price'])

                        max_entry_amount = max_possible_amount * min_ex[1][
                            'price']
                        min_entry_amount = max(min_amount_for_profit,
                                               SPOT_MIN_ENTRY_AMOUNT_USDT)

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
            await asyncio.sleep(SPOT_CHECK_INTERVAL)

        except Exception as e:
            logger.error(f"Ошибка в основном цикле спотового арбитража: {e}")
            await asyncio.sleep(60)


async def check_futures_arbitrage():
    logger.info("Запуск проверки фьючерсного арбитража")

    # Инициализация бирж
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

    if len(exchanges) < FUTURES_MIN_EXCHANGES_FOR_PAIR:
        logger.error(f"Недостаточно бирж (нужно минимум {FUTURES_MIN_EXCHANGES_FOR_PAIR})")
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
        if len(pairs) >= FUTURES_MIN_EXCHANGES_FOR_PAIR
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
                            if data and data['price'] is not None and data['volume'] is not None:
                                if data['volume'] >= FUTURES_MIN_VOLUME_USD:
                                    ticker_data[name] = data
                                else:
                                    logger.debug(f"Объем {symbol} на {name} слишком мал: {data['volume']}")
                            else:
                                logger.debug(f"Нет данных для {symbol} на {name}")
                        except Exception as e:
                            logger.warning(f"Ошибка получения данных {base} на {name}: {e}")

                    if len(ticker_data) < FUTURES_MIN_EXCHANGES_FOR_PAIR:
                        continue

                    # Сортируем биржи по цене
                    sorted_data = sorted(ticker_data.items(), key=lambda x: x[1]['price'])
                    min_ex = sorted_data[0]  # Самая низкая цена (покупка)
                    max_ex = sorted_data[-1]  # Самая высокая цена (продажа)

                    # Рассчитываем спред
                    spread = (max_ex[1]['price'] - min_ex[1]['price']) / min_ex[1]['price'] * 100

                    logger.debug(
                        f"Пара {base}: спред {spread:.2f}% (min: {min_ex[0]} {min_ex[1]['price']}, max: {max_ex[0]} {max_ex[1]['price']})")

                    if FUTURES_THRESHOLD_PERCENT <= spread <= FUTURES_MAX_THRESHOLD_PERCENT:
                        # Получаем комиссии
                        buy_fee = exchanges[min_ex[0]]["config"]["taker_fee"]
                        sell_fee = exchanges[max_ex[0]]["config"]["taker_fee"]

                        # Рассчитываем минимальную сумму для MIN_NET_PROFIT_USD
                        min_amount_for_profit = calculate_min_entry_amount(
                            buy_price=min_ex[1]['price'],
                            sell_price=max_ex[1]['price'],
                            min_profit=FUTURES_MIN_NET_PROFIT_USD,
                            buy_fee_percent=buy_fee,
                            sell_fee_percent=sell_fee
                        )

                        if min_amount_for_profit <= 0:
                            logger.debug(f"Пропускаем {base}: недостаточная прибыль")
                            continue

                        # Рассчитываем максимально возможную сумму входа
                        max_entry_amount = FUTURES_MAX_ENTRY_AMOUNT_USDT
                        min_entry_amount = max(min_amount_for_profit, FUTURES_MIN_ENTRY_AMOUNT_USDT)

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
            await asyncio.sleep(FUTURES_CHECK_INTERVAL)

        except Exception as e:
            logger.error(f"Ошибка в основном цикле фьючерсного арбитража: {e}")
            await asyncio.sleep(60)


async def handle_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех сообщений и команд от пользователей"""
    user_id = str(update.effective_user.id)

    if user_id in TELEGRAM_CHAT_IDS:
        response = "🤖 Бот работает в автономном режиме и не принимает команды. Все арбитражные возможности будут отправляться автоматически."
    else:
        response = "⛔ У вас нет доступа к этому боту."

    await update.message.reply_text(response)


async def start_bot():
    """Запуск Telegram бота с обработчиками команд"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрируем обработчики:
    # 1. Для любых команд (начинающихся с /)
    application.add_handler(CommandHandler("start", handle_any_message))
    application.add_handler(CommandHandler("help", handle_any_message))

    # 2. Обработчик для всех остальных команд (которые не указаны явно)
    application.add_handler(MessageHandler(filters.COMMAND, handle_any_message))

    # 3. Обработчик для обычных текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_any_message))

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