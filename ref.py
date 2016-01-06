import requests
from bs4 import BeautifulSoup
from enum import Enum

from datetime import timedelta, datetime, date
from pytz import timezone

import sync

tz = timezone("America/Los_Angeles")


class Type(Enum):
    ref = 'ref'
    line = 'line'
    play = 'play'
    avail = 'avail'
    event = 'event'

    @classmethod
    def from_string(cls, string):
        for resp in cls:
            if resp.value == string.lower():
                return resp

        raise Exception("no such game type known " + string.lower())


class Game:

    def __init__(self, date, resp, location, league, duration=timedelta(hours=1.25)):
        self.date = date
        self.location = location
        self.league = league
        self.duration = duration
        self.resp = Type.from_string(resp.lower())

    def __str__(self):
        return "{} {} {} @ {}".format(self.date, self.resp, self.league, self.location)

    def __repr__(self):
        return str(self)

    def get_summary(self):
        return "{} {}".format(self.resp.name.title(), self.league)


def get_games(span=14):
    def createGames(date):
        games = BeautifulSoup(s.get("http://ihonc-ca.com/members/dayview.cgi",
                                    params={'date': date.strftime('%Y-%m-%d')}).text, 'html.parser')
        form = games.find('form')
        if not form:
            return []
        games = []
        for row in form.find_all('input', {'type': 'checkbox'}):
            row = row.find_parent('tr').find_all("td")
            row = [x.text for x in row[2:]]
            row[1] = row[1].replace('a', 'AM')
            row[1] = row[1].replace('p', 'PM')

            if Type.from_string(row[3]) not in (Type.ref, Type.line):
                continue

            when = datetime.strptime(
                '{} {}'.format(*row[:2]), '%a %b %d %I:%M%p')
            when = when.replace(year=datetime.now().year)
            when = tz.localize(when)

            if when < tz.localize(datetime.now()):
                when = when.replace(year=datetime.now().year + 1)

            games.append(Game(when, *(x for x in row[3:] if x)))
        return games

    s = requests.Session()
    s.post("http://ihonc-ca.com/members/index.cgi",
           data={'login_username': sync.config.get('ihonc', 'username'), 'login_password': sync.config.get('ihonc', 'password')})

    games = []
    for l in (createGames(date.today() + x * timedelta(days=1)) for x in range(span)):
        games.extend(l)

    for game in games:
        start = game.date
        end = game.date + game.duration

        result = sync.service.events().list(calendarId="primary",
                                            orderBy="startTime",
                                            singleEvents=True,
                                            sharedExtendedProperty="hockeyref=true",
                                            timeMax=(
                                                start + timedelta(seconds=5)).isoformat(),
                                            timeMin=start.isoformat())
        results = result.execute()
        if(len(results.get('items', [])) > 0):
            print("Not creating {} because it already exists".format(game))

        else:
            # create the event
            result = sync.service.events().insert(calendarId="primary", body={'start': {'dateTime': start.isoformat()},
                                                                         'summary': game.get_summary(),
                                                                         'location': game.location,
                                                                         'end': {'dateTime': end.isoformat()},
                                                                         'reminders': {'useDefault': False},
                                                                         'colorId': '6',
                                                                         'extendedProperties': {'shared': {'hockeyref': True}}}).execute()
            print("Created {}".format(game))

if __name__ == '__main__':
    sync.setup_google()
    get_games()
