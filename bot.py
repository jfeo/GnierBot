"""A telegram bot"""

import logging

from telegram.ext import Updater, ConversationHandler, CommandHandler
from telegram.ext import MessageHandler, CallbackQueryHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from shopgun import Session
from cart import Cart, Subscription
from config import TELEGRAM_TOKEN, DEFAULT_LOCATION, DEFAULT_RADIUS

from datetime import timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger('gnier')

CHATS = {}


def offer_text(offer):
    """Standard text for an offer."""
    icon = '💰'
    if offer.expiring():
        icon = '⌛'
    if offer.expired():
        icon = '☠️'

    return (f'{icon} {offer.store} tilbyder "{offer.heading}" til '
            f'{offer.price} kr.')


def offer_text_expired(offer):
    """Text for an expired offer."""
    return f'❌ Tilbuddet "{offer.heading}" i {offer.store} er udløbet.'


def offer_text_expiring(offer):
    """Text for an expiring offer."""
    return (f'⚠ {offer.store}s tilbud om️ "{offer.heading}" til '
            f'{offer.price} kr. udløber '
            f'{human_timedelta(offer.timeleft())}.')


def human_timedelta(delta):
    """Return a string representing the time delta in a (danish) human readable
    format.
    """
    seconds = delta.seconds % 60 if delta.seconds else 0
    minutes = delta.seconds // 60 % 60 if delta.seconds else 0
    hours = delta.seconds // 3600 % 24 if delta.seconds else 0
    days = abs(delta.days) % 7 if delta.days else 0
    weeks = abs(delta.days) // 7 if delta.days else 0
    parts = []

    if weeks > 0:
        parts.append(f'{weeks} uger')
    if days > 0:
        parts.append(f'{days} dage')
    if hours > 0:
        parts.append(f'{hours} timer')
    if minutes > 0:
        parts.append(f'{minutes} minutter')
    if seconds > 0:
        parts.append(f'{seconds} sekunder')

    sentence = None
    if len(parts) == 1:
        (sentence) = parts
    else:
        last = parts.pop()
        sentence = f'{", ".join(parts)}, og {last}'

    if delta.days < 0:
        return f'for {sentence} siden'

    return f'om {sentence}'


class Chat:
    """User data, subscription storage, and update scheduling."""

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.job = None
        self.cart = Cart()
        self.radius = DEFAULT_RADIUS
        self.lat, self.lon = DEFAULT_LOCATION

    @staticmethod
    def get(chat_id):
        """Get existing or created chat."""
        if chat_id not in CHATS:
            CHATS[chat_id] = Chat(chat_id)
        return CHATS[chat_id]

    def schedule(self, context, interval, first=None):
        """Schedule a chat to update at a given interval."""
        if self.job is not None:
            self.job.schedule_removal()
        self.job = context.job_queue.run_repeating(
            self.update, interval, interval if first is None else first)

    def add_subscription(self, query, price):
        """Add a new subscription."""
        session = Session()
        sub = self.cart.add_subscription(query, price)
        offers = session.search(query, price, self.lat, self.lon)
        sub.handle_offers(offers)
        sub.check_offers()

    def update(self, context):
        """Check each subscription for updates."""
        session = Session()
        for sub in self.cart:
            offers = list(session.search(
                sub.query, sub.price, self.lat, self.lon))
            for offer in sub.handle_offers(offers):
                context.bot.send_message(
                    self.chat_id,
                    text=offer_text(offer)
                )
            updates = sub.check_offers()
            for offer in updates['expired']:
                context.bot.send_message(
                    self.chat_id,
                    text=offer_text_expired(offer))
            for offer in updates['expiring']:
                context.bot_send_message(
                    self.chat_id,
                    text=offer_text_expiring(offer)
                )


# Conversation state identifies for search conversation
SEARCH_ASK_QUERY, SEARCH_ASK_PRICE, SEARCH_SHOW_RESULT = range(3)
SEARCH_DONE, SEARCH_COMMAND, SEARCH_REMOVE = range(3, 6)

# Conversation state identifiers for settings conversation
SETTINGS_VIEW_SAVE, SETTINGS_ASK, SETTINGS_DONE = range(3)


def start(update, context):
    """Start command."""
    lines = (
        'Vær hilset!',
        'En krone sparet er en krone tjent. Og nu skal der tjenes!',
        '',
        'Med mine evner, og din sparsommelighed kan vi sammen gøre store '
        'ting. Jeg forstår følgende kommandoer der kan hjælpe dig: '
        '',
        ' 🌟 /ny - lav en ny søgning',
        ' 🗑 /slet - slet en af dine søgninger',
        ' 📃 /liste - få en liste over dine søgninger',
        ' 💰 /tilbud - få en liste over dine tilbud',
        ' ✍️ /indstil- for at ændre placering eller radius på søgninger'
    )
    update.message.reply_text('\n'.join(lines))

    # initialize user data
    chat = Chat.get(update.message.chat_id)
    chat.schedule(context, timedelta(hours=6))


def search_convo_entry(update, context):
    """Entry into the search conversation."""
    keyboard = [[
        InlineKeyboardButton(text='🌟 Ny søgning', callback_data='new'),
        InlineKeyboardButton(text='📃 Vis søgninger', callback_data='list'),
        InlineKeyboardButton(text='🗑️ Slet søgning', callback_data='remove')
    ]]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Hvad vil du?', reply_markup=markup)
    return SEARCH_COMMAND


def search_convo_ask_query(update, context):
    """Ask for a search query."""
    if update.callback_query:
        query = update.callback_query
        bot = context.bot
        bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text='❓ Hvad vil du søge efter?'
        )
    else:
        update.message.reply_text('❓ Hvad vil du søge efter?')
    return SEARCH_ASK_PRICE


def search_convo_ask_price(update, context):
    """Handle search query, and ask for price."""
    user_data = context.user_data
    query = update.message.text
    user_data['query'] = query
    update.message.reply_text(
        f'Ja, {query} er også godt. Og til hvilken pris (i kr.)?')
    return SEARCH_SHOW_RESULT


def search_convo_show_result(update, context):
    """Handle price, perform query, and show result,
    and ask if the user wants to save it."""
    chat = Chat.get(update.message.chat_id)
    user_data = context.user_data
    query = user_data['query']
    price = float(update.message.text)
    user_data['price'] = price

    ses = Session()
    offers = ses.search_all(query, chat.lat, chat.lon, chat.radius)
    too_expensive = 0
    total_offers = 0
    for offer in offers:
        total_offers += 1
        if offer.price > price:
            too_expensive += 1
            continue

        update.message.reply_text(offer_text(offer))

    if total_offers == 0:
        update.message.reply_text(
            f'Der blev ikke fundet nogen tilbud lige nu.')
    if too_expensive > 0:
        update.message.reply_text(f'{too_expensive} tilbud blev frasorteret, '
                                  'fordi de var for dyre.')

    keyboard = [[
        InlineKeyboardButton(text='💾 Gem søgning', callback_data='save'),
        InlineKeyboardButton(text='🌟 Ny søgning', callback_data='new'),
        InlineKeyboardButton(text='🚪️ Færdig', callback_data='done')
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text(
        '❓ Vil du gemme søgningen?', reply_markup=markup
    )

    return SEARCH_DONE


def search_convo_save(update, context):
    """Save the created search."""
    query = update.callback_query
    chat = Chat.get(query.message.chat_id)
    bot = context.bot
    user_data = context.user_data

    bot.edit_message_text(
        chat_id=chat.chat_id,
        message_id=query.message.message_id,
        text='👋 Den er i vinkel, du!'
    )

    chat.add_subscription(user_data['query'], user_data['price'])

    return ConversationHandler.END


def search_convo_done(update, context):
    """End search conversation."""
    query = update.callback_query
    bot = context.bot
    bot.edit_message_text(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text='️👋 Det er godt du, hej!'
    )
    return ConversationHandler.END


def search_convo_list(update, context):
    """List all saved searches."""
    if update.callback_query:
        query = update.callback_query
        chat = Chat.get(query.message.chat_id)
        bot = context.bot
    else:
        chat = Chat.get(update.message.chat_id)

    if not chat.subs:
        text = '⁉️ Du har ingen gemte søgninger.'
    else:
        text = '\n'.join([f'{i}. {sub.query}' for i,
                          sub in enumerate(chat.subs, start=1)])
        text = f'Her er dine søgninger:\n{text}'

    if update.callback_query:
        bot.edit_message_text(
            chat_id=chat.chat_id,
            message_id=query.message.message_id,
            text=text
        )
    else:
        update.message.reply_text(text)

    return ConversationHandler.END


def search_convo_ask_remove(update, context):
    """Ask which search to remove."""
    if update.callback_query:
        query = update.callback_query
        bot = context.bot
        chat = Chat.get(query.message.chat_id)
    else:
        chat = Chat.get(update.message.chat_id)

    # No subscriptions
    if not chat.subs:
        text = '⁉️ Du har ingen søgninger at slette.'
        if update.callback_query:
            bot.edit_message_text(
                text, chat_id=chat.chat_id,
                message_id=query.message.message_id
            )
        else:
            update.message.reply_text(text)
        return ConversationHandler.END

    # Generate keyboard
    keyboard = [[InlineKeyboardButton(sub.query, callback_data=str(i))]
                for i, sub in enumerate(chat.subs)]
    keyboard.append([InlineKeyboardButton(
        text='Annuller', callback_data='cancel')])
    markup = InlineKeyboardMarkup(keyboard)

    # Reply
    text = 'Hvilken søgning vil du fjerne?'
    if update.callback_query:
        bot.edit_message_text(
            text, chat_id=chat.chat_id,
            message_id=query.message.message_id,
            reply_markup=markup
        )
    else:
        update.message.reply_text(text, reply_markup=markup)

    return SEARCH_REMOVE


def search_convo_remove(update, context):
    """Remove the selected"""
    query = update.callback_query
    bot = context.bot
    chat = Chat.get(query.message.chat_id)
    sub_index = int(query.data)
    removed_query = chat.subs[sub_index].query
    del chat.subs[sub_index]

    bot.edit_message_text(
        text=f'🗑️ Søgningen efter "{removed_query}" er fjernet.',
        chat_id=chat.chat_id,
        message_id=query.message.message_id
    )

    return ConversationHandler.END


def offers_list(update, context):
    """Show the currently found offers."""
    chat = Chat.get(update.message.chat_id)

    if not chat.subs:
        text = 'ℹ️ Du får ingen tilbud, hvis du ikke har nogen søgninger.'
        update.message.reply_text(text)

    for sub in chat.subs:
        if not sub.offers:
            text = f'ℹ️ Søgningen efter "{sub.query}" har ingen tilbud.'
            update.message.reply_text(text)
            continue

        lines = [
            f'ℹ️ Søgningen efter "{sub.query}" har {len(sub.offers)} tilbud:',
            ''
        ]
        for offer in sub.offers:
            print(offer, offer.timeleft(), offer.run_till)
            lines.append(f' 💰 {offer.heading} til {offer.price} kr. '
                         f'(udløber {human_timedelta(offer.timeleft())})')

        update.message.reply_text('\n'.join(lines))


def settings_convo_view_save(update, context):
    """Save location setting."""
    chat = Chat.get(update.message.chat_id)
    if update.message.location:
        user_location = update.message.location
        chat.lon = user_location.longitude
        chat.lan = user_location.latitude

    if update.message.text.isdigit():
        chat.radius = int(update.message.text)
    else:
        try:
            lat, lon = update.message.text.split(',')
            lat = float(lat)
            lon = float(lon)
            if 90 <= lat <= 90 and -180 <= lon <= 180:
                chat.lat = lat
                chat.lon = lon
        except ValueError:
            pass

    keyboard = [[
        InlineKeyboardButton('Opdater radius', callback_data='radius'),
        InlineKeyboardButton('Opdater lokation', callback_data='location'),
        InlineKeyboardButton('Færdig', callback_data='done')
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text('\n'.join([
        f'Dine indstillinger er:',
        '',
        f'🌍 {chat.lat}, {chat.lon}',
        f'⭕ {chat.radius}'
    ]), reply_markup=markup)

    return SETTINGS_ASK


def settings_convo_ask_location(update, context):
    """Ask user for location."""
    query = update.callback_query
    bot = context.bot

    bot.edit_message_text(
        text=f'Hvilken placering vil du søge ud fra?',
        chat_id=query.message.chat_id,
        message_id=query.message.message_id
    )

    return SETTINGS_VIEW_SAVE


def settings_convo_ask_radius(update, context):
    """Ask user for radius"""
    query = update.callback_query
    bot = context.bot

    bot.edit_message_text(
        text=f'Hvilken radius vil du søge indenfor (i meter)?',
        chat_id=query.message.chat_id,
        message_id=query.message.message_id
    )

    return SETTINGS_VIEW_SAVE


def settings_convo_done(update, context):
    """End settings conversation."""
    query = update.callback_query
    bot = context.bot

    bot.edit_message_text(
        text='Godt, godt.',
        chat_id=query.message.chat_id,
        message_id=query.message.message_id
    )

    return ConversationHandler.END


def main():
    """Run bot."""
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    disp = updater.dispatcher
    disp.add_handler(CommandHandler("start", start))
    disp.add_handler(CommandHandler("help", start))

    # conversation for changing user settings
    settings_convo = ConversationHandler(
        entry_points=[
            CommandHandler('indstil', settings_convo_view_save)
        ],

        states={
            SETTINGS_VIEW_SAVE: [
                MessageHandler(Filters.location, settings_convo_view_save),
                MessageHandler(Filters.regex(
                    r'^[0-9]+$'), settings_convo_view_save),
            ],
            SETTINGS_ASK: [
                CallbackQueryHandler(
                    settings_convo_ask_location, pattern=r'^location$'
                ),
                CallbackQueryHandler(
                    settings_convo_ask_radius, pattern=r'radius'
                ),
                CallbackQueryHandler(
                    settings_convo_done, pattern=r'done'
                )
            ],
            SETTINGS_DONE: [
                MessageHandler(Filters.text, settings_convo_done)
            ]
        },

        fallbacks=[
            MessageHandler(Filters.text, settings_convo_done)
        ]
    )
    disp.add_handler(settings_convo)

    disp.add_handler(CommandHandler('tilbud', offers_list))

    # conversation for searching and adding subscriptions
    search_convo = ConversationHandler(
        entry_points=[
            CommandHandler('menu', search_convo_entry),
            CommandHandler('ny', search_convo_ask_query),
            CommandHandler('slet', search_convo_ask_remove),
            CommandHandler('liste', search_convo_list)
        ],

        states={
            SEARCH_COMMAND: [
                CallbackQueryHandler(search_convo_ask_query, pattern=r'^new$'),
                CallbackQueryHandler(
                    search_convo_ask_remove, pattern=r'^remove$'),
                CallbackQueryHandler(search_convo_list, pattern=r'^list$')
            ],
            SEARCH_ASK_QUERY: [
                MessageHandler(Filters.text, search_convo_ask_query)
            ],
            SEARCH_ASK_PRICE: [
                MessageHandler(Filters.text, search_convo_ask_price)
            ],
            SEARCH_SHOW_RESULT: [
                MessageHandler(Filters.regex(
                    r'^[0-9]+(,|\.)?[0-9]*'), search_convo_show_result)
            ],
            SEARCH_DONE: [
                CallbackQueryHandler(search_convo_ask_query, pattern=r'^new$'),
                CallbackQueryHandler(search_convo_done, pattern=r'^done$'),
                CallbackQueryHandler(search_convo_save, pattern='^save$')
            ],
            SEARCH_REMOVE: [
                CallbackQueryHandler(search_convo_remove),
                CallbackQueryHandler(search_convo_done, pattern='^ cancel$')
            ]
        },

        fallbacks=[]
    )
    disp.add_handler(search_convo)

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == "__main__":
    main()
