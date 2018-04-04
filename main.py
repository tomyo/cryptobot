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
while_seconds_delay = 30
sell_amount = 0.25
# buy_amount  = 0.25  # Whe sell all FIAT available
minimum_sells_in_hot_minutes_to_sell = 3  # How purchases give us confident
buy_minimum = 50
bid_padding_ars = 2
bid_padding_clp = 20  # Amount to sum or subtract from heading prices in buy/sell
transaction_commission = 0.007
sell_above_global = 0.015  # Will only sell if price is this far up from global
currency_rates_api_url = 'http://free.currencyconverterapi.com/api/v3/convert?q=USD_{}&compact=ultra'

bid_padding = bid_padding_ars
if market == 'ETHCLP':
    bid_padding = bid_padding_clp


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

    def cancel_orders(self):
        for order in self.orders:
            if order['type'] == 'sell':
                print 'order to cancel', order
                result = self.cancel_order(order['id'])
                print "Order: {} to {} at {} Canceled".format(result['id'],
                                              result['type'], result['price'])

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

    def create_sell_order(self, fixed_price=None):
        # Sell ETH
        if fixed_price:
            sell_price = fixed_price
        else:
            sell_price = self.spread['ask'] - bid_padding
            eth_global_price = client.get_global_eth_price(currency=currency)
            sell_for_at_least = eth_global_price * (1 + sell_above_global)
            if sell_price < sell_for_at_least:
                # TODO: sell anyway if there is alot of buying activity
                print 'Current sell price is too low right now to sell.', \
                       '(should be at least ${})'.format(sell_for_at_least)
                if self.is_good_time_to_sell():
                    print 'But recent selling activity is hi, so lets sell.'
                else:
                    print 'Also, no rencent selling activity so not worthy.'
                    return
        result = self.create_order(market, sell_amount, sell_price, 'sell')
        print 'New order:', market, sell_amount, "at", sell_price, 'sell'
        if fixed_price:
            print "(Using fixed_price)"
        return result

    def get_buying_last_sell_recover_price(self):
        last_sell_price = self.get_last_order_sell_price()
        last_sell_amount = last_sell_price * sell_amount * (1 - transaction_commission)
        result = last_sell_price * (1 - transaction_commission) ** 2
        return result

    def get_best_selling_price_above_spread_threshold(self):
        book = self.get_book(market, 'sell').data
        sell_minimun_price = self.spread['bid'] * (1 + spread_threshold)
        for order in book:
            order_price = float(order['price'])
            if order_price > sell_minimun_price:
                return order_price - bid_padding

    # def get_best_buying_price_below_spread_threshold(self):
    #     book = self.get_book(market, 'buy').data
    #     buy_maximum_price = self.spread['bid'] * (1 - spread_threshold)
    #     for order in book:
    #         order_price = float(order['price'])
    #         if order_price < buy_maximum_price:
    #             return order_price - bid_padding

    def create_buy_order(self, fixed_price=None):
        # Buy ETH
        self.update_balances()
        balance_fiat_available = float([b.available for b in self.balances if b.wallet == currency][0])
        if not fixed_price:
            bid_price = self.spread['bid'] + bid_padding
            buying_recover_price = self.get_buying_last_sell_recover_price()
            if bid_price > buying_recover_price:
                bid_price = buying_recover_price
                print "Using last_sell_recover_price: ", buying_recover_price
        else:
            bid_price = fixed_price
        eth_to_buy = balance_fiat_available / bid_price
        result = self.create_order(market, eth_to_buy, bid_price, 'buy')
        print 'New order:', market, eth_to_buy, "at", bid_price, 'buy', \
              "({})".format(balance_fiat_available)
        return result

    def reorder(self, order, fixed_price=None):
        if order['type'] == 'buy' and not fixed_price:
            buying_recover_price = self.get_buying_last_sell_recover_price()
            bid_price = self.spread['bid'] + bid_padding
            if bid_price > buying_recover_price:
                print "Buy orden in hold so we don't loose eth against last sell"
                return
        self.cancel_order(order['id'])
        print "Canceled order:", order['id'], order['type'], \
               order['amount']['original'], "at", order['price']
        self.update_spread()
        if order['type'] == 'buy':
            self.create_buy_order(fixed_price=fixed_price)
        else:
            self.create_sell_order(fixed_price=fixed_price)

    def get_USD_convertion_rates(self, to="ARS"):
        to = str.upper(to)
        if self.usd_convertion_rate.has_key(to):
            result = self.usd_convertion_rate.has_key[to]
        else:
            url = currency_rates_api_url.format(to)
            response = requests.get(url).json()
            key = 'USD_' + to
            result = response[key]
        return result

    def get_global_eth_price(self, currency='USD'):
        # Return USD price of ether right now
        url = 'https://min-api.cryptocompare.com/data/price?fsym=ETH&tsyms=USD'
        response = requests.get(url)
        result = float(response.json()['USD'])
        if str.upper(currency) in ['ARS', 'CLP']:
            result *= self.get_USD_convertion_rates(to=str.upper(currency))
        return result

    # def get_USD_ARS_convertion_rate(self):
    #     url = 'http://ws.geeklab.com.ar/dolar/get-dolar-json.php'
    #     response = requests.get(url)
    #     return float(response.json()['libre'])

    def get_ETH_global_hour_ticker(self):
        url = 'https://api.cryptonator.com/api/ticker/eth-usd'
        response = requests.get(url)
        result = None
        while not result:
            try:
                result = response.json()['ticker']
            except ValueError:
                print "Can't access cryptonator api, retrying.."
                time.sleep(1)
        usd_ars_rate = self.get_USD_convertion_rates()['USDARS']
        for key, value in result.items():
            try:
                result[key] = float(value)
            except ValueError:
                pass
        result[u'price_ars'] = float(result['price']) * usd_ars_rate
        return result

    def print_balances(self):
        balances = self.get_balance().data
        balance_fiat = float([b.balance for b in balances if b.wallet == currency][0])
        balance_fiat_available = float([b.available for b in balances if b.wallet == currency][0])
        balance_eth = float([b.balance for b in balances if b.wallet == "ETH"][0])
        balance_eth_available = float([b.available for b in balances if b.wallet == "ETH"][0])
        print "Balances (Available): {}: {} ({}), ETH: {} ({})".format(currency,
            balance_fiat, balance_fiat_available, balance_eth, balance_eth_available)

    def can_buy(self):
        balances = self.get_balance().data
        balance_fiat_available = float([b.available for b in balances if b.wallet == currency][0])
        return buy_minimum < balance_fiat_available

    def is_good_time_to_sell(self):
        recent_sells = self.get_last_trades('sell', hot_minutes)
        return recent_sells >= minimum_sells_in_hot_minutes_to_sell
    # def get_ETH_ARS_global_price(self):
    #     return self.get_global_eth_price() * self.get_USD_ARS_convertion_rate()

client = MyClient(api_key, api_secret)
print 'Welcome to EtherCryptoBot\n'
print 'Market chosen: {}\n'.format(market)
def mainCycle():
    spread = client.get_spread()
    print "Spread:", spread
    ethars_global_price = client.get_global_eth_price(currency=currency)
    client.print_balances()
    # Getting recent trades
    sells = client.get_last_trades('sell', hot_minutes)
    purchases = client.get_last_trades('buy', hot_minutes)
    print 'Activity:'
    print "{} sells made in the last {} minutes".format(sells, hot_minutes)
    print "{} purchases made in the last {} minutes".format(purchases, hot_minutes)

    # Getting open orders
    orders = client.get_active_orders(market).data
    # Printing activity
    print "Global {} price: ${}".format(market, ethars_global_price)
    if not orders:
        if client.can_buy():
            # Purchase ETH
            buy_order = client.create_buy_order()
        else:
            # Sell ETH
            sell_order = client.create_sell_order()
    else:
        for order in orders:
            print "1 active order to {} {} at ${}".format(order['type'], \
                    order['amount']['remaining'], order['price'])

    if spread['relation'] < spread_threshold:
        print "Spread is too low"

    for order in orders:
        order_price = float(order['price'])
        if order['type'] == 'sell':
            if spread['relation'] < spread_threshold:
                # here, order['type'] == 'buy'
                # ticker = client.get_ETH_global_hour_ticker()
                # if ticker['change'] > 1:
                #     continue
                # low_spread_selling_price = client.get_best_selling_price_above_spread_threshold()
                # if float(order['price']) != low_spread_selling_price:
                #     print "Using best_selling_price_above_spread_threshold"
                #     client.reorder(order, low_spread_selling_price)
                client.cancel_order(order['id'])
                print "Canceled order:", order['id'], order['type'], \
                       order['amount']['original'], "at", order['price'], \
                       "due to low spread."
                continue
            # If we are here, spread is wide enough, fun time.
            if order_price > spread['ask']:
                client.reorder(order)  # Try to get first on the line
            else:
                print 'Selling order is first on the line at', order['price']
                book = client.get_book(market, 'sell').data
                second_seller_price = float(book[1]['price'])
                posible_higher_selling_price = second_seller_price - bid_padding
                if posible_higher_selling_price > order_price:
                    # Can sell higher
                    client.reorder(order, posible_higher_selling_price)
        else:
            # here, order['type'] == 'sell'
            if order_price < spread['bid']:
                client.reorder(order)  # Try to get first on the line
            else:
                print 'Buying order is first on the line at', order['price']
                book = client.get_book(market, 'buy').data
                second_buyer_price = float(book[1]['price'])
                posible_cheaper_buyin_price = second_buyer_price + bid_padding
                if posible_cheaper_buyin_price < order_price:
                    print 'But will try to buy cheaper...'
                    client.reorder(order, posible_cheaper_buyin_price)





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
