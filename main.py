#! /usr/bin/env python2

from datetime import datetime
import time
import sys
sys.path.append("./cryptomkt")
from cryptomarket.exchange.client import Client

import requests
from api_keys import api_key, api_secret
from reprint import output

market = "ETHARS"
if len(sys.argv) > 1:
    maybe_market = str.upper(sys.argv[1])
    if maybe_market in ['ETHARS', 'ETHCLP', 'XLMARS', 'XLMCLP']:
        market = maybe_market
currency = min(market.strip('XLM'), market.strip('ETH'))
crypto = min(market.strip('ARS'), market.strip('CLP'))
crypto_long_name = 'ethereum' if crypto == 'ETH' else 'stellar'
spread_threshold = 0.0275  # We start tunnel strategy obove this relation value
hot_minutes = 30  # Time for active purchases
while_seconds_delay = 20
sell_amount = 0.5 if crypto == 'ETH' else 400
# buy_amount  = 0.25  # Whe sell all FIAT available
minimum_sells_in_hot_minutes_to_sell = 3  # How purchases give us confident
buy_minimum = 50 # (ars available to buy)
bid_padding_ars = 2 if crypto == 'ETH' else 0.005
bid_padding_clp = 20  # Amount to sum or subtract from heading prices in buy/sell
transaction_commission = 0.0034  # Level 3 on cryptomkt
sell_above_global = 0.07  # Will only sell if price is this far up from global
currency_rates_api_url = 'http://free.currencyconverterapi.com/api/v3/convert?q=USD_{}&compact=ultra'
change_1h_min_to_sell = 0.54  # %
cache_time_minutes = 1
stop_order_price = 2  # Any order at a price of 2 is a stop activity order

bid_padding = bid_padding_ars
if market == 'ETHCLP':
    bid_padding = bid_padding_clp
debug_mode = False

def debug(*args):
    if debug_mode:
        print args
    else:
        global output
        output['Last event'] = ', '.join([str(a) for a in args])

# Decorator to cache fun results for wanted time, so we don't make too many requests
def cached_fun(fun, cache_time_minutes=cache_time_minutes):
    cache = {'time': 0, 'result': None}
    def wrapper(*args, **kwargs):
        now = time.time()
        if cache['time'] + cache_time_minutes * 60 < now:
            debug('Filling cache for result of fun: {} for {} seconds'.format(
                fun.__name__, cache_time_minutes * 60))
            cache['result'] = fun(*args, **kwargs)
            cache['time'] = now
        return cache['result']
    return wrapper

class MyClient(Client):
    def _get_balance(self):
        return super(MyClient, self).get_balance()

    def __init__(self, *args, **kwargs):
        super(MyClient, self).__init__(*args, **kwargs)
        self.orders = []
        self.orders_cache = []
        self.spread = {}
        self.balances = []
        self.update_active_orders()
        self.update_spread()
        self.update_balances()

    def update_active_orders(self):
        new_orders = self.get_active_orders(market).data
        if new_orders:
            self.orders_cache = self.orders        
            self.orders = new_orders
        else:
            self.orders = []
    
    def get_active_orders_of_type(self, order_type):
        self.update_active_orders()
        return [order for order in self.orders if order['type'] == order_type]
    
    def update_balances(self):
        self.balances = self._get_balance().data

    def get_balances(self):
        self.update_balances()
        return self.balances
    
    def get_balance(self, wallet=None):
        balances = self.get_balances()
        if not wallet:
            return balances
        else:
            for balance in balances:
                if balance['wallet'] == str.upper(wallet):
                    return balance

    def update_spread(self):
        result = {}
        ticker = self.get_ticker(market).data[0]
        result["difference"] = abs(float(ticker.ask) - float(ticker.bid))
        result["relation"] = result["difference"] / float(ticker.bid)
        result["porcentage"] = "%{}".format(result["relation"] * 100)
        result['bid'] = float(ticker.bid)
        result['ask'] = float(ticker.ask)
        self.spread = result

    def get_spread(self):
        self.update_spread()
        return self.spread

    def get_last_order_sell_price(self):
        # Find maximum price at which to buy according to last sell
        last_orders = self.get_executed_orders(market).data
        for order in last_orders:
            if order['type'] == 'sell':
                # This is last sell trade made
                return float(order['execution_price'])

    def get_last_trades(self, type='all', minutes_before_now=60):
        # `type`: can be 'sell', 'buy' or 'all'
        trades = self.get_trades(market).data
        now = datetime.utcnow()
        result = 0
        for trade in trades:
            dt = datetime.strptime(trade.timestamp, "%Y-%m-%dT%H:%M:%S.%f")
            delta = now - dt
            # print now, dt, delta
            if type != 'all' and trade['market_taker'] != type:
                continue
            if delta.seconds / 60 < minutes_before_now:
                result += 1
        return result

    def cancel(self, order):
        try:
            client.cancel_order(order['id'])
        except Exception as inst:
            print type(inst), inst
            traceback.print_exc()
        debug("Canceled order:", order['type'], \
                order['amount']['original'], "at", order['price'])
        return order

    def get_global_crypto_price(self, currency='usd'):
        # Return USD price of crypto right now
        # url = 'https://min-api.cryptocompare.com/data/price?fsym={crypto}&tsyms=USD'
        result = self.get_global_crypto_ticker(currency)
        key = 'price_' + str.lower(currency)
        return float(result[key])

    @cached_fun
    def get_global_crypto_ticker(self, currency='usd'):
        # url = 'https://api.cryptonator.com/api/ticker/'
        currency = str.lower(currency)
        url = 'https://api.coinmarketcap.com/v1/ticker/{}/?convert={}'.format(crypto_long_name, currency)
        response = requests.get(url)
        result = None
        while not result:
            try:
                result = response.json()[0]
            except ValueError:
                print "Can't access cryptonator api, retrying.."
                time.sleep(1)
        return result

    def print_balances(self):
        global output
        balances = self.get_balances()
        balance_fiat = float([b.balance for b in balances if b.wallet == currency][0])
        balance_fiat_available = float([b.available for b in balances if b.wallet == currency][0])
        balance_crypto = float([b.balance for b in balances if b.wallet == crypto][0])
        balance_crypto_available = float([b.available for b in balances if b.wallet == crypto][0])
        output["Balances (Available)"] = "{}: {} ({}), {}: {} ({})".format(currency,
            balance_fiat, balance_fiat_available, crypto, balance_crypto, balance_crypto_available)
    
    def selling_orders(self):
        orders = client.get_active_orders(market).data
        return [order for order in orders if order['type'] == 'sell']
    
    def buying_orders(self):
        orders = client.get_active_orders(market).data
        return [order for order in orders if order['type'] == 'buy']

    def selling_activity_is_hi(self):
        recent_sells = self.get_last_trades('sell', hot_minutes)
        return recent_sells >= minimum_sells_in_hot_minutes_to_sell
    
    def spread_is_hi(self):
        return spread_threshold <= self.spread['relation']  
    
    def selling_price_is_hi(self):
        global_price = self.get_global_crypto_price(currency=currency)
        return global_price * (1 + sell_above_global) <= self.get_spread()['bid']
    
    def global_price_change_is_low(self):
        pass

    def should_sell(self):
        ticker = client.get_global_crypto_ticker(currency=currency)
        change_1h = float(ticker['percent_change_1h'])
        return change_1h < change_1h_min_to_sell and \
                (self.spread_is_hi() or self.selling_activity_is_hi() or self.selling_price_is_hi())
    
    def can_buy(self):
        balance_fiat_available = float(self.get_balance(currency).available)
        return buy_minimum < balance_fiat_available
    
    def create_sell_order(self, fixed_price=None, amount=sell_amount):
        # Sell Crypto
        if fixed_price:
            sell_price = fixed_price
        else:
            sell_price = self.get_best_selling_price_above_spread_threshold()
        amount = float(amount)
        result = self.create_order(market, amount, sell_price, 'sell')
        output['Active sell order'] = "{:.3f} at ${:.3f} (${:.2f})".format(amount, sell_price, amount * sell_price)
        fixed_price_text = ""
        if fixed_price:
            fixed_price_text  = "(Using fixed_price: {})".format(fixed_price)
        debug('New order:', 'sell', market, amount, "at", sell_price, fixed_price_text)
        return result

    def get_buying_last_sell_recovery_price(self):
        last_sell_price = self.get_last_order_sell_price()
        result = last_sell_price * (1 - transaction_commission) ** 2
        return result

    def get_best_selling_price_above_spread_threshold(self):
        book = self.get_book(market, 'sell').data
        sell_minimun_price = self.spread['bid'] * (1 + spread_threshold)
        my_sell_orders = self.get_active_orders_of_type('sell')
        selling_price = None
        if my_sell_orders:
            selling_price = float(my_sell_orders[0]['price'])
        result = sell_minimun_price
        for order in book:
            order_price = float(order['price'])
            if selling_price == order_price:
                continue
            if order_price > sell_minimun_price:
                result = order_price - bid_padding
                break
        return result

    def get_best_buying_price_below_spread_threshold(self, less_than=None):
        book = self.get_book(market, 'buy').data
        if less_than:
            buy_maximum_price = less_than
        else:
            buy_maximum_price = self.spread['bid'] + bid_padding
        my_buy_orders_prices = [o['price'] for o in self.get_active_orders_of_type('buy')]
        my_buy_order_price = float(my_buy_orders_prices[0]) if my_buy_orders_prices else 0
        for order in book:
            order_price = float(order['price'])
            if order_price == my_buy_order_price:
                continue
            if order_price < buy_maximum_price:
                return order_price + bid_padding

    def create_buy_order(self, fixed_price=None):
        # Buy Crypto
        self.update_balances()
        balance_fiat_available = float([b.available for b in self.balances if b.wallet == currency][0])
        if not fixed_price:
            bid_price = self.spread['bid'] + bid_padding
            buying_recover_price = self.get_buying_last_sell_recovery_price()
            if bid_price > buying_recover_price:
                bid_price = buying_recover_price
                debug("Using last_sell_recover_price: ", buying_recover_price)
        else:
            bid_price = fixed_price
        crypto_to_buy = balance_fiat_available / bid_price
        result = self.create_order(market, crypto_to_buy, bid_price, 'buy')
        output['Active buy order'] = "{:.3f} at ${:.3f} (${:.2f})".format(crypto_to_buy, bid_price, crypto_to_buy * bid_price)
        debug('New order:', 'buy', market, crypto_to_buy, "at", bid_price, \
              "(${})".format(balance_fiat_available))
        return result

    def reorder(self, order, fixed_price=None):
        order = self.cancel(order)
        self.update_spread()
        if order['type'] == 'buy':
            self.create_buy_order(fixed_price=fixed_price)
        else:
            amount = order['amount']['remaining']
            self.create_sell_order(fixed_price=fixed_price, amount=amount)
        
    def try_to_sell_better(self, order):
        order_price = float(order['price'])
        best_selling_price = self.get_best_selling_price_above_spread_threshold()
        if order_price != best_selling_price:
            debug("Can sell better at: ${}".format(best_selling_price))
            self.reorder(order, best_selling_price)  # Try to get first on the line
        else:
            if order_price == self.get_spread()['ask']:
                debug('Selling order is first on the line')
            else:
                order_price = float(order['price'])
                percentage_above = (1 - self.spread['bid'] / order_price)//0.0001/100
                extraText = "(%{} above bid price)".format(percentage_above)
                debug("Selling order is at desired price", extraText)
    
    def try_to_buy_better(self, order):
        order_price = float(order['price'])
        if order_price < self.spread['bid'] or self.can_buy(): # can_bay() == have enough balance in fiat to buy more
            # Order is not first
            buying_recover_price = self.get_buying_last_sell_recovery_price()
            debug("buying_recover_price: {}, otherwise would sell at {}".format(buying_recover_price, self.get_best_buying_price_below_spread_threshold()))
            best_buy_price = self.get_best_buying_price_below_spread_threshold(less_than=buying_recover_price)
            if best_buy_price != order_price:
                debug("Can buy better at: ${}".format(best_buy_price))
                self.reorder(order, best_buy_price)  # Try to get first on the line
        else:
            debug('Buying order is first on the line at', order['price'])
            book = self.get_book(market, 'buy').data
            second_buyer_price = float(book[1]['price'])
            posible_cheaper_buyin_price = second_buyer_price + bid_padding
            if posible_cheaper_buyin_price < order_price:
                debug('But will try to buy cheaper...')
                self.reorder(order, posible_cheaper_buyin_price)

    def try_to_improve_orders(self):
        for order in self.orders:
            if order['type'] == 'sell':
                if self.should_sell():
                    self.try_to_sell_better(order)
                else:
                    self.cancel(order)
            else:
                # here, order['type'] == 'buy'
                self.try_to_buy_better(order)
    def is_stop_order(self, order):
        return float(order['price']) == stop_order_price
    
    def trade(self):
        global output
        self.update_active_orders()
        should_stop_activity = False
        output['Active buy order'] = 'None'
        output['Active sell order'] = 'None'
        if self.orders:
            for order in self.orders:
                if self.is_stop_order(order):
                    should_stop_activity = True
                else:
                    key = 'Active {} order'.format(order['type'])
                    output[key] = "{} at ${} (${:.2f})".format(order['amount']['remaining'], order['price'], float(order['amount']['remaining']) * float(order['price']))
            if should_stop_activity:
                output['stop_order'] = 'A stop activity order type exists (price at {}), activity is stopped until order is removed...'.format(stop_order_price)
                return       
            self.try_to_improve_orders()
            if not self.get_active_orders_of_type('buy') and self.can_buy():
                # This happen when a partial sell have been executed, so we should start buying
                self.create_buy_order()
        else:
            # No active orders
            if self.can_buy():
                # Purchase Crypto
                self.create_buy_order()
            else:
                if self.should_sell():
                    # Sell Crypto
                    self.create_sell_order()
            
    


client = MyClient(api_key, api_secret)
print 'Welcome to CryptoBot\n'
print 'Market chosen: {}\n'.format(market)

def mainCycle():
    global output
    ticker = client.get_global_crypto_ticker(currency=currency)
    crypto_global_price = ticker['price_' + str.lower(currency)]
    output['global_price'] = "Global {} price: ${}".format(market, crypto_global_price)
    output['global_price_h'] = "Global change in last hour: %" + ticker['percent_change_1h']
    # client.print_balances()
    spread = client.get_spread()
    output['spread'] = "Spread: " + spread.__repr__()
    
    # Getting recent trades
    sells = client.get_last_trades('sell', hot_minutes)
    purchases = client.get_last_trades('buy', hot_minutes)
    # Printing activity
    output['activity_sells'] = "{} sells made in the last {} minutes".format(sells, hot_minutes)
    output['activity_buys'] = "{} purchases made in the last {} minutes".format(purchases, hot_minutes)
    # Printing market status
    spread_status = u"Spread is {}".format(u"Hi \u2714" if client.spread_is_hi() else u"Low \u2718")
    spread_status += " ({} <= %{})".format(spread['porcentage'], spread_threshold * 100)
    output['spread_status'] = spread_status
    global_price = client.get_global_crypto_price(currency=currency)
    sell_percentage_above_global = (1 - global_price / client.spread['bid'])
    selling_price_status = u"Selling price is {}".format(u"Hi \u2714" if client.selling_price_is_hi() else u"Low \u2718")
    selling_price_status += " (%{} above global, specting at least %{})".format(sell_percentage_above_global//0.001/10, sell_above_global*100)
    output['selling_price_status'] = selling_price_status
    selling_activity_status = u"Selling activity is {}".format(u"Hi \u2714" if client.selling_activity_is_hi() else u"Low \u2718")
    selling_activity_status += " (at least {} in the last {} minutes)".format(minimum_sells_in_hot_minutes_to_sell, hot_minutes)
    output['selling_activity_status'] = selling_activity_status
    global_price_change_is_low = float(ticker['percent_change_1h']) < change_1h_min_to_sell
    global_price_change_status = u"Global price change is {}".format(u"Low \u2714" if global_price_change_is_low else u"Hi \u2718")
    global_price_change_status += " (%{} < %{})".format(ticker['percent_change_1h'], change_1h_min_to_sell)
    output['global_price_change_status'] = global_price_change_status

    client.trade()



# Instalar
# pip install -r requeriments.txt

# Para correr esto en ipython:
# %run main.py
import traceback
def sort_key(x):
    # print 'sort_key', len(x), x
    result = 0
    key = x[0]
    if 'activity' in key:
        result = 2
    if 'status' in key:
        result = 3
    if 'next' in key or 'event' in key:
        result = 4
    if 'Active' in key:
        result = 5
    # print "SORT_KEY", key, result
    return result
with output(output_type="dict", sort_key=sort_key) as output:
    while True:
        try:
            output['next_update'] = "now..."
            mainCycle()
        except Exception as inst:
            print type(inst), inst
            traceback.print_exc()
        # print "Will check again in {} seconds...\n".format(while_seconds_delay)
        for i in range(while_seconds_delay, 0, -1):
            output['next_update'] = "in {} seconds...".format(i)
            time.sleep(1)
