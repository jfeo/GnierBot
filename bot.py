"""A telegram bot"""

import logging

from telegram.ext import Updater, ConversationHandler, CommandHandler
from telegram.ext import MessageHandler, CallbackQueryHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from shopgun import Session
from config import TELEGRAM_TOKEN, DEFAULT_LOCATION, DEFAULT_RADIUS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger('gnier')

CHATS = {}


def human_timedelta(timedelta):
    """Return a string representing the time delta in a (danish) human readable
    format.
    """
    seconds = timedelta.seconds % 60 if timedelta.seconds else 0
    minutes = timedelta.seconds // 60 % 60 if timedelta.seconds else 0
    hours = timedelta.seconds // 3600 % 24 if timedelta.seconds else 0
    days = abs(timedelta.days) % 7 if timedelta.days else 0
    weeks = abs(timedelta.days) // 7 if timedelta.days else 0
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

    if timedelta.days < 0:
        return f'for {sentence} siden'

    return f'om {sentence}'


class Subscription:
    """Stores a search that is subscribed."""

    def __init__(self, query, price):
        self.query = query
        self.price = price
        self.offers = []

    def update(self, chat, func_new=None, func_expired=None,
               func_expiring=None):
        """Perform an update."""
        session = Session()
        found = {offer.ident: False for offer in self.offers}
        remove = []

        # get new offers
        for offer in session.search(self.query, chat.lat, chat.lon, chat.radius):
            if offer.ident in found:
                found[offer.ident] = True
                continue
            if offer.price <= self.price:
                self.offers.append(offer)
                if func_new:
                    func_new(offer)

        # handle existing offers
        for offer in self.offers:
            if offer.expired():
                remove.append(offer)
                if func_expired:
                    func_expired(offer)
            elif offer.expiring():
                if func_expiring:
                    func_expiring(offer)

        for offer in remove:
            self.offers.remove(offer)


class Chat:
    """User data, subscription storage, and update scheduling."""

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.subs = []
        self.job = None
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

    def update(self, context):
        """Check each subscription for updates."""
        def expiring(offer):
            msg = (f'⚠ {offer.store}s tilbud om️ "{offer.heading}" til '
                   f'{offer.price} kr. udløber '
                   f'{human_timedelta(offer.timeleft())}.')
            context.bot.send_message(self.chat_id, text=msg)

        def expired(offer):
            msg = f'❌ Tilbuddet "{offer.heading}" i {offer.store} er udløbet.'
            context.bot.send_message(self.chat_id, text=msg)

        def new(offer):
            msg = (f'💰 {offer.store} tilbyder "{offer.heading}" til '
                   f'{offer.price} kr.')
            context.bot.send_message(self.chat_id, text=msg)

        for sub in self.subs:
            sub.update(self, func_new=new, func_expired=expired,
                       func_expiring=expiring)

        CommandHandler('indstil', 'settings_convo_entry')


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
        ' ℹ /menu - en menu med muligheder',
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

        icon = '💰'
        if offer.expiring():
            icon = '⌛'
        if offer.expired():
            icon = '☠️'

        update.message.reply_text(
            f'{icon} {offer.heading} i {offer.store} til {offer.price} kr. '
            f'(udløber {human_timedelta(offer.timeleft())})'
        )

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

    sub = Subscription(user_data['query'], user_data['price'])
    sub.update(chat)
    chat.subs.append(sub)

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

    if update.message.text:
        try:
            chat.radius = int(update.message.text)
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
