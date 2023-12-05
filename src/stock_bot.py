import sys
sys.path.append("")
import os 
import yaml
import schedule
import threading
from threading import Thread
import time
import subprocess

import telebot
from telebot import types
from dotenv import load_dotenv
load_dotenv()

# from telegram.ext.filters import Filters 
from Utils.utils import *
from Utils.bot_utils import warning_macd, warningpricevsma, warningsnr, warningbigday, validate_symbol_decorator, run_vscode_tunnel
from src.PayBackTime import PayBackTime, find_PBT_stocks
from src.stock_class import Stock
from src.motif import MotifMatching, find_best_motifs
from src.Indicators import MACD, BigDayWarning, PricevsMA
from src.support_resist import SupportResistFinding
from src.trading_record import BuySellAnalyzer, WinLossAnalyzer, scrape_trading_data, AssetAnalyzer
from src.summarize_text import SpeechSummaryProcessor



data = config_parser(data_config_path = 'config/config.yaml')

user_data_path = data.get('user_data_path', None)
TRADE_USER= os.getenv('TRADE_USER')
TRADE_PASS= os.getenv('TRADE_PASS')
TELEBOT_API= os.getenv('TELEBOT_API')
bot = telebot.TeleBot(TELEBOT_API)


@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Welcome to the Mrzaizai2k Stock Assistant bot! Type /help to see the available commands.")

@bot.message_handler(commands=['help'])
def help(message):
    bot.send_message(message.chat.id, "Available commands:\n/help - Show this help message")
    bot.send_message(message.chat.id, "\n/pbt + symbol: Calculate the payback time for a stock")
    bot.send_message(message.chat.id, "\n/snr + symbol: Find a closest support and resistance for a stock")
    bot.send_message(message.chat.id, "\n/findpbt: find payback time stocks right now")
    bot.send_message(message.chat.id, "\n/findmyfav: find my_param stocks right now")
    bot.send_message(message.chat.id, "\n/risk + symbol: calculate how much stocks u can buy with loss/trade = 6% with max loss/capital = 2%")
    bot.send_message(message.chat.id, "\n/rate + symbol: general rating the stock")
    bot.send_message(message.chat.id, "\n/mulpattern + symbol + date (YYYY-mm-dd): find pattern of the stock on multi-dimension ['close', 'volume']")
    bot.send_message(message.chat.id, "\n/pattern + symbol + date (YYYY-mm-dd): find pattern of the stock ['close']")
    bot.send_message(message.chat.id, "\n/findbestmotif: Find the best motif on all the stocks")
    bot.send_message(message.chat.id, "\n/watchlist: See/change watch list")
    bot.send_message(message.chat.id, "\n/winlossanalyze: Analyze my win loss trading for the last 6 months (FPTS data)")
    bot.send_message(message.chat.id, "\n/buysellanalyze: Picture of my Buy sell for a stock (FPTS data)")
    bot.send_message(message.chat.id, "\n/remote: Open remote tunnel to vscode on mrzaizai2k latop. Can only be used by me!")
    bot.send_message(message.chat.id, "\n Summarize idea from Audio or Voice")


@bot.message_handler(commands=['rate', 'risk', 'pbt','mulpattern', 'pattern','snr','buysellanalyze'])
def ask_for_symbol(message):
    # Ask for the stock symbol
    markup = types.ForceReply(selective = False)
    bot.reply_to(message, "Please enter the stock symbol:", reply_markup = markup)
    if message.text == '/rate':
        bot.register_next_step_handler(message, rate)
    elif message.text == '/risk':
        bot.register_next_step_handler(message, calculate_risk)
    elif message.text == '/pbt':
        bot.register_next_step_handler(message, get_paybacktime)
    elif message.text == '/snr':
        bot.register_next_step_handler(message, get_support_resistance)
    elif message.text == '/buysellanalyze':
        bot.register_next_step_handler(message, get_buysell_analyze)
    else: # message.text in ['/mulpattern', '/pattern']:
        bot.register_next_step_handler(message, ask_pattern_stock, message.text)

@validate_symbol_decorator(bot)
def ask_pattern_stock(message, command):
    symbol = message.text.upper()
    markup = types.ForceReply(selective = False)
    bot.reply_to(message, "Please enter the start_date (YYYY-mm-dd):", reply_markup = markup)

    if command == '/mulpattern':
        bot.register_next_step_handler(message, find_similar_pattern_multi_dimension, symbol)
    else: # command == '/pattern':
        bot.register_next_step_handler(message, find_similar_pattern, symbol)


def find_similar_pattern(message, symbol):

    start_date = message.text # %Y-%m-%d
    bot.send_message(message.chat.id, "Please wait. This process can takes several minutes")

    motif_matching = MotifMatching(symbol=symbol, start_date=start_date)
    pattern_start_date, pattern_end_date, distance = motif_matching.find_similar_subseries_with_date()

    report = ""
    report += f"The similar pattern for {symbol} from {start_date} to current day\n"
    report += f"- Indices: from {pattern_start_date} to {pattern_end_date} (Window_size m = {motif_matching.m})\n"
    report += f"- Distance: {distance:.2f}\n"
    # Send the report to the user
    bot.send_message(message.chat.id, report)

def find_similar_pattern_multi_dimension(message, symbol):

    start_date = message.text # %Y-%m-%d
    bot.send_message(message.chat.id, "Please wait. This process can takes several minutes")

    motif_matching = MotifMatching(symbol=symbol, start_date=start_date)
    ticker, result = motif_matching.find_matching_series_multi_dim_with_date()
    pattern_start_date = motif_matching.dataframe.iloc[int(result[0])].time.strftime('%Y-%m-%d')
    pattern_end_date= motif_matching.dataframe.iloc[int(result[0]) + motif_matching.m].time.strftime('%Y-%m-%d')
    distance = result[2]

    report = ""
    report += f"The similar pattern for {ticker} from {start_date} to current day in multi dimension ['close','volume']\n"
    report += f"- Indices: from {pattern_start_date} to {pattern_end_date} (Window_size m = {motif_matching.m})\n"
    report += f"- Distance: {distance:.2f}\n"
    # Send the report to the user
    bot.send_message(message.chat.id, report)

@validate_symbol_decorator(bot)
def get_paybacktime(message):
    pbt_params = data.get('pbt_params')
    # Get the symbol from the user's message
    symbol = message.text.upper()
    bot.send_message(message.chat.id, "Please wait. This process can takes several minutes")
    # Create the PayBackTime object and get the report
    pbt_generator = PayBackTime(symbol=symbol, report_range=pbt_params[0], window_size = pbt_params[1])
    report = pbt_generator.get_report()
    
    # Send the report to the user
    bot.send_message(message.chat.id, report)

@validate_symbol_decorator(bot)
def get_buysell_analyze(message):
    symbol = message.text.upper()
    
    buy_sell_df_path = data.get('buy_sell_df_path', None)
    buysell_analyzer = BuySellAnalyzer(buy_sell_df_path=buy_sell_df_path)
    image_path = buysell_analyzer.plot_and_save_buy_sell_of_stock(symbol=symbol)

    # Send the image
    with open(image_path, 'rb') as photo:
        bot.send_photo(message.chat.id, photo)

    bot.send_message(message.chat.id, f'This is your Buy/Sell for stock {symbol}')
    os.remove(image_path)

@validate_symbol_decorator(bot)
def get_support_resistance(message):
    # Get the symbol from the user's message
    symbol = message.text.upper()
  
    # Create the PayBackTime object and get the report
    sr_finding = SupportResistFinding(symbol=symbol)
    result = sr_finding.find_closest_support_resist(current_price=sr_finding.get_current_price())
    report = f'The current price for {symbol} is {sr_finding.get_current_price()}\n'
    report += f'- The closest support is {result[0]}\n'
    report += f'- The closest resistance is {result[1]}\n'
    # Send the report to the user
    bot.send_message(message.chat.id, report)

@validate_symbol_decorator(bot)
def calculate_risk(message):
    symbol = message.text.upper()

    stock_generator = Stock(symbol=symbol)
    stock_price = stock_generator.get_current_price()

    asset_data_path = data.get('asset_data_path')
    data_frame_reader = AssetAnalyzer(file_path=asset_data_path)
    capital_value = data_frame_reader.read_capital_value()

    num_stocks = calculate_stocks_to_buy(stock_price, capital = capital_value)
    mess = ""
    mess += f"You can buy {num_stocks} stocks at the price of {stock_price} each\n"
    mess += f"Your Captial: {capital_value/1_000_000:.2f} (triệu VND)\n"
    mess += f'Total price: {stock_price*num_stocks/1_000_000:.2f} (triệu VND)\n'
    mess += f'The fee is: 0.188% -> {((0.188/100) * stock_price*num_stocks)/1_000} (nghìn VND)\n'
    bot.send_message(message.chat.id, mess)

@validate_symbol_decorator(bot)
def rate(message):
    symbol = message.text.upper()
    if len(symbol) > 3: # Its not for Index
        bot.send_message(message.chat.id, 'This function can just be used for stocks, not index')
        return
    
    rating = general_rating(symbol)
    report = f"The general rating for {symbol}:\n"
    report += "\n".join([f"{col}: {rating[col].values[0]}" for col in rating.columns])

    # Send the report to the user
    bot.send_message(message.chat.id, report)

@bot.message_handler(commands=['findpbt'])
def findpbt(message):
    bot.send_message(message.chat.id, "Please wait. This process can takes several minutes")
    pass_ticker = find_PBT_stocks(file_path="memory/paybacktime.csv")
    pass_ticker_string = ", ".join(pass_ticker)
    print('pass_ticker_string',pass_ticker_string)

    # Send the report to the user
    bot.send_message(message.chat.id, f"The Paybacktime stocks are {pass_ticker_string}")

@bot.message_handler(commands=['findmyfav'])
def findmyfav(message):
    my_params = {
        "exchangeName": "HOSE,HNX",
        "marketCap": (1_000, 200_000),
        "roe": (10, 100),  # Minimum Return on Equity (ROE)
        'pe': (10,20),
        'priceNearRealtime': (10,100),
        # "avgTradingValue20Day": (100, 1000),  # Minimum 20-day average trading value
    #     'uptrend': 'buy-signal',
        'macdHistogram': 'macdHistLT0Increase',
        'strongBuyPercentage': (20,100),
        'relativeStrength3Day': (50,100),
    }
    
    pass_ticker = filter_stocks(param=my_params)
    pass_ticker_string = ", ".join(pass_ticker.ticker.unique())

    # Send the report to the user
    bot.send_message(message.chat.id, f"The stocks most suitable for u are: {pass_ticker_string}")


@bot.message_handler(commands=['findbestmotif'])
def findpbt(message):
    bot.send_message(message.chat.id, "Please wait. This process can takes several minutes")
    result_dict = find_best_motifs()
    report = ""
    for stock, values in result_dict.items():
        start_date, end_date, distance = values
        report += f"Stock: {stock}\n"
        report += f"- Date: {start_date} to {end_date}\n"
        report += f"- Distance: {distance:.3f}\n\n"
    # Send the report to the user
    bot.send_message(message.chat.id, report)

@bot.message_handler(commands=['winlossanalyze'])
def analyze_winloss(message):
    win_loss_df_path = data.get('win_loss_df_path', None)
    winloss_analyzer = WinLossAnalyzer(win_loss_df_path=win_loss_df_path)
    report = winloss_analyzer.get_report()
    bot.send_message(message.chat.id, report)


@bot.message_handler(commands=['watchlist'])
def handle_watchlist(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    watch_button = types.KeyboardButton('Watch')
    add_button = types.KeyboardButton('Add')
    remove_button = types.KeyboardButton('Remove')
    markup.add(watch_button, add_button, remove_button)

    bot.send_message(message.chat.id, "Choose an action:", reply_markup=markup)
    bot.register_next_step_handler(message, process_button_click)

def process_button_click(message):
    user_action = message.text.lower()

    if user_action == 'watch':
        user_db= UserDatabase(user_data_path=user_data_path)
        watchlist = user_db.get_watch_list(user_id=message.chat.id)
        bot.send_message(message.chat.id, f"Your watchlist: {watchlist}")
    elif user_action == 'add':
        bot.send_message(message.chat.id, "Enter the stock name to add:\n VD: VIX")
        bot.register_next_step_handler(message, process_add_stock)
    elif user_action == 'remove':
        bot.send_message(message.chat.id, "Enter the stock name to remove:\n VD: VIX")
        bot.register_next_step_handler(message, process_remove_stock)
    else:
        bot.send_message(message.chat.id, "Invalid option. Please choose a valid action.")

@validate_symbol_decorator(bot)
def process_add_stock(message):
    symbol = message.text.upper()
    user_db= UserDatabase(user_data_path=user_data_path)    
    watchlist = user_db.get_watch_list(user_id=message.chat.id)
    watchlist.append(symbol)
    user_db.save_watch_list(user_id=message.chat.id, watch_list=watchlist)
    bot.send_message(message.chat.id, f"{symbol} added to your watchlist. Updated watchlist: {watchlist}")

@validate_symbol_decorator(bot)
def process_remove_stock(message):
    symbol = message.text.upper()

    user_db= UserDatabase(user_data_path=user_data_path)
    watchlist = user_db.get_watch_list(user_id=message.chat.id)

    if symbol in watchlist:
        watchlist.remove(symbol)
        user_db.save_watch_list(user_id=message.chat.id, watch_list=watchlist)
        bot.send_message(message.chat.id, f"{symbol} removed from your watchlist. Updated watchlist: {watchlist}")
    else:
        bot.send_message(message.chat.id, f"{symbol} not found in your watchlist.")


@bot.message_handler(commands=['remote'])
def open_vscode_tunnel(message):
    if not validate_mrzaizai2k_user(message.chat.id):
        bot.send_message(message.chat.id, f"This command can just be used by the owner (mrzaizai2k).\nIf you want to use this, close the git repo and modify the code")
        return
    bot.reply_to(message, f"VS Code remote tunnel Opening...")
    Thread(target=run_vscode_tunnel, args=(bot, message)).start()


def warning_stock():
    times = data.get('times', []) 
    functions = [warning_macd, warningpricevsma, warningsnr, warningbigday]
    user_db = UserDatabase(user_data_path=user_data_path)
    user_list = user_db.get_users_for_warning()

    # Schedule the jobs for each day and time
    for time_str in times:
        for func in functions:
            for user in user_list:
                watchlist = user_db.get_watch_list(user_id=user)
                if func in [warningsnr, warningpricevsma]:
                    schedule.every().day.at(f"{time_str}").do(func, bot=bot , watchlist=watchlist, user_id=user, data_config = data)
                else:
                    schedule.every().day.at(f"{time_str}").do(func, bot=bot , watchlist=watchlist, user_id=user)

@bot.message_handler(content_types=['audio','voice'])
def summarize_sound(message):
    bot.send_message(message.chat.id, "Proccessing...")
    file_id = message.audio.file_id if message.content_type == 'audio' else message.voice.file_id

    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    file_path = f'data/{file_id}.mp3'

    with open(file_path, 'wb') as new_file:
        new_file.write(downloaded_file)

    speech_to_text = SpeechSummaryProcessor(audio_path=file_path)
    text = speech_to_text.generate_speech_to_text()
    text = f"Here's your note:\n {text}"
    bot.reply_to(message, text)
    os.remove(file_path)


# Define the function to handle all other messages
@bot.message_handler(func=lambda message: True)
def echo(message):
    response_message = "Apologies, I didn't understand that command. 😕\nPlease type /help to see the list of available commands."
    bot.send_message(message.chat.id, response_message)

def main():

    warning_stock()
    schedule.every().day.at(data.get('scape_trading_data_time')).do(scrape_trading_data, user_name = TRADE_USER, password = TRADE_PASS)
    Thread(target=schedule_checker).start() 


    while True:
        try:
            bot.infinity_polling()
            
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            print("Resetting the bot in 3 seconds...")
            time.sleep(3)  # Pause for 3 seconds before restarting
            main()  # Restart the main function
        
        finally:
            # Clear scheduled jobs to avoid duplication on restart
            schedule.clear()

if __name__ == "__main__":
    main()
