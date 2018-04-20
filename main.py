#! /usr/bin/env python2

from datetime import datetime
import time
import sys
sys.path.append("./cryptomkt")
from cryptomkt.exchange.client import Client
import requests
from api_keys import api_key, api_secret

market = "ETHARS"
if len(sys.argv) > 1:
    maybe_market = str.upper(sys.argv[1])
    if maybe_market in ['ETHARS', 'ETHCLP']:
        market = maybe_market
currency = market.strip('ETH')
spread_threshold = 0.04  # We start tunnel strategy obove this relation value
hot_minutes = 30  # Time for active purchases
while_seconds_delay = 25
sell_amount = 0.25
# buy_amount  = 0.25  # Whe sell all FIAT available
minimum_sells_in_hot_minutes_to_sell = 3  # How purchases give us confident
buy_minimum = 50
bid_padding_ars = 2
bid_padding_clp = 20  # Amount to sum or subtract from heading prices in buy/sell
transaction_commission = 0.007
sell_above_global = 0.015  # Will only sell if price is this far up from global
currency_rates_api_url = 'http://free.currencyconverterapi.com/api/v3/convert?q=USD_{}&compact=ultra'
change_1h_min_to_sell = 1  # %
cache_time_minutes = 1

bid_padding = bid_padding_ars
if market == 'ETHCLP':
    bid_padding = bid_padding_clp

# Decorator to cache fun results for wanted time, so we don't make too many requests
def cached_fun(fun, cache_time_minutes=cache_time_minutes):
    cache = {'time': 0, 'result': None}
    def wrapper(*args, **kwargs):
        now = time.time()
        if cache['time'] + cache_time_minutes * 60 < now:
            print 'Filling cache for result of fun: {} for {} seconds'.format(
                fun.__name__, cache_time_minutes * 60)
            cache['result'] = fun(*args, **kwargs)
            cache['time'] = now
        return cache['result']
    return wrapper

class MyClient(Client):
    def __init__(self, *args, **kwargs):
        super(MyClient, self).__init__(*args, **kwargs)
        self.orders = []
        self.spread = {}
        self.balances = []
        self.update_active_orders()
        self.update_spread()
        self.update_balances()
        self.usd_convertion_rate = {}

    def update_active_orders(self):
        self.orders = self.get_active_orders(market).data
    
    def get_active_orders_of_type(self, order_type):
        self.update_active_orders()
        return [order for order in self.orders if order['type'] == order_type]
    
    def update_balances(self):
        self.balances = self.get_balance().data

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
                return float(order['price'])

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
        client.cancel_order(order['id'])
        print "Canceled order:", order['type'], \
                order['amount']['original'], "at", order['price']
        return order

    def get_global_eth_price(self, currency='usd'):
        # Return USD price of ether right now
        # url = 'https://min-api.cryptocompare.com/data/price?fsym=ETH&tsyms=USD'
        result = self.get_global_eth_ticker(currency)
        key = 'price_' + str.lower(currency)
        return float(result[key])

    @cached_fun
    def get_global_eth_ticker(self, currency='usd'):
        # url = 'https://api.cryptonator.com/api/ticker/eth-usd'
        currency = str.lower(currency)
        url = 'https://api.coinmarketcap.com/v1/ticker/ethereum/?convert=' + currency
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
        balances = self.get_balance().data
        balance_fiat = float([b.balance for b in balances if b.wallet == currency][0])
        balance_fiat_available = float([b.available for b in balances if b.wallet == currency][0])
        balance_eth = float([b.balance for b in balances if b.wallet == "ETH"][0])
        balance_eth_available = float([b.available for b in balances if b.wallet == "ETH"][0])
        print "Balances (Available): {}: {} ({}), ETH: {} ({})".format(currency,
            balance_fiat, balance_fiat_available, balance_eth, balance_eth_available)
    
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
        global_price = self.get_global_eth_price(currency=currency)
        return global_price * (1 + sell_above_global) < self.get_spread()['ask']

    def should_sell(self):
        ticker = client.get_global_eth_ticker(currency=currency)
        change_1h = float(ticker['percent_change_1h'])
        return change_1h < change_1h_min_to_sell and \
                (self.spread_is_hi() or self.selling_activity_is_hi() or self.selling_price_is_hi())
    
    def can_buy(self):
        balances = self.get_balance().data
        balance_fiat_available = float([b.available for b in balances if b.wallet == currency][0])
        return buy_minimum < balance_fiat_available
    
    def create_sell_order(self, fixed_price=None, amount=sell_amount):
        # Sell ETH
        if fixed_price:
            sell_price = fixed_price
        else:
            sell_price = self.get_best_selling_price_above_spread_threshold()
        result = self.create_order(market, amount, sell_price, 'sell')
        print 'New order:', 'sell', market, amount, "at", sell_price
        if fixed_price:
            print "(Using fixed_price)"
        return result

    def get_buying_last_sell_recovery_price(self):
        last_sell_price = self.get_last_order_sell_price()
        result = last_sell_price * (1 - transaction_commission) ** 2
        return result

    def get_best_selling_price_above_spread_threshold(self):
        book = self.get_book(market, 'sell').data
        sell_minimun_price = self.spread['bid'] * (1 + spread_threshold)
        my_sell_orders = self.get_active_orders_of_type('sell')
        for order in book:
            order_price = float(order['price'])
            if [order for order in my_sell_orders if float(order['price']) == order_price]:
                continue
            if order_price > sell_minimun_price:
                return order_price - bid_padding

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
        # Buy ETH
        self.update_balances()
        balance_fiat_available = float([b.available for b in self.balances if b.wallet == currency][0])
        if not fixed_price:
            bid_price = self.spread['bid'] + bid_padding
            buying_recover_price = self.get_buying_last_sell_recovery_price()
            if bid_price > buying_recover_price:
                bid_price = buying_recover_price
                print "Using last_sell_recover_price: ", buying_recover_price
        else:
            bid_price = fixed_price
        eth_to_buy = balance_fiat_available / bid_price
        result = self.create_order(market, eth_to_buy, bid_price, 'buy')
        print 'New order:', 'buy', market, eth_to_buy, "at", bid_price, \
              "(${})".format(balance_fiat_available)
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
            print "Can sell better at: ${}".format(best_selling_price)
            self.reorder(order, best_selling_price)  # Try to get first on the line
        else:
            if order_price == self.get_spread()['ask']:
                print 'Selling order is first on the line'
            else:
                print "Selling order is at desired price"
    
    def try_to_buy_better(self, order):
        order_price = float(order['price'])
        if order_price < self.spread['bid'] or self.can_buy(): # can_bay() == have enough balance in fiat to buy more
            # Order is not first
            buying_recover_price = self.get_buying_last_sell_recovery_price()
            best_buy_price = self.get_best_buying_price_below_spread_threshold(less_than=buying_recover_price)
            if best_buy_price != order_price:
                print "Can buy better at: ${}".format(best_buy_price)
                self.reorder(order, best_buy_price)  # Try to get first on the line
        else:
            print 'Buying order is first on the line at', order['price']
            book = self.get_book(market, 'buy').data
            second_buyer_price = float(book[1]['price'])
            posible_cheaper_buyin_price = second_buyer_price + bid_padding
            if posible_cheaper_buyin_price < order_price:
                print 'But will try to buy cheaper...'
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
    
    def trade(self):
        self.update_active_orders()
        if self.should_sell() and not self.get_active_orders_of_type('sell'):
            # Sell ETH
            self.create_sell_order()
        if self.can_buy() and not self.get_active_orders_of_type('buy'):
            # Purchase ETH
           self.create_buy_order()
        else:
            for order in self.orders:
                print "1 active order to {} {} at ${}".format(order['type'], \
                        order['amount']['remaining'], order['price'])
            client.try_to_improve_orders()
    


client = MyClient(api_key, api_secret)
print 'Welcome to EtherCryptoBot\n'
print 'Market chosen: {}\n'.format(market)
def mainCycle():
    ticker = client.get_global_eth_ticker(currency=currency)
    ethars_global_price = ticker['price_' + str.lower(currency)]
    print "Global {} price: ${}".format(market, ethars_global_price)
    print "Global change in last hour: %" + ticker['percent_change_1h']
    client.print_balances()
    spread = client.get_spread()
    print "Spread:", spread
    
    # Getting recent trades
    sells = client.get_last_trades('sell', hot_minutes)
    purchases = client.get_last_trades('buy', hot_minutes)
    # Printing activity
    print 'Activity:'
    print "{} sells made in the last {} minutes".format(sells, hot_minutes)
    print "{} purchases made in the last {} minutes".format(purchases, hot_minutes)
    # Printing market status
    print "Spread is", u"Hi \u2714" if client.spread_is_hi() else u"Low \u274C" 
    print "Selling activity is", u"Hi \u2714" if client.selling_activity_is_hi() else u"Low \u274C"
    print "Sellig price is", u"Hi \u2714" if client.selling_price_is_hi() else u"Low \u274C"

    client.trade()



# Instalar
# pip install -r requeriments.txt

# Para correr esto en ipython:
# %run main.py
import traceback

while True:
    try:
        mainCycle()
    except Exception as inst:
        print type(inst), inst
        traceback.print_exc()
    print "Will check again in {} seconds...\n".format(while_seconds_delay)
    time.sleep(while_seconds_delay)
