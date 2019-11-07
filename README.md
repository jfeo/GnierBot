GnierBot
========

A telegram bot, that can be used to subscribe to offers using the ShopGun API.

Dependencies
------------

The dependencies of the project are managed by `pipenv`.

Setup
-----

Simply run `pipenv install` in the repository.

Usage
-----

Executing `pipenv run python bot.py` will start the bot.


Configuration
-------------

It is required to setup a `config.py` configuration file simply containing
the required API keys and tokens.

    SHOPGUN_API_KEY=<API key here>
    SHOPGUN_API_SECRET=<API secret here>
    SHOPGUN_TRACKID=<Track id here>
    TELEGRAM_TOKEN=<Token here>

