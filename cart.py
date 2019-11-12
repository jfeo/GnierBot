"""Functionality for keeping track of subscriptions offer searches, keeping
check of expiration, and new offers."""


class Cart:
    """A cart is a collection of subscriptions."""

    def __init__(self):
        self.subscriptions = list()

    def add_subscription(self, query, price):
        """Add a subscription to the cart."""
        sub = Subscription(query, price)
        self.subscriptions.append(sub)
        return sub

    def remove_subscription(self, subscription):
        """Remove a subscription from the cart."""
        self.subscriptions.remove(subscription)

    def __iter__(self):
        """Get an iterator for the subscriptions in the cart."""
        return iter(self.subscriptions)


class Subscription:
    """Stores a search that is subscribed."""

    def __init__(self, query, price):
        self.query = query
        self.price = price
        self.offers = []
        self.warned = set()

    def handle_offers(self, offers):
        """Perform an update."""
        found = {offer.ident: False for offer in self.offers}

        # get new offers
        for offer in offers:
            if offer.offer_id in found:
                continue
            if offer.price <= self.price:
                yield offer
                self.offers.append(offer)

    def check_offers(self):
        """Check the expiration status of offers, and get a list of expired and
        a list of expiring offers.
        """
        updates = {
            'expired': list(),
            'expiring': list()
        }

        for offer in self.offers:
            if offer.expired():
                self.offers.remove(offer)
                self.warned.remove(offer)
                updates['expired'].append(offer)
            elif offer.expiring() and offer not in self.warned:
                self.warned.add(offer)
                updates['expiring'].append(offer)

        for offer in updates['expired']:
            self.offers.remove(offer)

        return updates
