"""Implementation of part of the ShopGun API."""

import json
import hashlib
from datetime import datetime, timedelta

import requests
from dateutil.parser import isoparse

from config import SHOPGUN_API_KEY as api_key, SHOPGUN_API_SECRET as api_secret


class Session:
    """A session for the ShopGun API."""

    def __init__(self):
        self.api_url = "https://api.etilbudsavis.dk/v2"
        body = {}
        body['api_key'] = api_key
        response = requests.post(
            f"{self.api_url}/sessions",
            data=json.dumps(body),
            headers={'Content-Type': 'application/json'})
        if response.status_code == 201:
            data = response.json()
            self.token = data['token']
            self.signature = hashlib.sha256(api_secret.encode(
                'utf-8') + self.token.encode('utf-8')).hexdigest()
        else:
            raise Exception("Kunne ikke starte session.")

    def search(self, query, lat=None, lon=None, radius=None, limit=None,
               offset=None):
        """Search for the given query, within the given radius starting from
        the giving geolocation. Paginate with limit and offset. Return a
        generator yielding Offers."""

        params = {
            "_token": self.token,
            "_signature": self.signature,
            "query": query
        }

        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if lat is not None:
            params["r_lat"] = lat
        if lon is not None:
            params["r_lng"] = lon
        if radius is not None:
            params["r_radius"] = radius

        queryparts = map(lambda param: '='.join(map(str, param)),
                         params.items())

        response = requests.get(
            f"{self.api_url}/offers/search?{'&'.join(queryparts)}")

        for item in response.json():
            yield Offer(item)

    def search_all(self, query, lat=None, lon=None, radius=None):
        """Search that paginates to retrieve all Offers."""
        contd = True
        offset = 0
        while contd:
            before = offset
            for offer in self.search(query, lat, lon, radius, limit=100,
                                     offset=offset):
                offset += 1
                yield offer
            contd = offset - before == 100


class Offer:
    """Represents a single Offer, a result from an Offer search."""

    def __init__(self, item: dict):
        self.ident = item.get('id')
        self.heading = item.get('heading')
        self.run_till = isoparse(
            item['run_till']) if 'run_till' in item else None
        self.run_from = isoparse(
            item['run_from']) if'run_from' in item else None
        self.price = item.get('pricing').get('price')
        self.quantity = item.get('quantity')
        self.store = item['branding']['name']
        self.images = item.get('images')

    def timeleft(self):
        """Get the time left on the offer."""
        if not self.run_till:
            return None

        return self.run_till - datetime.now(self.run_till.tzinfo)

    def expiring(self):
        """Is the offer expiring soon?"""
        timeleft = self.timeleft()
        if not timeleft:
            return None
        return timeleft < timedelta(days=2)

    def expired(self):
        """Is the offer expired?"""
        timeleft = self.timeleft()
        if not timeleft:
            return None
        return timeleft < timedelta(seconds=0)
