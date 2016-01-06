import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pytz import timezone
from enum import Enum

import httplib2
from configparser import ConfigParser

from apiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.tools import run_flow, argparser

service = None

tz = timezone("America/Los_Angeles")

config = ConfigParser()
config.read('config')


class RSVP(Enum):
    yes = 'yes'
    maybe = 'maybe'
    no = 'no'
    unknown = 'reply here'

    @classmethod
    def from_string(cls, string):
        for rsvp in cls:
            if rsvp.value == string:
                return rsvp

        raise Exception("no such reply known")


class Game:

    def __init__(self, date, rink, home, away, rsvp, duration=timedelta(hours=1.5)):
        self.date = date
        self.duration = duration
        self.rink = rink
        self.home = home
        self.away = away
        self.rsvp = RSVP.from_string(rsvp.lower())

    def __str__(self):
        return "{} @ {} {} {} {}".format(self.home, self.away, self.date, self.rink, self.rsvp)

    def __repr__(self):
        return str(self)

    def get_summary(self):
        return "{} @ {}".format(self.away, self.home)


def setup_google():
    global service

    client_id = config.get('google', 'id')
    client_secret = config.get('google', 'secret')

    scope = 'https://www.googleapis.com/auth/calendar'

    flow = OAuth2WebServerFlow(client_id, client_secret, scope)
    storage = Storage('credentials.dat')

    credentials = storage.get()

    if credentials is None or credentials.invalid:
        credentials = run_flow(flow, storage, argparser.parse_args([]))

    http = httplib2.Http()
    http = credentials.authorize(http)

    service = build('calendar', 'v3', http=http)


def get_games():
    def convertGame(game):
        infos = game('td')
        date = datetime.strptime(infos[0].get_text(), '%a %b %d %I:%M %p')
        date = date.replace(year=datetime.now().year)
        date = tz.localize(date)

        if date < tz.localize(datetime.now()):
            date = date.replace(year=datetime.now().year + 1)

        return Game(date, *map(lambda x: x.get_text(), infos[1:]))

    s = requests.Session()
    r = s.get('http://hockeyvite.com/session/new')
    text = BeautifulSoup(r.text, 'html.parser')

    submit = {'login': config.get(
        'hockeyvite', 'username'), 'password': config.get('hockeyvite', 'password')}
    for field in text.form.find_all("input")[:2]:
        submit[field['name']] = field['value']

    s.post('http://hockeyvite.com/session', data=submit)

    games = BeautifulSoup(
        s.get('http://hockeyvite.com/games').text, 'html.parser')

    return map(convertGame, games.select('table tr.txt11'))


def create_event(game):
    start = game.date
    end = game.date + game.duration
    sub_teams = config.get('teams', 'sub').split(',')

    result = service.events().list(calendarId="primary",
                                   orderBy="startTime",
                                   singleEvents=True,
                                   sharedExtendedProperty="hockeyvite=true",
                                   timeMax=(
                                       start + timedelta(seconds=5)).isoformat(),
                                   timeMin=start.isoformat())
    results = result.execute()
    if(len(results.get('items', [])) > 0):
        if game.rsvp is RSVP.no:
            for event in results.get('items'):
                if event.get('summary', '') == game.get_summary() and event['start']['dateTime'] == game.date.isoformat():
                    print("deleting event for 'no' RSVP", game)
                    service.events().delete(
                        calendarId="primary", eventId=event['id']).execute()
        if game.get_summary() not in (event.get('summary', '') for event in results.get('items')):
            pass
        else:
            print("not creating", game, "because it already exists")
            return

    if game.rsvp in (RSVP.yes, RSVP.maybe):

        if game.rsvp is RSVP.maybe and (game.home in sub_teams or game.away in sub_teams):
            print("not creating because sub", game)
            return

        result = service.events().insert(calendarId="primary", body={'start': {'dateTime': start.isoformat()},
                                                                     'summary': game.get_summary(),
                                                                     'location': game.rink,
                                                                     'end': {'dateTime': end.isoformat()},
                                                                     'reminders': {'useDefault': False},
                                                                     'colorId': '7',
                                                                     'extendedProperties': {'shared': {'hockeyvite': True}}}).execute()
        print('created', game)


if __name__ == '__main__':
    setup_google()
    list(map(create_event, get_games()))
