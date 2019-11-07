import requests
import json
import hashlib

from dateutil.parser import isoparse

from config import SHOPGUN_API_KEY as api_key, SHOPGUN_API_SECRET as api_secret


class Session(object):

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

    def search(self, query, lat=None, lon=None, radius=None):
        params = {
            "_token": self.token,
            "_signature": self.signature,
            "query": query
        }
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


class Offer(object):

    def __init__(self, item: dict):
        self.ident = item.get('id')
        self.ern = item.get('ern')
        self.heading = item.get('heading')
        self.run_till = isoparse(
            item['run_till']) if 'run_till' in item else None
        self.run_from = isoparse(
            item['run_from']) if'run_from' in item else None
        self.pricing = item.get('pricing')
        self.quantity = item.get('quantity')
        self.store = item['branding']['name']
