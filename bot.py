import logging
from telegram.ext import Updater, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from shopgun import Session
from config import TELEGRAM_TOKEN, DEFAULT_LOCATION, DEFAULT_RADIUS
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOGGER = logging.getLogger('gnier')

CHATS = {}


class Subscription:

    def __init__(self, context, query, price=None, radius=None):
        self.query = query
        self.price = price
        self.radius = DEFAULT_RADIUS
        self.lat, self.lon = DEFAULT_LOCATION
        self.offers = []

    def update(self):
        session = Session()
        found = {offer.ident: False for offer in self.offers}
        remove = []

        # get new offers
        for offer in session.search(self.query, self.lat, self.lon, self.radius):
            if offer.ident in found:
                found[offer.ident] = True
                continue
            if self.price is None or offer.pricing['price'] <= self.price:
                self.offers.append(offer)
                yield (f'I {offer.store} kan du købe "{offer.heading}" til '
                       f'{offer.pricing["price"]} kr!')

        # handle existing offers
        for offer in self.offers:
            timeleft = offer.run_till - datetime.now(offer.run_till.tzinfo)
            if timeleft.days < 0:
                remove.append(offer)
                yield f'Tilbuddet "{offer.heading}" i {offer.store} er udløbet.'
            elif timeleft.days < 3:
                yield (f'Tilbuddet "{offer.heading}" i {offer.store} til '
                       f'{offer.pricing["price"]} kr udløber om kort tid: '
                       f'{offer.run_till}.')

        for offer in remove:
            self.offers.remove(offer)


class Chat:

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.subs = []
        self.job = None

    def schedule(self, context, interval, first=None):
        if self.job is not None:
            self.job.schedule_removal()
        self.job = context.job_queue.run_repeating(
            self.update, interval, interval if first is None else first)

    def update_sub(self, context, sub):
        for message in sub.update():
            context.bot.send_message(self.chat_id, text=message)

    def update(self, context):
        LOGGER.log(logging.DEBUG, f'Running update for chat {self.chat_id}')
        for sub in self.subs:
            self.update_sub(context, sub)


def start(update, context):
    lines = ('Vær hilset!!',
             'En krone sparet er en krone tjent. Og nu skal der tjenes!',
             '',
             'Med min viden, og din sparsommelighed kan vi sammen gøre store '
             'ting. Jeg forstår følgende kommandoer der kan hjælpe dig: '
             '',
             '/tilmeld - tilmeld dig meddelelser om tilbud',
             '/afmeld - afmeld meddelelserne igen',
             '/liste - få en liste over dine tilmeldinger'
             )
    update.message.reply_text('\n'.join(lines))


QUERY, PRICING, UNSUB = range(3)


def subscribe_entry(update, context):
    update.message.reply_text(
        f'Hvad vil du gerne tilmelde dig notifikationer omkring?')
    return QUERY


def subscribe_query(update, context):
    user_data = context.user_data
    query = update.message.text
    user_data['query'] = query
    update.message.reply_text('Og til hvilken pris, maksimalt?')
    return PRICING


def subscribe_pricing(update, context):
    chat_id = update.message.chat_id
    user_data = context.user_data
    query = user_data['query']
    pricing = float(update.message.text)

    sub = Subscription(context, query, pricing, 1000)
    if chat_id not in CHATS:
        CHATS[chat_id] = Chat(chat_id)
        CHATS[chat_id].schedule(context, timedelta(6))

    CHATS[chat_id].subs.append(sub)
    CHATS[chat_id].update_sub(context, sub)

    update.message.reply_text(
        f'Glæd dig til at høre, når {query} er billigere end {pricing} kr!')
    return ConversationHandler.END


def unsubscribe_choice(update, context):
    chat_id = update.message.chat_id
    if chat_id not in CHATS or not CHATS[chat_id].subs:
        update.message.reply_text(
            f'Det kunne være du skulle tilmelde dig noget først, ikke?')
        return
    chat = CHATS[chat_id]

    keyboard = [[InlineKeyboardButton('Annuller', callback_data='annuller')]]
    keyboard += [[InlineKeyboardButton(f'"{sub.query}"', callback_data=str(i))]
                 for i, sub in enumerate(chat.subs)]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        'Hvilken søgning vil du afmelde?', reply_markup=markup)
    return UNSUB


def unsubscribe(update, context):
    query = update.callback_query
    if query.data == 'annuller':
        query.edit_message_text(
            text=f'Du beholder dine tilmeldinger denne gang.')
        return ConversationHandler.END

    chat_id = query.message.chat_id
    chat = CHATS[chat_id]

    sub_idx = int(query.data)
    sub = chat.subs[sub_idx]

    query.edit_message_text(
        text=f'Du vil ikke høre mere om {sub.query}.')

    chat.subs.remove(sub)
    return ConversationHandler.END


def list_subs(update, context):
    chat_id = update.message.chat_id
    if chat_id not in CHATS or not CHATS[chat_id].subs:
        update.message.reply_text(
            f'Det kunne være du skulle tilmelde dig noget først, ikke?')
    else:
        messages = []
        messages.append(f'Du er tilmeldt følgende søgninger:')
        for i, sub in enumerate(CHATS[chat_id].subs):
            messages.append(f'{i+1}. {sub.query}')
        update.message.reply_text('\n'.join(messages))


def main():
    """Run bot."""
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    disp = updater.dispatcher
    disp.add_handler(CommandHandler("start", start))

    sub_convo = ConversationHandler(
        entry_points=[CommandHandler("tilmeld", subscribe_entry)],
        states={
            QUERY: [MessageHandler(Filters.text, subscribe_query)],
            PRICING: [MessageHandler(Filters.regex(
                r'^[0-9]+$'), subscribe_pricing)]
        },
        fallbacks=[]
    )
    unsub_convo = ConversationHandler(
        entry_points=[CommandHandler("afmeld", unsubscribe_choice)],
        states={
            UNSUB: [CallbackQueryHandler(unsubscribe)],
        },
        fallbacks=[]
    )
    disp.add_handler(sub_convo)
    disp.add_handler(unsub_convo)
    disp.add_handler(CommandHandler("liste", list_subs))

    updater.start_polling()


if __name__ == "__main__":
    main()
